"""The SQLite audit trail's connection is bound to the thread that created it.

Known limit, not a contract. ``AuditTrail`` opens its connection with the default ``check_same_thread=True``
(core/audit.py:136), although it has a lock. The hosted runtime calls it only from its event loop thread, so
nothing breaks today; it is what made ``tests/test_cloud_service.py`` flaky while its client moved every request to a
new thread. If the connection is ever opened with ``check_same_thread=False`` (and its read paths locked), this test is
expected to fail and should be updated on purpose.
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from bilinc.core.audit import AuditTrail, OpType


@pytest.mark.asyncio
async def test_the_audit_connection_cannot_be_used_from_another_thread(tmp_path):
    trail = AuditTrail(str(tmp_path / "audit.db"))
    await trail.init()
    errors: list[BaseException] = []
    done = threading.Event()

    def other_thread():
        try:
            trail.log(OpType.CREATE, "k", None, {"n": 1})
        except BaseException as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)
        finally:
            done.set()

    worker = threading.Thread(target=other_thread)
    worker.start()                       # the creating (test) thread stays alive, so the worker cannot get its identifier
    assert done.wait(10)
    worker.join()
    try:
        assert len(errors) == 1 and isinstance(errors[0], sqlite3.ProgrammingError)
        assert "same thread" in str(errors[0])
    finally:
        await trail.close()


@pytest.mark.asyncio
async def test_the_same_thread_can_log(tmp_path):
    trail = AuditTrail(str(tmp_path / "audit.db"))
    await trail.init()
    try:
        assert trail.log(OpType.CREATE, "k", None, {"n": 1}).root_hash
    finally:
        await trail.close()
