"""Neutral tests for corpus-aware lexical ranking and current-state recall."""

import time

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend


def test_lexical_specificity_breaks_common_word_ties():
    plane = StatePlane()
    candidates = {
        "common-one": MemoryEntry(
            key="common-one",
            value="What is the answer?",
            memory_type=MemoryType.SEMANTIC,
        ),
        "common-two": MemoryEntry(
            key="common-two",
            value="What is another answer?",
            memory_type=MemoryType.SEMANTIC,
        ),
        "specific": MemoryEntry(
            key="specific",
            value="Database details are stored here.",
            memory_type=MemoryType.SEMANTIC,
        ),
    }

    ranked = plane._rank_lexical_keys("What database?", candidates)

    assert ranked[0] == "specific"


def test_current_state_boost_is_opt_in_and_timestamp_based():
    plane = StatePlane()
    older = MemoryEntry(
        key="older",
        value="The deployment target was Heroku.",
        memory_type=MemoryType.SEMANTIC,
        created_at=10.0,
        updated_at=10.0,
    )
    newer = MemoryEntry(
        key="newer",
        value="The deployment target is Fly.io.",
        memory_type=MemoryType.SEMANTIC,
        created_at=20.0,
        updated_at=20.0,
    )
    scores = {"older": 1.0, "newer": 1.0}

    plane._apply_current_state_boost("what is the current deployment target", scores, {"older": older, "newer": newer})

    assert scores["newer"] > scores["older"]


def test_current_state_boost_does_not_change_general_queries():
    plane = StatePlane()
    candidates = {
        "older": MemoryEntry(key="older", created_at=10.0, updated_at=10.0),
        "newer": MemoryEntry(key="newer", created_at=20.0, updated_at=20.0),
    }
    scores = {"older": 1.0, "newer": 1.0}

    plane._apply_current_state_boost("what is the deployment target", scores, candidates)

    assert scores == {"older": 1.0, "newer": 1.0}


def test_current_state_boost_demotes_explicitly_non_current_entries():
    plane = StatePlane()
    stale = MemoryEntry(
        key="stale",
        created_at=20.0,
        updated_at=20.0,
        invalid_at=10.0,
    )
    superseded = MemoryEntry(
        key="superseded",
        created_at=20.0,
        updated_at=20.0,
        superseded_by="replacement",
    )
    active = MemoryEntry(key="active", created_at=20.0, updated_at=20.0)

    scores = {"stale": 1.0, "superseded": 1.0, "active": 1.0}
    plane._apply_current_state_boost(
        "what is the current deployment target",
        scores,
        {"stale": stale, "superseded": superseded, "active": active},
    )

    assert scores["stale"] < scores["active"]
    assert scores["superseded"] < scores["active"]


@pytest.mark.asyncio
async def test_intelligent_recall_defaults_to_current_valid_entries(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "current-state.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    now = time.time()

    await backend.restore(
        MemoryEntry(
            key="memory:expired",
            value="deployment target is legacy-host",
            memory_type=MemoryType.SEMANTIC,
            invalid_at=now - 1,
        )
    )
    await backend.restore(
        MemoryEntry(
            key="memory:superseded",
            value="deployment target is old-host",
            memory_type=MemoryType.SEMANTIC,
            superseded_by="memory:current",
        )
    )
    await backend.restore(
        MemoryEntry(
            key="memory:future",
            value="deployment target is future-host",
            memory_type=MemoryType.SEMANTIC,
            valid_at=now + 3600,
        )
    )
    await backend.restore(
        MemoryEntry(
            key="memory:current",
            value="deployment target is current-host",
            memory_type=MemoryType.SEMANTIC,
        )
    )

    results = await plane.recall_intelligent("deployment target", limit=10)
    assert [result["key"] for result in results] == ["memory:current"]

    historical = await plane.recall_intelligent("deployment target", limit=10, include_stale=True)
    assert {result["key"] for result in historical} == {
        "memory:expired",
        "memory:superseded",
        "memory:future",
        "memory:current",
    }


@pytest.mark.asyncio
async def test_intelligent_recall_keeps_memory_type_scope_across_hybrid_paths(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "memory-type-scope.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    await backend.restore(
        MemoryEntry(
            key="memory:semantic",
            value="database uses postgres",
            memory_type=MemoryType.SEMANTIC,
        )
    )
    await backend.restore(
        MemoryEntry(
            key="memory:episodic",
            value="database uses sqlite",
            memory_type=MemoryType.EPISODIC,
        )
    )

    results = await plane.recall_intelligent(
        "database uses",
        limit=10,
        memory_types=[MemoryType.SEMANTIC],
    )
    assert results
    assert all(result["memory_type"] == MemoryType.SEMANTIC.value for result in results)
