"""Per-project recall settings stored next to the project's runtime database."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SETTINGS_FILE = "settings.json"
MAX_LOW_SIGNAL_SOURCES = 20
MAX_SOURCE_LENGTH = 120


@dataclass(frozen=True)
class ProjectSettings:
    timezone: str = "UTC"
    low_signal_sources: tuple[str, ...] = ()


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
        if not isinstance(source, str) or not source.strip() or len(source) > MAX_SOURCE_LENGTH:
            raise ValueError("invalid low-signal source")


def load_project_settings(project_dir: Path) -> ProjectSettings:
    """Read settings.json; any problem (missing, corrupt, wrong shape) yields defaults."""
    path = Path(project_dir) / SETTINGS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return ProjectSettings()
        timezone = raw.get("timezone", "UTC")
        sources = raw.get("low_signal_sources", [])
        if not isinstance(timezone, str) or not isinstance(sources, list):
            return ProjectSettings()
        if not all(isinstance(item, str) for item in sources):
            return ProjectSettings()
        settings = ProjectSettings(timezone=timezone, low_signal_sources=tuple(sources))
        _validate(settings)
        return settings
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        return ProjectSettings()


def save_project_settings(project_dir: Path, settings: ProjectSettings) -> None:
    _validate(settings)
    directory = Path(project_dir)
    directory.mkdir(parents=True, exist_ok=True)
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
    current = load_project_settings(project_dir)
    changing = bool(args.timezone or args.low_signal_source or args.clear_low_signal)
    if changing:
        sources = () if args.clear_low_signal else current.low_signal_sources
        if args.low_signal_source:
            sources = tuple(dict.fromkeys([*sources, *(s.strip() for s in args.low_signal_source)]))
        current = ProjectSettings(timezone=args.timezone or current.timezone, low_signal_sources=sources)
        try:
            save_project_settings(project_dir, current)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if args.show or not changing:
        print(json.dumps({"timezone": current.timezone, "low_signal_sources": list(current.low_signal_sources)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
