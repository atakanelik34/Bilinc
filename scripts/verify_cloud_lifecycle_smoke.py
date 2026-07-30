#!/usr/bin/env python3
"""Exercise the whole public Cloud lifecycle against a local mock control plane.

This is the release-evidence smoke: it proves that an *installed* wheel — with
``PYTHONPATH`` unset, so nothing can fall back to ``src/`` — can drive every
one of the eight lifecycle capabilities through the SDK, the CLI, and the MCP
adapter, over real HTTP, with no hosted Bilinc account involved.

Usage::

    env -u PYTHONPATH /path/to/venv/bin/python scripts/verify_cloud_lifecycle_smoke.py

Exits non-zero on the first failed expectation.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

API_KEY = "bil_live_smoke_key"

# Canned responses shaped exactly like the public routes' payloads.
RESPONSES: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {
    ("GET", "/api/cloud/health"): (200, {"status": "ok", "mode": "live_cloud"}),
    ("GET", "/api/cloud/status"): (
        200,
        {
            "status": "ok",
            "runtime": "ready",
            "plan": {"key": "pro", "entitlementStatus": "active"},
            "capabilities": {
                "commit": True,
                "recall": True,
                "revise": True,
                "forget": True,
                "snapshots": True,
                "diff": True,
                "rollback": True,
            },
            "tools": [
                "commit_mem",
                "recall",
                "revise",
                "forget",
                "status",
                "snapshot",
                "diff",
                "rollback",
            ],
            "recallProfiles": ["fast", "balanced", "verified"],
        },
    ),
    ("POST", "/api/cloud/memory/commit"): (
        201,
        {"success": True, "operation": "expansion", "entryVersion": "v1_abc", "affected_keys": ["k"]},
    ),
    ("POST", "/api/cloud/memory/recall"): (200, {"results": [{"key": "k"}], "profile": "balanced"}),
    ("POST", "/api/cloud/memory/revise"): (200, {"success": True, "entryVersion": "v1_def"}),
    ("POST", "/api/cloud/memory/forget"): (200, {"success": True, "removed": True, "reasonRecorded": True}),
    ("POST", "/api/cloud/memory/snapshots"): (201, {"snapshot": {"id": "snap_1", "totalEntries": 1}}),
    ("GET", "/api/cloud/memory/snapshots"): (200, {"snapshots": [{"id": "snap_1"}]}),
    ("POST", "/api/cloud/memory/diff"): (
        200,
        {"counts": {"added": 1, "modified": 0, "removed": 0}, "added": [{"key": "k"}]},
    ),
    ("POST", "/api/cloud/memory/rollback/preview"): (
        200,
        {
            "mode": "preview",
            "confirmationToken": "tok_smoke",
            "counts": {"create": 0, "update": 1, "remove": 0},
            "destructive": True,
        },
    ),
    ("POST", "/api/cloud/memory/rollback"): (
        200,
        {"success": True, "mode": "execute", "counts": {"created": 0, "updated": 1, "deleted": 0}},
    ),
}

seen: list[tuple[str, str]] = []
failures: list[str] = []


class MockControlPlane(BaseHTTPRequestHandler):
    def _respond(self) -> None:
        path = self.path.split("?")[0]
        key = (self.command, path)
        seen.append(key)

        if self.headers.get("Authorization") != f"Bearer {API_KEY}":
            return self._write(401, {"error": "missing_api_key", "message": "no key", "retryable": False})

        status, body = RESPONSES.get(key, (404, {"error": "invalid_request", "message": "unknown route"}))
        self._write(status, body)

    def _write(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = _respond
    do_POST = _respond

    def log_message(self, *_args: Any) -> None:  # keep the smoke output readable
        return


def check(label: str, condition: bool) -> None:
    print(f"  {'ok  ' if condition else 'FAIL'} {label}")
    if not condition:
        failures.append(label)


def run_sdk(base_url: str) -> None:
    from bilinc import CloudClient

    client = CloudClient(api_key=API_KEY, base_url=base_url)

    print("SDK")
    check("health", client.health()["status"] == "ok")
    check("status reports eight tools", len(client.status()["tools"]) == 8)
    check("commit", client.commit("k", {"n": 1}, idempotency_key="smoke-1")["success"] is True)
    check("recall", client.recall("k", profile="balanced", limit=25)["results"] != [])
    check("revise", client.revise("k", {"n": 2}, reason="smoke")["success"] is True)
    check("forget", client.forget("k", reason="smoke cleanup")["removed"] is True)
    check("snapshot create", client.snapshot(action="create", label="smoke")["snapshot"]["id"] == "snap_1")
    check("snapshot list", client.snapshot(action="list")["snapshots"] != [])
    check("diff", client.diff("snap_1")["counts"]["added"] == 1)

    preview = client.rollback_preview("snap_1", reason="smoke")
    check("rollback preview mints a token", preview["confirmationToken"] == "tok_smoke")
    executed = client.rollback(
        "snap_1", confirmation_token=preview["confirmationToken"], reason="smoke"
    )
    check("rollback execute", executed["success"] is True)


def run_sdk_validation() -> None:
    from bilinc import CloudClient
    from bilinc.client import BilincValidationError

    client = CloudClient(api_key=API_KEY, base_url="http://127.0.0.1:1")

    print("SDK client-side validation (no network)")
    for label, call in [
        ("forget requires a reason", lambda: client.forget("k", reason="  ")),
        ("rollback requires a token", lambda: client.rollback("s", confirmation_token="", reason="r")),
        ("recall limit is bounded", lambda: client.recall("q", limit=101)),
        ("unknown memory type is rejected", lambda: client.commit("k", 1, memory_type="dreams")),
        ("unknown profile is rejected", lambda: client.recall("q", profile="psychic")),
    ]:
        try:
            call()
            check(label, False)
        except BilincValidationError:
            check(label, True)


def run_cli(base_url: str) -> None:
    print("CLI")
    common = [sys.executable, "-m", "bilinc.cli.main", "--api-key", API_KEY, "--base-url", base_url]
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}

    for label, argv in [
        ("status", ["status"]),
        ("health", ["health"]),
        ("commit", ["commit", "--key", "k", "--value", '{"n":1}']),
        ("recall", ["recall", "--query", "k"]),
        ("revise", ["revise", "--key", "k", "--value", '{"n":2}', "--reason", "smoke"]),
        ("forget", ["forget", "--key", "k", "--reason", "smoke cleanup"]),
        ("snapshot create", ["snapshot", "create", "--label", "smoke"]),
        ("snapshot list", ["snapshot", "list"]),
        ("diff", ["diff", "--from-snapshot", "snap_1"]),
        ("rollback preview", ["rollback", "preview", "--snapshot", "snap_1", "--reason", "smoke"]),
    ]:
        result = subprocess.run(common + argv, capture_output=True, text=True, env=env)
        check(label, result.returncode == 0 and "Traceback" not in result.stderr)


def run_mcp() -> None:
    from bilinc.cloud_mcp import CLOUD_MCP_TOOLS, build_server

    print("MCP adapter")
    tools = {tool.name: tool for tool in asyncio.run(build_server().list_tools())}
    check("exactly eight tools", sorted(tools) == sorted(CLOUD_MCP_TOOLS))
    check("forget declares its risk", "destructive" in (tools["forget"].description or "").lower())
    check("rollback declares its risk", "destructive" in (tools["rollback"].description or "").lower())
    check("forget requires key and reason", set(tools["forget"].inputSchema["required"]) == {"key", "reason"})
    check("rollback exposes a mode", "mode" in tools["rollback"].inputSchema["properties"])


def main() -> int:
    if os.environ.get("PYTHONPATH"):
        print("refusing to run with PYTHONPATH set: this smoke must exercise the installed wheel")
        return 2

    server = HTTPServer(("127.0.0.1", 0), MockControlPlane)
    base_url = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        run_sdk(base_url)
        run_sdk_validation()
        run_cli(base_url)
        run_mcp()
    finally:
        server.shutdown()

    print()
    print(f"routes exercised: {len({path for _, path in seen})}")
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("all Cloud lifecycle smokes passed against the installed package")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
