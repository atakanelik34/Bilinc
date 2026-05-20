#!/usr/bin/env python3
"""Bilinc 2.0 cloud-only CLI."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from bilinc import __version__
from bilinc.client import BilincApiKeyRequired, BilincCloudError, CloudClient, SIGNUP_URL


def _parse_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _client(args: argparse.Namespace) -> CloudClient:
    return CloudClient(api_key=args.api_key, base_url=args.base_url, timeout=args.timeout)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bilinc",
        description="Bilinc 2.0 cloud-only memory SDK. Local StatePlane is no longer bundled.",
    )
    parser.add_argument("--version", action="version", version=f"bilinc {__version__}")
    parser.add_argument("--api-key", help="Bilinc Cloud API key. Defaults to BILINC_API_KEY.")
    parser.add_argument("--base-url", default="https://bilinc.space", help="Bilinc Cloud base URL")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds")

    sub = parser.add_subparsers(dest="command")

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
    sub.add_parser("signup", help="Print signup URL for a 7-day trial")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "signup":
        _print({"signup": SIGNUP_URL, "trial": "7 days"})
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
        else:
            parser.print_help()
            return 2
    except (BilincApiKeyRequired, BilincCloudError, ValueError) as exc:
        print(f"bilinc: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
