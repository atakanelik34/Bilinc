"""CLI error-shape tests for deterministic failure envelopes."""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

import pytest

from bilinc.cli.main import _run_commit, _run_recall, _structured_error_payload


def test_structured_error_payload_maps_sqlite_lock_to_retryable_code():
    payload = _structured_error_payload(sqlite3.OperationalError("database is locked"), "commit_failed")
    assert payload["success"] is False
    assert payload["error"] == "database_locked"
    assert payload["retryable"] is True


def test_run_commit_returns_deterministic_json_on_lock_error(capsys):
    class LockedPlane:
        def commit_sync(self, **kwargs):
            raise sqlite3.OperationalError("database is locked")

    args = SimpleNamespace(key="k1", type="semantic", importance=1.0)
    with pytest.raises(SystemExit):
        _run_commit(LockedPlane(), backend=None, args=args, value="v1", backend_type="sqlite")

    err = capsys.readouterr().err
    payload = json.loads(err)
    assert payload["success"] is False
    assert payload["error"] == "database_locked"
    assert payload["key"] == "k1"


def test_run_recall_returns_deterministic_json_on_lock_error(capsys):
    class BrokenBackend:
        async def list_all(self):
            raise sqlite3.OperationalError("database is locked")

    class DummyPlane:
        pass

    args = SimpleNamespace(key=None, limit=5)
    with pytest.raises(SystemExit):
        _run_recall(DummyPlane(), backend=BrokenBackend(), args=args, backend_type="sqlite")

    err = capsys.readouterr().err
    payload = json.loads(err)
    assert payload["success"] is False
    assert payload["error"] == "database_locked"
