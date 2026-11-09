"""Where the wiki may go: the cloud-folder warning and the MCP target checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from bilinc.wiki import location
from bilinc.wiki.location import check_mcp_target, cloud_sync_warning
from bilinc.wiki.writer import WikiRefused

# Every test injects home, the config folder, the refused roots and the temp
# folders under tmp_path, so nothing depends on the machine running it.
symlinks = pytest.mark.skipif(os.name == "nt", reason="POSIX symlinks")


@pytest.fixture()
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


@dataclass
class Env:
    home: Path
    config_dir: Path
    system: Path
    temp: Path
    root: Path

    def kwargs(self) -> dict:
        return {
            "config_dir": self.config_dir,
            "refused_roots": (str(self.system),),
            "temp_dirs": (str(self.temp),),
        }

    def check(self, directory) -> Path:
        return check_mcp_target(str(directory), home=self.home, **self.kwargs())

    def refused(self, directory) -> str:
        with pytest.raises(WikiRefused) as caught:
            self.check(directory)
        return str(caught.value)


@pytest.fixture()
def env(tmp_path, home):
    for rel in (".ssh", ".config", "Documents", "Library/x", "Library/Mobile Documents", "Library/CloudStorage"):
        (home / rel).mkdir(parents=True)
    # Outside home, so the config rule is the one that fires (not the hidden-folder rule).
    config_dir = tmp_path / "cfgroot" / "bilinc"
    config_dir.mkdir(parents=True)
    system = tmp_path / "sys"
    (system / "inner").mkdir(parents=True)
    temp = system / "tmp"
    temp.mkdir()
    return Env(home=home, config_dir=config_dir, system=system, temp=temp, root=tmp_path)


@pytest.fixture()
def case_alias(env):
    """Another spelling of ~/.ssh: a symlinked parent whose real path is ~/.ssh."""
    alias = env.home / "SSH-ALIAS"
    alias.symlink_to(env.home / ".ssh", target_is_directory=True)
    return alias


# --- cloud-folder warning -------------------------------------------------


@pytest.mark.parametrize("rel, name", [
    ("Library/Mobile Documents/com~apple~CloudDocs/wiki", "iCloud Drive"),
    ("Library/CloudStorage/Dropbox/wiki", "Dropbox"),
    ("Library/CloudStorage/OneDrive-Personal/wiki", "OneDrive-Personal"),
    ("Dropbox/notes/wiki", "Dropbox"),
    ("OneDrive - Acme/wiki", "OneDrive - Acme"),
])
def test_cloud_warning_names_the_service(home, rel, name):
    message = cloud_sync_warning(home / rel, home=home)
    assert message and name in message and "warning:" in message
    assert message == (
        f"warning: {home / rel} is inside a cloud-synced folder ({name}); the sync client may "
        "upload this export, which can hold private data, or keep conflicting copies"
    )


@symlinks
def test_cloud_warning_follows_symlinks(home, tmp_path):
    (home / "Dropbox").mkdir()
    (tmp_path / "w").symlink_to(home / "Dropbox")
    message = cloud_sync_warning(tmp_path / "w" / "wiki", home=home)
    assert message and "(Dropbox)" in message


def test_no_warning_elsewhere(home):
    assert cloud_sync_warning(home / "Documents" / "wiki", home=home) is None
    assert cloud_sync_warning(home / "DropboxBackup", home=home) is None
    assert cloud_sync_warning(home / "Library" / "CloudStorage", home=home) is None


# --- MCP target checks ----------------------------------------------------


@pytest.mark.parametrize("given", ["relative/wiki", "", "./x"])
def test_mcp_refuses_relative(env, given):
    assert "absolute" in env.refused(given)


@pytest.mark.parametrize("rel", [".", ".."])  # home itself, ancestor of home
def test_mcp_refuses_home_and_ancestors(env, rel):
    assert "home folder" in env.refused(f"{env.home}{os.sep}{rel}")


def test_mcp_refuses_filesystem_root(env):
    assert env.refused(os.path.abspath(os.sep))


def test_mcp_refuses_system_roots_and_inside(env):
    assert "system folder" in env.refused(env.system)
    assert "system folder" in env.refused(env.system / "inner")
    assert "system folder" in env.refused(env.system / "inner" / "missing" / "wiki")


def test_mcp_refuses_hidden_home_folders(env):
    assert "hidden" in env.refused(env.home / ".ssh" / "wiki")
    assert "hidden" in env.refused(env.home / ".config" / "x")
    assert "hidden" in env.refused(env.home / ".new-hidden")


def test_mcp_refuses_library_but_not_cloud_folders(env):
    assert "Library" in env.refused(env.home / "Library")
    assert "Library" in env.refused(env.home / "Library" / "x")
    icloud = env.home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "wiki"
    assert env.check(icloud) == Path(os.path.realpath(icloud))
    dropbox = env.home / "Library" / "CloudStorage" / "Dropbox" / "wiki"
    assert env.check(dropbox) == Path(os.path.realpath(dropbox))


@pytest.mark.parametrize("where", ["equal", "inside", "containing"])
def test_mcp_refuses_config_dir_equal_inside_or_containing(env, where):
    target = {
        "equal": env.config_dir,
        "inside": env.config_dir / "wiki",
        "containing": env.config_dir.parent,
    }[where]
    assert "config folder" in env.refused(target)


def test_mcp_refuses_config_dir_that_does_not_exist_yet(env):
    env.config_dir = env.root / "fresh" / "bilinc"
    assert "config folder" in env.refused(env.config_dir / "wiki")
    assert "config folder" in env.refused(env.root / "fresh")


@symlinks
@pytest.mark.parametrize("points_to", ["config", "inside"])
def test_mcp_refuses_config_dir_through_symlink(env, points_to):
    real = env.config_dir if points_to == "config" else env.config_dir / "sub"
    real.mkdir(exist_ok=True)
    link = env.root / "elsewhere"
    link.symlink_to(real, target_is_directory=True)
    assert "config folder" in env.refused(link / "wiki")


@symlinks
def test_mcp_refuses_symlinked_last_component(env):
    real = env.home / "Documents" / "real"
    real.mkdir()
    (env.home / "wiki").symlink_to(real, target_is_directory=True)
    assert "symbolic link" in env.refused(env.home / "wiki")
    assert "symbolic link" in env.refused(f"{env.home / 'wiki'}{os.sep}")


@symlinks
def test_mcp_follows_symlinks_in_parents(env):
    (env.home / "link").symlink_to(env.system / "inner", target_is_directory=True)
    assert "system folder" in env.refused(env.home / "link" / "wiki")


@symlinks
def test_mcp_compares_by_identity_not_spelling(env, case_alias):
    assert "hidden" in env.refused(case_alias / "wiki")


@symlinks
def test_mcp_identity_matches_home_given_by_another_spelling(env):
    # Home injected through an alias path: the real target text does not start
    # with the home text, so only (st_dev, st_ino) comparison finds ~/.ssh.
    alias_home = env.root / "home-alias"
    alias_home.symlink_to(env.home, target_is_directory=True)
    with pytest.raises(WikiRefused, match="hidden"):
        check_mcp_target(str(env.home / ".ssh" / "wiki"), home=alias_home, **env.kwargs())
    with pytest.raises(WikiRefused, match="home folder"):
        check_mcp_target(str(env.home), home=alias_home, **env.kwargs())


def test_mcp_temp_carve_out_wins_over_system_root(env):
    wiki = env.temp / "wiki"
    assert env.check(wiki) == Path(os.path.realpath(wiki))
    assert env.check(env.temp) == Path(os.path.realpath(env.temp))
    # The carve-out covers only the temp folder, not its system-root siblings.
    assert "system folder" in env.refused(env.system / "inner")


def test_mcp_temp_carve_out_does_not_lift_other_rules(env):
    env.config_dir = env.temp / "bilinc"
    assert "config folder" in env.refused(env.temp / "bilinc" / "wiki")


def test_mcp_refuses_unc_and_strips_long_prefix(env):
    assert "network" in env.refused("\\\\server\\share\\x")
    assert "network" in env.refused("\\\\?\\UNC\\server\\share\\x")
    wiki = env.home / "Documents" / "wiki"
    assert env.check("\\\\?\\" + str(wiki)) == Path(os.path.realpath(wiki))


def test_mcp_refuses_container_roots_but_not_drives_under_them(env, monkeypatch):
    volumes = env.root / "Volumes"
    (volumes / "Drive").mkdir(parents=True)
    monkeypatch.setattr(location, "CONTAINER_ROOTS", (str(volumes),))
    assert "drive" in env.refused(volumes)
    assert env.check(volumes / "Drive" / "wiki") == Path(os.path.realpath(volumes / "Drive" / "wiki"))


def test_mcp_accepts_a_normal_folder_and_returns_resolved(env):
    wiki = env.home / "Documents" / "wiki"
    result = env.check(wiki)
    assert result == Path(os.path.realpath(wiki))
    assert result.is_absolute() and not wiki.exists()


@pytest.mark.skipif(os.name == "nt", reason="HOME drives expanduser on POSIX only")
def test_mcp_expands_tilde(env, monkeypatch):
    monkeypatch.setenv("HOME", str(env.home))
    result = check_mcp_target("~/Documents/wiki", home=None, **env.kwargs())
    assert result == Path(os.path.realpath(env.home / "Documents" / "wiki"))
    with pytest.raises(WikiRefused, match="hidden"):
        check_mcp_target("~/.ssh/wiki", home=None, **env.kwargs())


def test_windows_roots_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("SystemRoot", "C:\\Windows")
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert location.WINDOWS_ROOTS() == ("C:\\Windows", "C:\\Program Files")


def test_system_roots_list_matches_the_design():
    assert {"/etc", "/usr", "/var", "/private", "/System", "/Library", "/Applications"} <= set(
        location.SYSTEM_ROOTS
    )
    assert "/tmp" not in location.SYSTEM_ROOTS and "/home" not in location.SYSTEM_ROOTS


# --- review round 1: ownership, temp carve-out limits, dot components, AppData -----


@pytest.mark.skipif(not hasattr(os, "geteuid"), reason="POSIX ownership")
def test_mcp_refuses_an_existing_folder_others_can_write(env):
    shared = env.home / "Documents" / "shared"
    shared.mkdir()
    os.chmod(shared, 0o777)
    assert "others can write" in env.refused(shared)
    os.chmod(shared, 0o755)
    assert env.check(shared) == shared.resolve()


@pytest.mark.skipif(not hasattr(os, "geteuid"), reason="POSIX ownership")
def test_mcp_refuses_a_new_folder_in_a_parent_others_can_write_without_sticky_bit(env):
    open_parent = env.home / "Documents" / "open"
    open_parent.mkdir()
    os.chmod(open_parent, 0o777)
    assert "others can write" in env.refused(open_parent / "wiki")
    os.chmod(open_parent, 0o1777)  # like /tmp: a new folder of ours cannot be swapped out
    assert env.check(open_parent / "wiki") == (open_parent / "wiki").resolve()


@pytest.mark.skipif(not hasattr(os, "geteuid"), reason="POSIX ownership")
def test_mcp_refuses_a_folder_owned_by_someone_else(env, monkeypatch):
    target = env.home / "Documents" / "theirs"
    target.mkdir()
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(target).st_uid + 1)
    assert "belongs to another user" in env.refused(target)


@pytest.mark.parametrize("bad_temp", ["/", "home", "system", "home_parent"])
def test_mcp_ignores_a_temp_carve_out_that_is_too_broad(env, bad_temp):
    temp = {
        "/": "/",
        "home": str(env.home),
        "system": str(env.system),
        "home_parent": str(env.home.parent),
    }[bad_temp]
    with pytest.raises(WikiRefused) as caught:
        check_mcp_target(
            str(env.system / "inner" / "wiki"),
            home=env.home,
            config_dir=env.config_dir,
            refused_roots=(str(env.system),),
            temp_dirs=(temp,),
        )
    assert "system folder" in str(caught.value)


@pytest.mark.skipif(os.name == "nt", reason="symlinks")
@pytest.mark.parametrize("suffix", ["/.", "/x/.."])
def test_mcp_refuses_a_symlinked_last_component_spelled_with_dots(env, suffix):
    real = env.home / "Documents" / "real"
    real.mkdir()
    (real / "x").mkdir()
    link = env.home / "Documents" / "link"
    link.symlink_to(real, target_is_directory=True)
    assert "symbolic link" in env.refused(str(link) + suffix)


def test_windows_roots_include_app_data(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\u\AppData\Roaming")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\u\AppData\Local")
    monkeypatch.setenv("ProgramData", r"C:\ProgramData")
    roots = location.WINDOWS_ROOTS()
    assert r"C:\Users\u\AppData\Roaming" in roots and r"C:\Users\u\AppData\Local" in roots
    assert r"C:\ProgramData" in roots
