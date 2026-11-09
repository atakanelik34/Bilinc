"""Where a wiki export may go.

Two checks live here. ``cloud_sync_warning`` notices a target inside a
cloud-synced folder and returns one warning line; it never refuses.
``check_mcp_target`` is the stricter guard for the MCP tool, whose caller is
a model choosing a path: it refuses relative paths, home and its ancestors,
system folders, hidden home folders, ``~/Library`` and the Bilinc config
folder. Paths are compared by file identity (``st_dev``, ``st_ino``) where the
file system provides it, so another spelling of a folder (case, symlinked
parents) cannot slip past; casefolded text is the fallback.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from bilinc.client import config_path
from bilinc.wiki.writer import WikiRefused

#: POSIX system folders: refused, and everything inside them.
SYSTEM_ROOTS = (
    "/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/opt", "/proc", "/root",
    "/run", "/sbin", "/srv", "/sys", "/usr", "/var", "/private", "/System", "/Library",
    "/Applications", "/cores",
)

#: Folders that hold drives: refused themselves, a drive under them is allowed.
CONTAINER_ROOTS = ("/Volumes", "/mnt")

#: Folders under ``~/Library`` that are user document locations.
LIBRARY_ALLOWED = frozenset({"mobile documents", "cloudstorage"})


def WINDOWS_ROOTS() -> tuple[str, ...]:  # noqa: N802 - named like the constant it stands for
    """The Windows folder, Program Files and the app data folders, from the environment."""

    names = ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA")
    return tuple(value for name in names if (value := os.environ.get(name)))


def cloud_sync_warning(target: str | os.PathLike, *, home: Path | None = None) -> str | None:
    """Return a warning line when ``target`` sits in a cloud-synced folder, else None."""

    home = Path(home) if home is not None else Path.home()
    for path in _candidates(os.path.abspath(os.path.expanduser(os.fspath(target)))):
        name = _cloud_name(_under(path, home))
        if name:
            return (
                f"warning: {target} is inside a cloud-synced folder ({name}); the sync client may "
                "upload this export, which can hold private data, or keep conflicting copies"
            )
    return None


def check_mcp_target(
    directory: str,
    *,
    home: Path | None = None,
    config_dir: Path | None = None,
    refused_roots: tuple[str, ...] | None = None,
    temp_dirs: tuple[str, ...] | None = None,
) -> Path:
    """Return the resolved export folder for the MCP tool, or raise ``WikiRefused``.

    Changes nothing on disk. The writer's own guards still run afterwards.
    """

    home = Path(home) if home is not None else Path.home()
    config = Path(config_dir) if config_dir is not None else config_path().parent
    if refused_roots is None:
        refused_roots = SYSTEM_ROOTS + (WINDOWS_ROOTS() if os.name == "nt" else ())
    if temp_dirs is None:
        temp_dirs = (os.path.realpath(tempfile.gettempdir()), "/tmp", "/private/tmp")
    temp_dirs = _narrow_temps(temp_dirs, home=home, roots=refused_roots)

    given = os.fspath(directory)
    # Long-path prefix: \\?\C:\x is C:\x, and \\?\UNC\server\share is \\server\share.
    if given.startswith("\\\\?\\"):
        given = given[4:]
        if given[:4].casefold() == "unc\\":
            given = "\\\\" + given[4:]
    if given.startswith("\\\\") or (os.name == "nt" and given.startswith("//")):
        raise WikiRefused(f"{directory} is a network path; give a folder on this computer")

    given = os.path.expanduser(given)
    if not given or not os.path.isabs(given):
        raise WikiRefused(f"{directory!r} is not an absolute path; give the full folder path")
    # Trailing separators and "." or ".." parts make islink follow the link, so
    # normalise first; the folder itself must be what its parent says it is.
    normalised = os.path.normpath(given)
    resolved = Path(os.path.realpath(given))
    name = os.path.basename(normalised)
    link_like = os.path.islink(given.rstrip("/\\") or given) or os.path.islink(normalised)
    moved = bool(name) and Path(os.path.realpath(os.path.dirname(normalised))) / name != resolved
    if link_like or moved:
        raise WikiRefused(f"{directory} is a symbolic link; give the real folder instead")

    for path in _candidates(given):
        reason = _refusal(path, home=home, config=config, roots=refused_roots, temps=temp_dirs)
        if reason:
            shown = str(path) if str(path) == directory else f"{directory} ({path})"
            raise WikiRefused(f"{shown} {reason}")
    reason = _ownership_refusal(resolved)
    if reason:
        raise WikiRefused(f"{directory} {reason}")
    return resolved


def _ownership_refusal(resolved: Path) -> str | None:
    """Refuse a folder another local user could swap out from under the export (POSIX).

    Every existing folder from the target up to the root must not be
    world-writable unless it has the sticky bit (as ``/tmp`` does), where
    nobody else can rename what is inside. An existing target must be ours,
    not world-writable, and group-writable only for a group nobody else is in
    (with a umask of 002 and a group per user that is the normal state of a
    user's own folders).
    """

    if not hasattr(os, "geteuid"):
        return None
    try:
        info = os.stat(resolved)
    except FileNotFoundError:
        info = None
    except OSError:
        return None
    for ancestor in _chain(resolved.parent):
        try:
            mode = os.stat(ancestor).st_mode
        except OSError:
            continue
        if mode & 0o002 and not mode & stat.S_ISVTX:
            return f"sits in {ancestor}, a folder others can write; choose a folder of your own"
    if info is None:
        return None
    if info.st_uid != os.geteuid():
        return "belongs to another user; choose a folder of your own"
    if info.st_mode & 0o002:
        return "is a folder others can write; choose a folder of your own"
    if info.st_mode & 0o020 and not _private_group(info.st_gid):
        return "is writable by a group others share; choose a folder of your own"
    return None


def _private_group(gid: int) -> bool:
    """True when ``gid`` is our group and no other account belongs to it."""

    import grp
    import pwd

    if gid != os.getegid():
        return False
    me = pwd.getpwuid(os.geteuid()).pw_name
    try:
        members = set(grp.getgrgid(gid).gr_mem)
    except KeyError:
        return False
    if members - {me}:
        return False
    return all(entry.pw_name == me for entry in pwd.getpwall() if entry.pw_gid == gid)


#: Where a system temp folder may live for the carve-out to apply.
TEMP_BASES = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")


def _narrow_temps(temps: tuple[str, ...], *, home: Path, roots: tuple[str, ...]) -> tuple[str, ...]:
    """Keep only temp folders that are real temp locations.

    ``tempfile.gettempdir()`` follows ``TMPDIR``, which could name ``/``, a
    system folder or a folder inside one. A temp folder is kept when it sits
    in ``/tmp``, ``/private/tmp``, macOS's ``/var/folders`` (or, on Windows,
    ``%LOCALAPPDATA%\\Temp``), and is neither home, an ancestor of home, nor a
    refused root or one of its ancestors.
    """

    bases = [Path(base) for base in TEMP_BASES]
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        bases.append(Path(os.environ["LOCALAPPDATA"]) / "Temp")
    kept = []
    for temp in temps:
        path = Path(os.path.realpath(temp))
        literal = Path(os.path.normpath(temp))
        if not any(candidate == base or base in candidate.parents for base in bases for candidate in (path, literal)):
            continue
        if _under(home, path) is not None:
            continue
        if any(_under(Path(root), path) is not None for root in roots):
            continue
        kept.append(temp)
    return tuple(kept)


def _candidates(given: str) -> list[Path]:
    """The real path and the normalised given path; both must pass."""

    resolved = Path(os.path.realpath(given))
    normalised = Path(os.path.normpath(given))
    return [resolved] if normalised == resolved else [resolved, normalised]


def _refusal(
    path: Path, *, home: Path, config: Path, roots: tuple[str, ...], temps: tuple[str, ...]
) -> str | None:
    """Why ``path`` may not hold an export, or None."""

    if path == Path(path.anchor):
        return "is the root of a drive; choose a folder inside your documents"
    if _under(home, path) is not None:
        return "is your home folder or contains it; choose a folder inside it"
    if _under(path, config) is not None or _under(config, path) is not None:
        return "is, holds or sits in the Bilinc config folder, which keeps your key"
    # The temp carve-out is weighed before the system-folder rule, and lifts only that rule.
    if not any(_under(path, Path(temp)) is not None for temp in temps):
        for root in roots:
            if _under(path, Path(root)) is not None:
                return f"is in the system folder {root}"
    for root in CONTAINER_ROOTS:
        if _under(path, Path(root)) == ():
            return "holds drives; choose a folder on one of them"
    parts = _under(path, home) or ()
    if any(part.startswith(".") for part in parts):
        return "is in a hidden folder of your home"
    if parts and parts[0].casefold() == "library":
        if len(parts) < 2 or parts[1].casefold() not in LIBRARY_ALLOWED:
            return "is in ~/Library, which holds app data"
    return None


def _cloud_name(parts: tuple[str, ...] | None) -> str | None:
    """The cloud service a home-relative path belongs to, or None."""

    if not parts:
        return None
    folded = [part.casefold() for part in parts]
    if folded[:2] == ["library", "mobile documents"]:
        return "iCloud Drive"
    if folded[:2] == ["library", "cloudstorage"] and len(parts) > 2:
        return parts[2]
    if folded[0] == "dropbox":
        return "Dropbox"
    if folded[0].startswith("onedrive"):
        return parts[0]
    return None


def _identity(path: Path) -> tuple[int, int] | None:
    try:
        info = os.stat(path)
    except OSError:
        return None
    # Windows may report no inode number; text comparison takes over then.
    return (info.st_dev, info.st_ino) if info.st_ino else None


def _chain(path: Path) -> list[Path]:
    """``path`` and its ancestors that exist, nearest first."""

    return [p for p in (path, *path.parents) if os.path.lexists(p)]


def _under(path: Path, root: Path) -> tuple[str, ...] | None:
    """The components of ``path`` below ``root`` (``()`` when equal), or None when outside.

    Matches by file identity where available, else by casefolded real path text.
    """

    wanted = _identity(root)
    if wanted is not None:
        for ancestor in _chain(path):
            if _identity(ancestor) == wanted:
                return path.relative_to(ancestor).parts
        return None
    real_path, real_root = Path(os.path.realpath(path)), Path(os.path.realpath(root))
    text = os.path.normcase(str(real_path)).casefold()
    base = os.path.normcase(str(real_root)).casefold()
    if text == base:
        return ()
    if text.startswith(base.rstrip(os.sep) + os.sep):
        return real_path.parts[len(real_root.parts):]
    return None
