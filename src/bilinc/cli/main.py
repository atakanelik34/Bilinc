#!/usr/bin/env python3
"""Bilinc cloud-only CLI."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from typing import Any

from bilinc import __version__
from bilinc.client import (
    ACTIVATION_SIGNUP_URL,
    BilincApiKeyRequired,
    BilincCloudError,
    CloudClient,
    INSTALL_URL,
    MEMORY_TYPES,
    SIGNUP_URL,
    VALUE_MODES,
    config_path,
    load_config_api_key,
    save_config_api_key,
)
from bilinc.cli.login import LoginError, device_login, is_headless, loopback_login


def _parse_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _short_time(value: Any) -> str:
    """Render an ISO-8601 timestamp as `YYYY-MM-DD HH:MM:SS` UTC for tables."""
    if not isinstance(value, str) or not value:
        return "-"
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _short_value(value: Any, width: int = 60) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


def _print_history(payload: dict[str, Any]) -> None:
    key = payload.get("key", "")
    entries = payload.get("entries") or []
    if not entries:
        print(f"No recorded changes for {key}.")
        return
    state = "" if payload.get("exists", True) else ", forgotten"
    print(f"{key}  ({len(entries)} shown, newest first{state})")
    for entry in entries:
        op = str(entry.get("op", "?"))
        line = f"  {_short_time(entry.get('at'))}  {op:<8}"
        if entry.get("valuesRedacted"):
            line += "  (value not shown: the memory was forgotten)"
        elif "before" in entry and "after" in entry and op != "confirm":
            line += f"  {_short_value(entry['before'], 30)} -> {_short_value(entry['after'], 30)}"
        elif "after" in entry:
            line += f"  {_short_value(entry['after'])}"
        if entry.get("reason"):
            line += f"  reason: {_short_value(entry['reason'], 40)}"
        if entry.get("source"):
            line += f"  source: {entry['source']}"
        print(line)
    if payload.get("truncated"):
        print("  … older changes not shown; raise --limit to see more.")


def _continuation_command(next_cursor: str, filters: dict[str, Any] | None) -> str:
    """The `bilinc list` command for the next page, with the same filters.

    A cursor only marks a position; the filters must be repeated or the next
    page would cover a different set of memories.
    """

    parts = ["bilinc list"]
    flags = {
        "prefix": "--prefix",
        "memory_type": "--type",
        "updated_after": "--updated-after",
        "updated_before": "--updated-before",
        "limit": "--limit",
    }
    for name, flag in flags.items():
        value = (filters or {}).get(name)
        if value is not None and value != "":
            parts.append(f"{flag} {shlex.quote(str(value))}")
    values = (filters or {}).get("values")
    if values and values != "preview":
        parts.append(f"--values {shlex.quote(str(values))}")
    parts.append(f"--cursor {shlex.quote(next_cursor)}")
    return " ".join(parts)


def _print_memories(
    entries: list[dict[str, Any]],
    *,
    total: Any,
    next_cursor: Any,
    filters: dict[str, Any] | None = None,
) -> None:
    if not entries:
        print("No memories match.")
        return
    key_width = min(max(len(str(entry.get("key", ""))) for entry in entries), 40)
    print(f"{'KEY':<{key_width}}  {'TYPE':<10}  {'UPDATED (UTC)':<19}  VALUE")
    for entry in entries:
        key = _short_value(str(entry.get("key", "")), key_width)
        value = _short_value(entry["value"]) if "value" in entry else ""
        print(
            f"{key:<{key_width}}  {str(entry.get('memoryType', '-')):<10}  "
            f"{_short_time(entry.get('updatedAt')):<19}  {value}"
        )
    summary = f"{len(entries)} shown"
    if isinstance(total, int):
        summary += f" of {total}"
    print(summary)
    if isinstance(next_cursor, str) and next_cursor:
        print(f"More: {_continuation_command(next_cursor, filters)}  (or --all)")


def _write_private_json(path: str, payload: dict[str, Any]) -> None:
    """Write an export owner-only: it holds the full memory contents."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    # The creation mode is ignored when the file already exists, so tighten an
    # existing file before any memory content is written into it.
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False))
        handle.write("\n")


def _client(args: argparse.Namespace) -> CloudClient:
    return CloudClient(api_key=args.api_key, base_url=args.base_url, timeout=args.timeout)


def _has_key(args: argparse.Namespace) -> bool:
    return bool(args.api_key or os.environ.get("BILINC_API_KEY") or load_config_api_key())


def _print_start_guide(*, opened: bool = False) -> None:
    _print(
        {
            "next": "Connect this computer to Bilinc Cloud",
            "goal": "Sign in once from the terminal and finish with bilinc quicktest.",
            "steps": [
                "1. Run: bilinc login  (opens your browser; sign in with Google, GitHub, or email)",
                "2. Run: bilinc quicktest",
            ],
            "no_browser_on_this_machine": "bilinc login --device",
            "ci": "bilinc login --api-key <key>, or set BILINC_API_KEY",
            "pricing": "Free, no card required",
            "signup": ACTIVATION_SIGNUP_URL,
            "install_guide": INSTALL_URL,
            "opened_browser": opened,
        }
    )


MCP_KEY_PLACEHOLDER = "bil_live_..."


def _mcp_server_entry() -> dict[str, Any]:
    # The absolute interpreter works where a bare `python` does not: macOS ships
    # only python3, and Claude Desktop launches servers without the shell PATH.
    entry: dict[str, Any] = {"command": sys.executable, "args": ["-m", "bilinc.cloud_mcp"]}
    if not load_config_api_key():
        # With a key saved by `bilinc login` the adapter reads it itself, so the
        # client config carries no key at all. Without one, the client must pass it.
        entry["env"] = {"BILINC_API_KEY": MCP_KEY_PLACEHOLDER}
    return entry


def _mcp_config() -> dict[str, Any]:
    return {"mcpServers": {"bilinc": _mcp_server_entry()}}


def _claude_code_command() -> str:
    argv = ["claude", "mcp", "add", "--scope", "user", "bilinc"]
    if not load_config_api_key():
        argv += ["-e", f"BILINC_API_KEY={MCP_KEY_PLACEHOLDER}"]
    argv += ["--", sys.executable, "-m", "bilinc.cloud_mcp"]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _claude_desktop_config_path() -> str:
    if sys.platform == "darwin":
        return "~/Library/Application Support/Claude/claude_desktop_config.json"
    if os.name == "nt":
        return r"%APPDATA%\Claude\claude_desktop_config.json"
    return "~/.config/Claude/claude_desktop_config.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bilinc",
        description="Bilinc Cloud memory SDK. Start with `bilinc start`.",
    )
    parser.add_argument("--version", action="version", version=f"bilinc {__version__}")
    parser.add_argument("--api-key", help="Bilinc Cloud API key. Defaults to BILINC_API_KEY.")
    parser.add_argument("--base-url", default="https://bilinc.space", help="Bilinc Cloud base URL")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")

    sub = parser.add_subparsers(dest="command")

    start = sub.add_parser("start", help="Open the simplest path from install to first memory")
    start.add_argument("--open", action="store_true", help="Open the Bilinc signup page in a browser")

    login = sub.add_parser(
        "login",
        help="Sign in from your browser and save an API key for this computer",
    )
    login.add_argument("--api-key", help="Save this API key instead of signing in (for CI)")
    login.add_argument(
        "--device",
        action="store_true",
        help="Sign in with a code approved in any browser (for SSH sessions and servers)",
    )
    login.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the sign-in URL instead of opening a browser",
    )
    login.add_argument("--open", action="store_true", help=argparse.SUPPRESS)

    commit = sub.add_parser("commit", help="Commit a memory entry to Bilinc Cloud")
    commit.add_argument("--key", required=True)
    commit.add_argument("--value", required=True, help="JSON value or plain string")
    commit.add_argument(
        "--type",
        default="semantic",
        choices=["episodic", "procedural", "semantic", "working", "spatial"],
    )
    commit.add_argument("--importance", type=float, default=1.0)
    commit.add_argument("--metadata", default="{}", help="JSON object metadata")

    recall = sub.add_parser("recall", help="Recall memories from Bilinc Cloud")
    recall.add_argument("--query", required=True)
    recall.add_argument("--profile", choices=["fast", "balanced", "verified", "deep"], default="balanced")
    recall.add_argument("--limit", type=int, default=10)

    revise = sub.add_parser("revise", help="Deliberately replace an existing memory")
    revise.add_argument("--key", required=True)
    revise.add_argument("--value", required=True, help="JSON value or plain string")
    revise.add_argument("--importance", type=float, default=1.0)
    revise.add_argument(
        "--strategy",
        default="entrenchment",
        choices=["entrenchment", "recency", "verification", "importance"],
    )
    revise.add_argument("--reason", help="Why this memory is being revised")
    revise.add_argument("--expected-version", help="Fail if the memory changed since this version")

    forget = sub.add_parser("forget", help="Remove a memory from active recall (destructive)")
    forget.add_argument("--key", required=True)
    forget.add_argument("--reason", required=True, help="Required audit reason for the deletion")
    forget.add_argument("--expected-version", help="Fail if the memory changed since this version")

    confirm = sub.add_parser("confirm", help="Record that an existing memory is still accurate")
    confirm.add_argument("key", help="Memory key")
    confirm.add_argument("--expected-version", help="Fail if the memory changed since this version")
    confirm.add_argument("--reason", help="Optional note recorded in the memory's history")

    history = sub.add_parser("history", help="Show one memory's recorded changes, newest first")
    history.add_argument("key", help="Memory key")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--values", choices=VALUE_MODES, default="full", help="How much of each value to show")
    history.add_argument("--json", action="store_true", help="Print the raw JSON response")

    list_cmd = sub.add_parser("list", help="List stored memories, ordered by key")
    list_cmd.add_argument("--prefix", help="Only keys starting with this text")
    list_cmd.add_argument("--type", choices=MEMORY_TYPES, help="Only this memory type")
    list_cmd.add_argument("--updated-after", help="Only memories updated after this ISO-8601 time")
    list_cmd.add_argument("--updated-before", help="Only memories updated before this ISO-8601 time")
    list_cmd.add_argument("--limit", type=int, default=50, help="Page size (1-100)")
    list_cmd.add_argument("--cursor", help="Continue from a previous page")
    list_cmd.add_argument("--all", action="store_true", help="Follow every page")
    list_cmd.add_argument("--values", choices=VALUE_MODES, default="preview", help="How much of each value to show")
    list_cmd.add_argument("--json", action="store_true", help="Print the raw JSON response")

    export = sub.add_parser("export", help="Export every stored memory with its full value as JSON")
    export.add_argument("-o", "--output", help="Write to this file (owner-only) instead of stdout")
    export.add_argument("--prefix", help="Only keys starting with this text")
    export.add_argument("--type", choices=MEMORY_TYPES, help="Only this memory type")

    snapshot = sub.add_parser("snapshot", help="Create or list project checkpoints")
    snapshot.add_argument("action", choices=["create", "list"], nargs="?", default="create")
    snapshot.add_argument("--label", help="Human-readable label for a new checkpoint")
    snapshot.add_argument("--metadata", default="{}", help="JSON object metadata for a new checkpoint")
    snapshot.add_argument("--limit", type=int, default=20, help="How many checkpoints to list")

    diff = sub.add_parser("diff", help="Compare a snapshot with another snapshot or current state")
    diff.add_argument("--from-snapshot", required=True, help="Baseline snapshot id")
    diff.add_argument("--to-snapshot", help="Target snapshot id. Omit to compare against current state.")
    diff.add_argument("--include-values", action="store_true", help="Include values (redacted by default)")
    diff.add_argument("--limit", type=int, default=100)

    rollback = sub.add_parser(
        "rollback",
        help="Preview or execute a snapshot restore (execute is destructive)",
    )
    rollback.add_argument("mode", choices=["preview", "execute"], nargs="?", default="preview")
    rollback.add_argument("--snapshot", required=True, help="Snapshot id to restore")
    rollback.add_argument("--reason", required=True, help="Required audit reason")
    rollback.add_argument(
        "--confirmation-token",
        help="Token from a preview. Required for execute; there is no interactive prompt.",
    )

    sub.add_parser("status", help="Show the authenticated Cloud workspace, plan, and capabilities")
    sub.add_parser("health", help="Show public Bilinc Cloud service health")
    sub.add_parser("doctor", help="Check local CLI configuration, service health, and account status")
    quicktest = sub.add_parser("quicktest", help="Run one hosted commit, recall, and status check")
    quicktest.add_argument("--key", default=None, help="Memory key for the test write")
    quicktest.add_argument("--value", default='{"status":"ready"}', help="JSON value or plain string")

    mcp = sub.add_parser("mcp", help="Print hosted Cloud MCP adapter configuration")
    mcp_sub = mcp.add_subparsers(dest="mcp_command")
    mcp_install = mcp_sub.add_parser("install", help="Print MCP config for agent runtimes")
    mcp_install.add_argument(
        "--client",
        choices=["json", "claude-code", "claude-desktop"],
        default="json",
        help="json: mcpServers config (default); claude-code: a `claude mcp add` command; "
        "claude-desktop: the config plus where Claude Desktop keeps it",
    )

    sub.add_parser("signup", help="Print the signup URL (free, no card required)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "start":
        opened = False
        if args.open:
            opened = webbrowser.open(ACTIVATION_SIGNUP_URL)
        if not _has_key(args):
            _print_start_guide(opened=opened)
            return 0
        try:
            client = _client(args)
            _print(
                {
                    "ready": True,
                    "config": str(config_path()),
                    "status": client.status(),
                    "next": "Run bilinc quicktest",
                }
            )
        except (BilincApiKeyRequired, BilincCloudError) as exc:
            print(f"bilinc: error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "login":
        if args.api_key:
            try:
                path = save_config_api_key(args.api_key, base_url=args.base_url)
            except BilincApiKeyRequired as exc:
                print(f"bilinc: error: {exc}", file=sys.stderr)
                return 1
            _print({"saved": True, "config": str(path), "next": "Run bilinc quicktest"})
            return 0
        try:
            if args.device or is_headless():
                result = device_login(args.base_url, timeout=args.timeout)
            else:
                result = loopback_login(args.base_url, timeout=args.timeout, open_browser=not args.no_browser)
            api_key = result.get("api_key")
            if not isinstance(api_key, str) or not api_key:
                raise LoginError("Bilinc Cloud did not return an API key. Run bilinc login again.")
            path = save_config_api_key(api_key, base_url=args.base_url)
        except (LoginError, BilincApiKeyRequired, BilincCloudError) as exc:
            print(f"bilinc: error: {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("bilinc: login cancelled", file=sys.stderr)
            return 130
        _print(
            {
                "saved": True,
                "config": str(path),
                "api_key_name": result.get("key_name"),
                "next": "Run bilinc quicktest",
            }
        )
        return 0

    if args.command == "signup":
        _print(
            {
                "signup": ACTIVATION_SIGNUP_URL,
                "base_signup": SIGNUP_URL,
                "pricing": "Free, no card required",
                "next": "Run bilinc login to sign in from your browser, then bilinc quicktest",
            }
        )
        return 0
    if args.command == "mcp" and args.mcp_command == "install":
        # stdout stays copy-paste clean; guidance goes to stderr.
        if args.client == "claude-code":
            print(_claude_code_command())
        else:
            _print(_mcp_config())
        if args.client == "claude-desktop":
            print(
                f'Merge the "bilinc" entry into mcpServers in {_claude_desktop_config_path()}, '
                "then restart Claude Desktop.",
                file=sys.stderr,
            )
        if not load_config_api_key():
            print(
                f"No saved key yet: run `bilinc login` first, or replace {MCP_KEY_PLACEHOLDER} with your API key.",
                file=sys.stderr,
            )
        return 0
    if args.command is None:
        parser.print_help()
        return 0

    try:
        client = _client(args)
        if args.command == "commit":
            metadata = _parse_value(args.metadata)
            if not isinstance(metadata, dict):
                raise ValueError("--metadata must be a JSON object")
            _print(
                client.commit(
                    args.key,
                    _parse_value(args.value),
                    memory_type=args.type,
                    importance=args.importance,
                    metadata=metadata,
                )
            )
        elif args.command == "recall":
            _print(client.recall(args.query, profile=args.profile, limit=args.limit))
        elif args.command == "revise":
            _print(
                client.revise(
                    args.key,
                    _parse_value(args.value),
                    importance=args.importance,
                    strategy=args.strategy,
                    reason=args.reason,
                    expected_version=args.expected_version,
                )
            )
        elif args.command == "forget":
            _print(
                client.forget(
                    args.key,
                    reason=args.reason,
                    expected_version=args.expected_version,
                )
            )
        elif args.command == "confirm":
            _print(
                client.confirm(
                    args.key,
                    expected_version=args.expected_version,
                    reason=args.reason,
                )
            )
        elif args.command == "history":
            result = client.history(args.key, limit=args.limit, values=args.values)
            if args.json:
                _print(result)
            else:
                _print_history(result)
        elif args.command == "list":
            filters = {
                "prefix": args.prefix,
                "memory_type": args.type,
                "updated_after": args.updated_after,
                "updated_before": args.updated_before,
                "values": args.values,
            }
            if args.all:
                entries = list(client.iter_memories(page_size=args.limit, **filters))
                if args.json:
                    _print({"entries": entries, "count": len(entries)})
                else:
                    _print_memories(entries, total=len(entries), next_cursor=None)
            else:
                result = client.list_memories(cursor=args.cursor, limit=args.limit, **filters)
                if args.json:
                    _print(result)
                else:
                    _print_memories(
                        result.get("entries") or [],
                        total=result.get("total"),
                        next_cursor=result.get("nextCursor"),
                        filters={**filters, "limit": args.limit},
                    )
        elif args.command == "export":
            exported = client.export(prefix=args.prefix, memory_type=args.type)
            if args.output:
                _write_private_json(args.output, exported)
                print(f"Exported {exported['count']} memories to {args.output}", file=sys.stderr)
            else:
                _print(exported)
        elif args.command == "snapshot":
            if args.action == "list":
                _print(client.list_snapshots(limit=args.limit))
            else:
                metadata = _parse_value(args.metadata)
                if not isinstance(metadata, dict):
                    raise ValueError("--metadata must be a JSON object")
                _print(client.create_snapshot(label=args.label, metadata=metadata))
        elif args.command == "diff":
            _print(
                client.diff(
                    args.from_snapshot,
                    to_snapshot_id=args.to_snapshot,
                    include_values=args.include_values,
                    limit=args.limit,
                )
            )
        elif args.command == "rollback":
            if args.mode == "execute":
                if not args.confirmation_token:
                    raise ValueError(
                        "rollback execute requires --confirmation-token from a preview"
                    )
                _print(
                    client.rollback(
                        args.snapshot,
                        confirmation_token=args.confirmation_token,
                        reason=args.reason,
                    )
                )
            else:
                _print(client.rollback_preview(args.snapshot, reason=args.reason))
        elif args.command == "status":
            _print(client.status())
        elif args.command == "health":
            _print(client.health())
        elif args.command == "doctor":
            _print(
                {
                    "config": str(config_path()),
                    "api_key_configured": True,
                    "cloud_health": client.health(),
                    "account_status": client.status(),
                    "next": "Run bilinc quicktest",
                }
            )
        elif args.command == "quicktest":
            key = args.key or f"bilinc.quicktest.{int(time.time())}"
            value = _parse_value(args.value)
            previous_command = os.environ.get("BILINC_CLIENT_COMMAND")
            os.environ["BILINC_CLIENT_COMMAND"] = "quicktest"
            try:
                commit_result = client.commit(
                    key,
                    value,
                    memory_type="semantic",
                    importance=0.5,
                    metadata={"source": "bilinc-cli-quicktest"},
                )
                recall_result = client.recall(key, profile="balanced", limit=3)
            finally:
                if previous_command is None:
                    os.environ.pop("BILINC_CLIENT_COMMAND", None)
                else:
                    os.environ["BILINC_CLIENT_COMMAND"] = previous_command
            _print(
                {
                    "ok": True,
                    "key": key,
                    "commit": commit_result,
                    "recall": recall_result,
                    "status": client.status(),
                }
            )
        else:
            parser.print_help()
            return 2
    except (BilincApiKeyRequired, BilincCloudError, ValueError) as exc:
        print(f"bilinc: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
