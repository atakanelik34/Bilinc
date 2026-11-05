"""Per-project recall settings stored next to the project's runtime database."""

from __future__ import annotations

import argparse
import json
import logging
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SETTINGS_FILE = "settings.json"
MAX_LOW_SIGNAL_SOURCES = 20
MAX_SOURCE_LENGTH = 120
# A valid file is well under 3 KB; anything bigger is not a settings file.
MAX_SETTINGS_BYTES = 64 * 1024

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectSettings:
    timezone: str = "UTC"
    low_signal_sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.low_signal_sources, str):
            raise ValueError("low_signal_sources must be a sequence of strings, not a string")
        object.__setattr__(self, "low_signal_sources", tuple(self.low_signal_sources))


def _validate(settings: ProjectSettings) -> None:
    if not isinstance(settings.timezone, str) or not settings.timezone:
        raise ValueError(f"unknown time zone: {settings.timezone!r}")
    try:
        ZoneInfo(settings.timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        # ZoneInfo raises ValueError for path-like keys such as "../etc/passwd".
        raise ValueError(f"unknown time zone: {settings.timezone!r}") from exc
    if len(settings.low_signal_sources) > MAX_LOW_SIGNAL_SOURCES:
        raise ValueError("too many low-signal sources")
    for source in settings.low_signal_sources:
        if (
            not isinstance(source, str)
            or not source
            or source != source.strip()
            or len(source) > MAX_SOURCE_LENGTH
            or not source.isprintable()
        ):
            raise ValueError("invalid low-signal source")


def _read_settings_file(path: Path) -> str:
    """Read a regular, small file without following a symlink or blocking on a FIFO."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SETTINGS_BYTES:
            raise ValueError("not a settings file")
        data = os.read(fd, MAX_SETTINGS_BYTES + 1)
    finally:
        os.close(fd)
    if len(data) > MAX_SETTINGS_BYTES:
        raise ValueError("not a settings file")
    return data.decode("utf-8")


def _parse_settings(text: str) -> ProjectSettings:
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("settings must be an object")
    timezone = raw.get("timezone", "UTC")
    sources = raw.get("low_signal_sources", [])
    if not isinstance(timezone, str) or not isinstance(sources, list):
        raise ValueError("wrong field types")
    if not all(isinstance(item, str) for item in sources):
        raise ValueError("wrong source types")
    settings = ProjectSettings(timezone=timezone, low_signal_sources=tuple(sources))
    _validate(settings)
    return settings


def load_project_settings(project_dir: Path) -> ProjectSettings:
    """Read settings.json; any problem (missing, corrupt, wrong shape) yields defaults.

    Called on every recall, so it never raises. A file that exists but cannot be
    used is logged (without its path or content) so a typo does not go unnoticed.
    """
    path = Path(project_dir) / SETTINGS_FILE
    try:
        return _parse_settings(_read_settings_file(path))
    except FileNotFoundError:
        return ProjectSettings()
    except (OSError, ValueError, TypeError, AttributeError, RecursionError, MemoryError) as exc:
        logger.warning("project settings unusable (%s); using defaults", type(exc).__name__)
        return ProjectSettings()


def save_project_settings(project_dir: Path, settings: ProjectSettings) -> None:
    _validate(settings)
    directory = Path(project_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = json.dumps(
        {"timezone": settings.timezone, "low_signal_sources": list(settings.low_signal_sources)},
        indent=1,
    )
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".settings.", suffix=".json")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, directory / SETTINGS_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    from bilinc.cloud.runtime import ProjectRuntimeManager

    parser = argparse.ArgumentParser(description="Show or change a project's recall settings.")
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--timezone")
    parser.add_argument("--low-signal-source", action="append", default=None)
    parser.add_argument("--clear-low-signal", action="store_true")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)
    try:
        project_dir = ProjectRuntimeManager(args.runtime_dir).project_dir(args.project)
    except ValueError:
        print("error: invalid project id (expected a UUID)", file=sys.stderr)
        return 2
    if not project_dir.is_dir():
        # A mistyped id must not create a phantom project directory.
        print("error: project directory not found", file=sys.stderr)
        return 2
    current = load_project_settings(project_dir)
    changing = args.timezone is not None or bool(args.low_signal_source) or args.clear_low_signal
    if changing:
        sources = () if args.clear_low_signal else current.low_signal_sources
        if args.low_signal_source:
            sources = tuple(dict.fromkeys([*sources, *(s.strip() for s in args.low_signal_source)]))
        timezone = args.timezone if args.timezone is not None else current.timezone
        try:
            current = ProjectSettings(timezone=timezone, low_signal_sources=sources)
            save_project_settings(project_dir, current)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if args.show or not changing:
        print(json.dumps({"timezone": current.timezone, "low_signal_sources": list(current.low_signal_sources)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
