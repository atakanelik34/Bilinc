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


def test_lexical_recall_bridges_common_inflections_without_synonyms():
    plane = StatePlane()
    candidates = {
        "distractor": MemoryEntry(
            key="distractor",
            value="The team planned a conference in the city.",
            memory_type=MemoryType.SEMANTIC,
        ),
        "target": MemoryEntry(
            key="target",
            value="The team went camping in the mountains.",
            memory_type=MemoryType.SEMANTIC,
        ),
    }

    ranked = plane._rank_lexical_keys("Where did the team's camped trip happen?", candidates)

    assert ranked[0] == "target"
    assert plane._normalize_lexical_token("camped") == "camp"
    assert plane._normalize_lexical_token("camping") == "camp"


def test_lexical_exact_form_remains_authoritative_over_inflectional_variants():
    plane = StatePlane()
    candidates = {
        "exact": MemoryEntry(
            key="exact",
            value="The country visit was documented.",
            memory_type=MemoryType.SEMANTIC,
        ),
        "variant": MemoryEntry(
            key="variant",
            value="They visited another country.",
            memory_type=MemoryType.SEMANTIC,
        ),
    }

    ranked = plane._rank_lexical_keys("Which country did they visit?", candidates)

    assert ranked[0] == "exact"


def test_surface_fallback_is_bounded_and_available_for_sparse_stores():
    plane = StatePlane()
    candidates = {
        "payment": MemoryEntry(
            key="payment",
            value="Payment processing uses Stripe with webhooks.",
            memory_type=MemoryType.SEMANTIC,
        )
    }

    assert plane._rank_lexical_keys("how do we handle money", candidates) == []
    assert plane._rank_surface_fallback_keys("how do we handle money", candidates) == ["payment"]
    assert plane.SURFACE_FALLBACK_MAX_CANDIDATES == 128


@pytest.mark.asyncio
async def test_sparse_completion_fills_broad_queries_without_displacing_primary_hits(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "sparse-completion.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    entries = [
        ("language", "The primary language is Rust."),
        ("database", "The database is PostgreSQL."),
        ("deployment", "The deployment target is a managed container."),
        ("testing", "Tests use a fast unit test runner."),
        ("style", "Code style uses two-space indentation."),
    ]
    for key, value in entries:
        await backend.restore(MemoryEntry(key=key, value=value, memory_type=MemoryType.SEMANTIC))

    broad = await plane.recall_intelligent("what are the project settings", limit=5)
    assert {result["key"] for result in broad} == {key for key, _ in entries}

    narrow = await plane.recall_intelligent("which database do we use", limit=2)
    assert narrow[0]["key"] == "database"
    assert plane.SPARSE_COMPLETION_MAX_CANDIDATES == 32


@pytest.mark.asyncio
async def test_default_recall_projects_generic_migration_to_current_state(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "current-projection.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    raw = "Migrated database from local SQLite to hosted Postgres for edge deployment."
    await backend.restore(
        MemoryEntry(key="architecture", value=raw, memory_type=MemoryType.SEMANTIC)
    )

    current = await plane.recall_intelligent("what is the current database", limit=3)
    assert current[0]["key"] == "architecture"
    assert "SQLite" not in current[0]["value"]
    assert "Postgres" in current[0]["value"]

    historical = await plane.recall_intelligent(
        "what is the database history",
        limit=3,
        include_stale=True,
    )
    assert historical[0]["value"] == raw


@pytest.mark.asyncio
async def test_current_intent_keeps_latest_entry_for_one_state_topic(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "current-topic.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    now = time.time()
    entries = [
        ("old", "The workspace used an Ember cluster.", now - 30),
        ("middle", "The workspace moved to a Nimbus cluster.", now - 20),
        ("latest", "The workspace upgraded to the Nimbus runtime.", now - 10),
    ]
    for key, value, stamp in entries:
        await backend.restore(
            MemoryEntry(
                key=key,
                value=value,
                memory_type=MemoryType.SEMANTIC,
                created_at=stamp,
                updated_at=stamp,
            )
        )

    results = await plane.recall_intelligent("what cluster do we currently use", limit=5)
    profiled = await plane.recall_profiled("what cluster do we currently use", limit=5)

    assert plane._is_current_state_query("what cluster do we currently use") is True
    assert plane._is_singular_current_state_query("what cluster do we currently use") is True
    assert [result["key"] for result in results] == ["latest"]
    assert [result["key"] for result in profiled["results"]] == ["latest"]
    assert "Nimbus runtime" in results[0]["value"]


@pytest.mark.asyncio
async def test_current_intent_preserves_multi_topic_evidence(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "current-multi-topic.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    now = time.time()
    entries = [
        ("older", "Mira joined the Harbor book club.", now - 20),
        ("latest", "Mira is currently reading a history book.", now - 10),
    ]
    for key, value, stamp in entries:
        await backend.restore(
            MemoryEntry(
                key=key,
                value=value,
                memory_type=MemoryType.SEMANTIC,
                created_at=stamp,
                updated_at=stamp,
            )
        )

    results = await plane.recall_intelligent("what book is Mira currently reading", limit=5)

    assert {result["key"] for result in results} == {"older", "latest"}


def test_adaptive_semantic_weight_is_opt_in_and_gated_by_lexical_coverage(monkeypatch):
    plane = StatePlane()
    candidates = {
        "database": MemoryEntry(
            key="database",
            value="database stores durable state",
            memory_type=MemoryType.SEMANTIC,
        ),
        "unrelated": MemoryEntry(
            key="unrelated",
            value="the service uses a remote queue",
            memory_type=MemoryType.SEMANTIC,
        ),
    }
    query = "Which database stores state?"
    lexical_ranked = plane._rank_lexical_keys(query, candidates)

    monkeypatch.delenv("BILINC_SEMANTIC_ADAPTIVE_WEIGHT", raising=False)
    assert plane._semantic_recall_weight(query, candidates, lexical_ranked) == 0.05

    monkeypatch.setenv("BILINC_SEMANTIC_ADAPTIVE_WEIGHT", "1")
    assert plane._semantic_recall_weight(query, candidates, lexical_ranked) == 0.0
    assert plane._semantic_recall_weight("Which platform is preferred?", candidates, []) == 0.12


def test_semantic_rrf_weight_is_configurable_and_bounded(monkeypatch):
    plane = StatePlane()

    monkeypatch.delenv("BILINC_SEMANTIC_RRF_WEIGHT", raising=False)
    assert plane._semantic_recall_rrf_weight() == 0.05

    monkeypatch.setenv("BILINC_SEMANTIC_RRF_WEIGHT", "0.12")
    assert plane._semantic_recall_rrf_weight() == 0.12

    monkeypatch.setenv("BILINC_SEMANTIC_RRF_WEIGHT", "not-a-number")
    assert plane._semantic_recall_rrf_weight() == 0.05

    monkeypatch.setenv("BILINC_SEMANTIC_RRF_WEIGHT", "4")
    assert plane._semantic_recall_rrf_weight() == 1.0

    monkeypatch.setenv("BILINC_SEMANTIC_RRF_WEIGHT", "-1")
    assert plane._semantic_recall_rrf_weight() == 0.0


def test_lexical_retrieval_surface_allows_event_time_but_not_arbitrary_metadata():
    plane = StatePlane()
    entry = MemoryEntry(
        key="memory:event",
        value="the project update was recorded",
        metadata={
            "source_date_time": "8 May, 2023",
            "secret": "do-not-index-this",
            "private": "customer context",
        },
    )

    surface = plane._retrieval_surface_text(entry)

    assert "8 May, 2023" in surface
    assert "do-not-index-this" not in surface
    assert "customer context" not in surface


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

    plane._apply_current_state_boost("what is the current deployment", scores, {"older": older, "newer": newer})

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
        "what is the current deployment",
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
