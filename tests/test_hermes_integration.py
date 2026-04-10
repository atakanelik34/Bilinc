"""Hermes-focused integration tests for Bilinc MCP server v2."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from bilinc.core.stateplane import StatePlane
from bilinc.mcp_server.server_v2 import (
    _enforce_auth_policy,
    _handle_commit_mem,
    _handle_diff,
    _handle_recall,
    _handle_rollback,
    _handle_snapshot,
)
from bilinc.storage.sqlite import SQLiteBackend


def _payload(result):
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return json.loads(result[0].text)


def _build_plane(tmp_path: Path) -> StatePlane:
    db_path = tmp_path / "bilinc_test.db"
    plane = StatePlane(
        backend=SQLiteBackend(str(db_path)),
        enable_verification=True,
        enable_audit=True,
    )
    asyncio.run(plane.init())
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


def test_http_auth_policy_enforced():
    missing = _enforce_auth_policy("abc", None, "http")
    invalid = _enforce_auth_policy("abc", "wrong", "http")
    valid = _enforce_auth_policy("abc", "abc", "http")
    stdio = _enforce_auth_policy("abc", None, "stdio")

    assert missing and missing["error"] == "unauthorized"
    assert invalid and invalid["error"] == "unauthorized"
    assert valid is None
    assert stdio is None


def test_commit_recall_metadata_contract_and_priority(tmp_path: Path):
    plane = _build_plane(tmp_path)

    _payload(
        _handle_commit_mem(
            plane,
            {
                "key": "hermes_session::001",
                "value": "session summary",
                "memory_type": "episodic",
                "source": "hermes_session_summary",
                "canonical": False,
                "priority": "low",
                "ttl": 120,
            },
        )
    )
    canonical = _payload(
        _handle_commit_mem(
            plane,
            {
                "key": "company_truth",
                "value": json.dumps({"name": "Bilinc"}),
                "memory_type": "semantic",
                "source": "hermes",
                "canonical": True,
                "priority": "high",
            },
        )
    )
    assert canonical["success"] is True

    recall = _payload(_handle_recall(plane, {"limit": 10}))
    assert recall["count"] >= 2
    assert recall["entries"][0]["key"] == "company_truth"
    assert all(isinstance(e.get("metadata"), dict) for e in recall["entries"])

    # Verify canonical entry was stored with metadata
    recall_all = _payload(_handle_recall(plane, {"limit": 10}))
    company_entries = [e for e in recall_all["entries"] if e["key"] == "company_truth"]
    assert len(company_entries) >= 1
    assert company_entries[0].get("metadata", {}).get("canonical", False) is True


def test_snapshot_diff_rollback_roundtrip(tmp_path: Path):
    plane = _build_plane(tmp_path)

    _payload(_handle_commit_mem(plane, {"key": "k1", "value": "v1", "memory_type": "semantic"}))
    snap_a = _payload(_handle_snapshot(plane, {}))
    time.sleep(0.01)
    _payload(_handle_commit_mem(plane, {"key": "k2", "value": "v2", "memory_type": "semantic"}))
    snap_b = _payload(_handle_snapshot(plane, {}))

    diff = _payload(_handle_diff(plane, {"ts_a": snap_a["timestamp"], "ts_b": snap_b["timestamp"]}))
    assert diff["success"] is True
    added_keys = [e["key"] if isinstance(e, dict) else e for e in diff.get("added", [])]
    modified_keys = [e["key"] if isinstance(e, dict) else e for e in diff.get("modified", [])]
    changed_keys = set(added_keys) | set(modified_keys)
    assert "k2" in changed_keys

    rollback = _payload(_handle_rollback(plane, {"ts": snap_a["timestamp"]}))
    assert rollback["success"] is True
    assert rollback["restored_count"] >= 1


def test_rollback_invalid_audit_payload_returns_structured_error(tmp_path: Path, monkeypatch):
    plane = _build_plane(tmp_path)
    _payload(_handle_commit_mem(plane, {"key": "k1", "value": "v1", "memory_type": "semantic"}))

    def _broken_state(_: float):
        return {"k1": "legacy-string-payload"}

    monkeypatch.setattr(plane.audit, "get_state_at", _broken_state)

    rollback = _payload(_handle_rollback(plane, {"ts": time.time()}))
    assert rollback["success"] is False
    assert rollback["error"] == "rollback_failed"
    assert "invalid audit payload" in rollback["message"]
