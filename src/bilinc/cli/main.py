#!/usr/bin/env python3
"""Bilinc cloud-only CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import webbrowser
from typing import Any

from bilinc import __version__
from bilinc.client import (
    BilincApiKeyRequired,
    BilincCloudError,
    CloudClient,
    SIGNUP_URL,
    config_path,
    load_config_api_key,
    save_config_api_key,
)


def _parse_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _client(args: argparse.Namespace) -> CloudClient:
    return CloudClient(api_key=args.api_key, base_url=args.base_url, timeout=args.timeout)


def _has_key(args: argparse.Namespace) -> bool:
    return bool(args.api_key or os.environ.get("BILINC_API_KEY") or load_config_api_key())


def _print_start_guide(*, opened: bool = False) -> None:
    _print(
        {
            "next": "Connect Bilinc Cloud",
            "steps": [
                "Start a 7-day trial and confirm email",
                "Create one Cloud API key in the dashboard",
                "Run: bilinc login --api-key <key>",
                "Run: bilinc quicktest",
            ],
            "signup": SIGNUP_URL,
            "opened_browser": opened,
        }
    )


def _mcp_config() -> dict[str, Any]:
    return {
        "mcpServers": {
            "bilinc": {
                "command": "python",
                "args": ["-m", "bilinc.cloud_mcp"],
                "env": {"BILINC_API_KEY": "${BILINC_API_KEY}"},
            }
        }
    }


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

    login = sub.add_parser("login", help="Save a Bilinc Cloud API key for local CLI use")
    login.add_argument("--api-key", help="Bilinc Cloud API key to save locally")
    login.add_argument("--open", action="store_true", help="Open the Bilinc signup page in a browser")

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

    sub.add_parser("status", help="Show Bilinc Cloud account/runtime status")
    sub.add_parser("doctor", help="Check local CLI configuration and Cloud runtime status")
    quicktest = sub.add_parser("quicktest", help="Run one hosted commit, recall, and status check")
    quicktest.add_argument("--key", default=None, help="Memory key for the test write")
    quicktest.add_argument("--value", default='{"status":"ready"}', help="JSON value or plain string")

    mcp = sub.add_parser("mcp", help="Print hosted Cloud MCP adapter configuration")
    mcp_sub = mcp.add_subparsers(dest="mcp_command")
    mcp_sub.add_parser("install", help="Print MCP config for agent runtimes")

    sub.add_parser("signup", help="Print signup URL for a 7-day trial")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "start":
        opened = False
        if args.open:
            opened = webbrowser.open(SIGNUP_URL)
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
        opened = False
        if args.open:
            opened = webbrowser.open(SIGNUP_URL)
        if not args.api_key:
            _print_start_guide(opened=opened)
            return 0
        try:
            path = save_config_api_key(args.api_key, base_url=args.base_url)
        except BilincApiKeyRequired as exc:
            print(f"bilinc: error: {exc}", file=sys.stderr)
            return 1
        _print({"saved": True, "config": str(path), "next": "Run bilinc quicktest"})
        return 0

    if args.command == "signup":
        _print({"signup": SIGNUP_URL, "trial": "7 days"})
        return 0
    if args.command == "mcp" and args.mcp_command == "install":
        _print(_mcp_config())
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
        elif args.command == "status":
            _print(client.status())
        elif args.command == "doctor":
            _print(
                {
                    "config": str(config_path()),
                    "api_key_configured": True,
                    "cloud_health": client.status(),
                    "next": "Run bilinc quicktest",
                }
            )
        elif args.command == "quicktest":
            key = args.key or f"bilinc.quicktest.{int(time.time())}"
            value = _parse_value(args.value)
            commit_result = client.commit(
                key,
                value,
                memory_type="semantic",
                importance=0.5,
                metadata={"source": "bilinc-cli-quicktest"},
            )
            recall_result = client.recall(key, profile="balanced", limit=3)
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
