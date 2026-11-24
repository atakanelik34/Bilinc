"""IMP-002b: the local MCP ``revise`` judges a stored memory the cache does not hold against its importance.

The local server restores beliefs only for rows with importance >= 0.5, and ``revise`` left an uncached key
alone, so after a restart a low-importance key was revised as a new key at any importance. A "restart" is a
second plane on the same SQLite file, set up like ``hermes_stdio``. Every write uses a different value: the
same value is a no-op success that never reaches the entrenchment check.
"""
from __future__ import annotations

import json

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.mcp_server.server_v2 import _handle_revise
from bilinc.storage.sqlite import SQLiteBackend


async def _plane(path):
    plane = StatePlane(backend=SQLiteBackend(path), enable_verification=False, enable_audit=True)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    plane.agm_engine.load_beliefs_from_entries(await plane.backend.list_all())   # as hermes_stdio does
    return plane


async def _revise(plane, key, value, importance, **extra):
    response = await _handle_revise(plane, {"key": key, "value": value, "importance": importance, **extra})
    return json.loads(response[0].text)


@pytest.fixture
def planes(tmp_path):
    made = []
    path = str(tmp_path / "local.sqlite")

    async def make():
        made.append(await _plane(path))
        return made[-1]

    return make            # each test closes the planes it made


async def _close(*planes):
    for plane in planes:
        await plane.backend.close()


# 1 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_lower_importance_is_refused_after_a_restart(planes):
    a = await planes()
    assert (await a.commit_with_agm_async("low.key", "kept", importance=0.3)).success is True
    b = await planes()                                        # restart
    try:
        result = await _revise(b, "low.key", "lower", 0.2)
        assert result["success"] is False
        assert (await b.backend.load("low.key")).value == "kept"
    finally:
        await _close(a, b)


# 2 ----------------------------------------------------------------------------------------------
PAIRS = [(0.3, 0.2), (0.3, 0.3), (0.3, 0.6), (0.7, 0.6), (0.7, 0.8)]


@pytest.mark.asyncio
async def test_the_outcome_is_the_same_before_and_after_a_restart(planes):
    a = await planes()
    for i, (stored, _new) in enumerate(PAIRS):
        await a.commit_with_agm_async(f"in-process-{i}", "old", importance=stored)
        await a.commit_with_agm_async(f"restarted-{i}", "old", importance=stored)
    in_process = [(await _revise(a, f"in-process-{i}", "new", new))["success"] for i, (_s, new) in enumerate(PAIRS)]
    b = await planes()                                        # starts after every commit
    try:
        after = [(await _revise(b, f"restarted-{i}", "new", new))["success"] for i, (_s, new) in enumerate(PAIRS)]
        assert after == in_process == [new >= stored for stored, new in PAIRS]
    finally:
        await _close(a, b)


# 3 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_requested_strategy_still_applies_after_a_restart(planes):
    a = await planes()
    await a.commit_with_agm_async("low.key", "kept", importance=0.3)
    b = await planes()
    try:
        assert (await _revise(b, "low.key", "newer", 0.2, strategy="recency"))["success"] is True
        assert (await b.backend.load("low.key")).value == "newer"
    finally:
        await _close(a, b)


# 4 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_key_with_no_stored_row_is_still_new(planes):
    a = await planes()
    try:
        assert (await _revise(a, "brand.new", "first", 0.1))["success"] is True
    finally:
        await _close(a)


# 5 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_and_graph_after_a_restart(planes):
    a = await planes()
    await a.commit_with_agm_async("low.key", "kept", importance=0.3)
    b = await planes()
    try:
        refused = await _revise(b, "low.key", "lower", 0.2)
        assert refused["success"] is False
        assert b.knowledge_graph.query_entity("low.key").properties["value"] == "kept"

        stored_before = (await b.backend.load("low.key")).to_dict()
        accepted = await _revise(b, "low.key", "higher", 0.4)
        assert accepted["success"] is True
        newest = b.audit.get_history(key="low.key", limit=1)[0]
        before = json.loads(newest.before_value) if isinstance(newest.before_value, str) else newest.before_value
        assert before == stored_before
        assert b.knowledge_graph.query_entity("low.key").properties["value"] == "higher"
    finally:
        await _close(a, b)


# 6 ----------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_an_entrenchment_raised_in_process_is_kept(planes):
    """Regression pin (green before the fix too): no read runs between the writes."""
    a = await planes()
    try:
        await a.commit_with_agm_async("k", "first", importance=0.9)
        assert (await _revise(a, "k", "second", 0.6, strategy="recency"))["success"] is True
        assert a.agm_engine.get_entrenchment("k") == 0.9
        assert (await _revise(a, "k", "third", 0.7))["success"] is False
    finally:
        await _close(a)
