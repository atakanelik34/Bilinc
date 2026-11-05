"""Time-window recall (StatePlane.recall_time_window) on SQLite and PostgreSQL.

The PostgreSQL cases run only when BILINC_TEST_POSTGRES_DSN points at a
disposable PostgreSQL; each uses its own tenant schema and drops it afterwards.
All sources and values are synthetic.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.core.time_intent import parse_time_intent
from bilinc.storage.postgres import PostgresBackend
from bilinc.storage.sqlite import SQLiteBackend

IST = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
DSN = os.getenv("BILINC_TEST_POSTGRES_DSN")
BACKENDS = [
    "sqlite",
    pytest.param("postgres", marks=pytest.mark.skipif(not DSN, reason="BILINC_TEST_POSTGRES_DSN not set")),
]
ENVELOPE_TYPES_KEYS = ("query", "final_query", "adequacy", "adequacy_threshold", "reflections_used",
                       "max_reflections", "queries_tried", "results")


def at(days_ago=0, hours=0, seconds=0):
    return NOW - timedelta(days=days_ago, hours=hours, seconds=seconds)


def intent_for(query, now=NOW):
    intent = parse_time_intent(query, now=now, tz=IST)
    assert intent is not None, query
    return intent


def entry(key, value, source="agent", when=None, memory_type=MemoryType.SEMANTIC, **extra):
    stamp = (when or at(0, hours=1)).timestamp()
    extra.setdefault("created_at", stamp)
    return MemoryEntry(key=key, value=value, source=source, memory_type=memory_type, updated_at=stamp, **extra)


def run_with_plane(backend_kind, tmp_path, scenario):
    """Run ``scenario(plane)`` against a fresh backend of the given kind."""
    async def runner():
        if backend_kind == "sqlite":
            backend = SQLiteBackend(str(tmp_path / "p.db"))
            await backend.init()
            try:
                return await scenario(StatePlane(backend=backend, enable_verification=False, enable_audit=False))
            finally:
                await backend.close()
        import asyncpg

        backend = PostgresBackend(dsn=DSN, schema=f"bilinc_tw_{uuid.uuid4().hex}")
        await backend.init()
        try:
            return await scenario(StatePlane(backend=backend, enable_verification=False, enable_audit=False))
        finally:
            await backend.close()
            conn = await asyncpg.connect(DSN)
            try:
                await conn.execute(f'DROP SCHEMA IF EXISTS "{backend.schema}" CASCADE')
            finally:
                await conn.close()

    return asyncio.new_event_loop().run_until_complete(runner())


async def fill(plane, entries):
    for item in entries:
        await plane.backend.restore(item)


@pytest.fixture(params=BACKENDS)
def kind(request):
    return request.param


def test_today_returns_only_todays_entries_newest_first(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [
            entry("old", "pricing decision", when=at(3)),
            entry("t1", "profile cleaned", when=at(0, hours=5)),
            entry("t2", "references fixed", when=at(0, hours=1)),
        ])
        payload = await plane.recall_time_window(intent_for("bugünün güncellemeleri"), limit=10, query="bugünün güncellemeleri")
        assert [r["key"] for r in payload["results"]] == ["t2", "t1"]
        assert payload["routed"] == "time_window"
        assert payload["time_window"]["count"] == 2
        assert payload["time_window"]["truncated"] is False
        assert payload["time_window"]["widened"] is False
        assert payload["time_window"]["topic_hits"] == 0
        assert payload["time_window"]["label"]
        start = datetime.fromisoformat(payload["time_window"]["start"])
        end = datetime.fromisoformat(payload["time_window"]["end"])
        assert start.astimezone(IST).hour == 0 and (end - start) <= timedelta(hours=25)
    run_with_plane(kind, tmp_path, scenario)


def test_low_signal_sources_are_excluded_unless_asked(kind, tmp_path):
    async def scenario(plane):
        rows = [entry(f"chat{i}", "we talked", "sample-chat-transcript", at(0, hours=1, seconds=i)) for i in range(150)]
        rows += [entry(f"dec{i}", f"decision {i}", "agent", at(0, hours=2, seconds=i)) for i in range(20)]
        await fill(plane, rows)
        intent = intent_for("what changed today")
        payload = await plane.recall_time_window(
            intent, limit=10, low_signal_sources=["sample-chat-transcript"], query="what changed today")
        assert payload["results"] and all(r["key"].startswith("dec") for r in payload["results"])
        asked = await plane.recall_time_window(
            intent, limit=10, low_signal_sources=["sample-chat-transcript"], include_low_signal=True,
            query="today's chats")
        assert any(r["key"].startswith("chat") for r in asked["results"])
    run_with_plane(kind, tmp_path, scenario)


def test_explicit_topic_ranks_first_with_padding_and_topic_hits(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [
            entry("a", "alpha references fixed", when=at(0, hours=1)),
            entry("b", "zebra flag removed", when=at(1)),
            entry("c", "unrelated note", when=at(0, hours=2)),
        ])
        query = "son 3 günde zebra"
        payload = await plane.recall_time_window(intent_for(query), limit=10, query=query)
        assert payload["results"][0]["key"] == "b"
        assert [r["key"] for r in payload["results"]] == ["b", "a", "c"]
        assert payload["time_window"]["topic_hits"] == 1
        signals = [r["signals"] for r in payload["results"]]
        assert signals[0]["lexical"] > 0.0 and signals[1]["lexical"] == 0.0 and signals[2]["lexical"] == 0.0
        none = await plane.recall_time_window(intent_for("today quokka"), limit=10, query="today quokka")
        assert none["time_window"]["topic_hits"] == 0
        assert [r["key"] for r in none["results"]] == ["a", "c"]
    run_with_plane(kind, tmp_path, scenario)


def test_implicit_widens_then_gives_up(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [entry("w", "weekly note", when=at(3)), entry("x", "ancient", when=at(30))])
        query = "what's new"
        widened = await plane.recall_time_window(intent_for(query), limit=10, query=query)
        assert [r["key"] for r in widened["results"]] == ["w"]
        assert widened["time_window"]["widened"] is True
    run_with_plane(kind, tmp_path, scenario)


def test_implicit_gives_up_when_nothing_in_seven_days(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [entry("x", "ancient", when=at(30))])
        assert await plane.recall_time_window(intent_for("what's new"), limit=10, query="what's new") is None
    run_with_plane(kind, tmp_path, scenario)


def test_implicit_topic_uses_only_lexical_hits_and_falls_back(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [
            entry("recent-other", "billing exports tuned", when=at(0, hours=2)),
            entry("old-topic", "purge logic rewritten", when=at(20)),
            entry("recent-topic", "auth tokens rotated", when=at(0, hours=3)),
        ])
        query = "what changed in the purge logic"
        # Topic only outside 7 days: not routed (an older relevant entry is never pushed out by recent rows).
        assert await plane.recall_time_window(intent_for(query), limit=10, query=query) is None
        # Topic inside 24 h: only topic hits, no padding.
        query = "what changed in auth"
        payload = await plane.recall_time_window(intent_for(query), limit=10, query=query)
        assert [r["key"] for r in payload["results"]] == ["recent-topic"]
        assert payload["time_window"]["topic_hits"] == 1
        assert payload["time_window"]["widened"] is False
    run_with_plane(kind, tmp_path, scenario)


def test_implicit_topic_widens_to_seven_days(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [
            entry("recent-other", "billing exports tuned", when=at(0, hours=2)),
            entry("week-topic", "auth tokens rotated", when=at(4)),
        ])
        query = "what changed in auth"
        payload = await plane.recall_time_window(intent_for(query), limit=10, query=query)
        assert [r["key"] for r in payload["results"]] == ["week-topic"]
        assert payload["time_window"]["widened"] is True
    run_with_plane(kind, tmp_path, scenario)


def test_explicit_empty_window_returns_empty_results(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [entry("old", "x", when=at(5))])
        payload = await plane.recall_time_window(intent_for("today"), limit=10, query="today")
        assert payload["results"] == []
        assert payload["routed"] == "time_window"
        assert payload["time_window"]["count"] == 0
    run_with_plane(kind, tmp_path, scenario)


def test_truncates_at_500(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [entry(f"k{i:04d}", "v", when=at(0, hours=1, seconds=i)) for i in range(520)])
        payload = await plane.recall_time_window(intent_for("today"), limit=10, query="today")
        assert payload["time_window"]["truncated"] is True
        assert payload["time_window"]["count"] == 500
        assert payload["results"][0]["key"] == "k0000"
    run_with_plane(kind, tmp_path, scenario)


def test_scan_cap_stops_a_filter_heavy_window(kind, tmp_path):
    async def scenario(plane):
        plane.TIME_WINDOW_PAGE = 10
        plane.TIME_WINDOW_SCAN_MAX = 30
        rows = [entry(f"gone{i:02d}", "stale", when=at(0, hours=1, seconds=i), superseded_by="newer") for i in range(40)]
        rows.append(entry("visible", "still here", when=at(0, hours=5)))
        await fill(plane, rows)
        payload = await plane.recall_time_window(intent_for("today"), limit=10, query="today")
        assert payload["results"] == []
        assert payload["time_window"]["truncated"] is True
    run_with_plane(kind, tmp_path, scenario)


def test_memory_type_filter_single_and_multiple(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [
            entry("s", "sem", when=at(0, hours=1)),
            entry("e", "epi", when=at(0, hours=2), memory_type=MemoryType.EPISODIC),
            entry("p", "proc", when=at(0, hours=3), memory_type=MemoryType.PROCEDURAL),
        ])
        intent = intent_for("today")
        one = await plane.recall_time_window(intent, limit=10, memory_types=[MemoryType.EPISODIC], query="today")
        assert [r["key"] for r in one["results"]] == ["e"]
        two = await plane.recall_time_window(
            intent, limit=10, memory_types=[MemoryType.EPISODIC, MemoryType.SEMANTIC], query="today")
        assert [r["key"] for r in two["results"]] == ["s", "e"]
        assert two["time_window"]["count"] == 2
    run_with_plane(kind, tmp_path, scenario)


def test_invisible_entries_are_absent(kind, tmp_path):
    async def scenario(plane):
        stamp = at(0, hours=2)
        await fill(plane, [
            entry("ok", "visible", when=at(0, hours=1)),
            entry("ttl", "expired", when=stamp, ttl=60.0),
            entry("inv", "invalidated", when=stamp, invalid_at=at(0, hours=1).timestamp()),
            entry("sup", "superseded", when=stamp, superseded_by="ok"),
            entry("fut", "future", when=stamp, valid_at=(NOW + timedelta(days=3650)).timestamp()),
        ])
        payload = await plane.recall_time_window(intent_for("today"), limit=10, query="today")
        assert [r["key"] for r in payload["results"]] == ["ok"]
        assert payload["time_window"]["count"] == 1
    run_with_plane(kind, tmp_path, scenario)


def test_result_shape_matches_normal_recall(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [
            entry("t", "today item", when=at(0, hours=1), metadata={"source_key": "origin-1"}),
            entry("u", "other item", when=at(0, hours=2)),
        ])
        normal = await plane.recall_profiled(query="today item", limit=5)
        routed = await plane.recall_time_window(intent_for("today"), limit=5, query="today")
        first = routed["results"][0]
        assert set(normal["results"][0]) - {"source_key"} == set(first) - {"source_key"}
        assert first["source_key"] == "origin-1"
        assert "source_key" not in routed["results"][1]
        assert set(first["signals"]) == {"lexical", "hybrid", "semantic", "sparse", "temporal", "entity"}
        assert [r["score"] for r in routed["results"]] == [1.0, 0.5]
        for item in routed["results"]:
            assert item["signals"]["temporal"] == item["score"]
            assert all(item["signals"][name] == 0.0 for name in ("lexical", "hybrid", "semantic", "sparse", "entity"))
        assert not {"rerank_score", "reordered_by", "source"} & set(first)
    run_with_plane(kind, tmp_path, scenario)


def _same_value_types(routed, normal, keys):
    for key in keys:
        assert isinstance(routed[key], type(normal[key])), key


def test_envelope_is_superset_of_recall_profiled(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [entry("t", "today item", when=at(0, hours=1))])
        normal = await plane.recall_profiled(query="today item", limit=5)
        routed = await plane.recall_time_window(intent_for("today"), limit=5, query="today", profile="balanced")
        assert set(normal) <= set(routed)
        _same_value_types(routed, normal, normal.keys())
        assert routed["routed"] == "time_window"
        assert routed["profile"] == "balanced" and routed["read_only"] is True
        assert routed["recall_profile"] == plane.resolve_recall_profile("balanced")
        assert routed["query"] == routed["final_query"] == "today"
        assert routed["queries_tried"] == ["today"] and routed["reflections_used"] == 0
        assert isinstance(routed["adequacy"], float)
        assert "evidence" not in routed
        override = await plane.recall_time_window(
            intent_for("today"), limit=5, query="today", profile="fast", max_reflections=3, adequacy_threshold=2.0)
        assert override["max_reflections"] == 3 and override["adequacy_threshold"] == 1.0
    run_with_plane(kind, tmp_path, scenario)


def test_envelope_is_superset_of_recall_reflective_without_profile(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [entry("t", "today item", when=at(0, hours=1))])
        normal = await plane.recall_reflective("today item", limit=5)
        routed = await plane.recall_time_window(intent_for("today"), limit=5, query="today")
        assert set(normal) <= set(routed)
        _same_value_types(routed, normal, normal.keys())
        assert not {"profile", "recall_profile", "read_only", "evidence"} & set(routed)
        custom = await plane.recall_time_window(
            intent_for("today"), limit=5, query="today", max_reflections=1, adequacy_threshold=0.9)
        assert custom["max_reflections"] == 1 and custom["adequacy_threshold"] == 0.9
    run_with_plane(kind, tmp_path, scenario)


def test_verified_profile_attaches_evidence(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [entry("t", "today item", when=at(0, hours=1))])
        normal = await plane.recall_profiled(query="today item", limit=5, profile="verified")
        routed = await plane.recall_time_window(intent_for("today"), limit=5, query="today", profile="verified")
        assert "evidence" in normal and "evidence" in routed
        assert set(routed["evidence"]) == set(normal["evidence"])
        assert routed["recall_profile"]["name"] == "verified"
    run_with_plane(kind, tmp_path, scenario)


def test_projection_matches_normal_recall(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [entry("move", "We migrated storage from Alpha to Beta.", when=at(0, hours=1))])
        normal = await plane.recall_profiled(query="storage", limit=5)
        routed = await plane.recall_time_window(intent_for("today"), limit=5, query="today")
        assert normal["results"][0]["value"] == "Current storage: Beta."
        assert routed["results"][0]["value"] == normal["results"][0]["value"]
    run_with_plane(kind, tmp_path, scenario)


def test_midnight_boundary_belongs_to_today(kind, tmp_path):
    async def scenario(plane):
        midnight = datetime(2026, 11, 5, 0, 0, tzinfo=IST)
        await fill(plane, [
            entry("at-midnight", "exactly midnight", when=midnight),
            entry("before", "just before", when=midnight - timedelta(seconds=1)),
        ])
        today = await plane.recall_time_window(intent_for("today"), limit=10, query="today")
        yesterday = await plane.recall_time_window(intent_for("yesterday"), limit=10, query="yesterday")
        assert [r["key"] for r in today["results"]] == ["at-midnight"]
        assert [r["key"] for r in yesterday["results"]] == ["before"]
    run_with_plane(kind, tmp_path, scenario)


def test_backend_failure_propagates(kind, tmp_path):
    async def scenario(plane):
        async def boom(**kwargs):
            raise RuntimeError("storage fault")

        plane.backend.list_page = boom
        with pytest.raises(RuntimeError, match="storage fault"):
            await plane.recall_time_window(intent_for("today"), limit=10, query="today")
    run_with_plane(kind, tmp_path, scenario)


def test_explain_is_flagged_unsupported(kind, tmp_path):
    async def scenario(plane):
        await fill(plane, [entry("t", "today item", when=at(0, hours=1))])
        payload = await plane.recall_time_window(intent_for("today"), limit=5, query="today", explain=True)
        assert payload["explain_supported"] is False
        assert payload["routed"] == "time_window"
        plain = await plane.recall_time_window(intent_for("today"), limit=5, query="today")
        assert "explain_supported" not in plain
    run_with_plane(kind, tmp_path, scenario)


def test_no_backend_is_not_routed():
    plane = StatePlane()
    payload = asyncio.new_event_loop().run_until_complete(
        plane.recall_time_window(intent_for("today"), limit=5, query="today"))
    assert payload is None
