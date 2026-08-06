"""Neutral tests for point-in-time recall using source event timestamps."""

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.core.temporal import entry_event_timestamp, parse_temporal_timestamp, temporal_query_constraints
from bilinc.storage.sqlite import SQLiteBackend


def test_temporal_parser_normalizes_timezone_offsets():
    assert parse_temporal_timestamp("2024-01-01T00:00:00+02:00") == parse_temporal_timestamp(
        "2023-12-31T22:00:00Z"
    )


def test_temporal_parser_accepts_human_readable_source_dates():
    assert parse_temporal_timestamp("1:56 pm on 8 May, 2023") == parse_temporal_timestamp(
        "2023-05-08T13:56:00Z"
    )
    assert parse_temporal_timestamp("8th May, 2023 1:56 pm") == parse_temporal_timestamp(
        "2023-05-08T13:56:00Z"
    )


def test_entry_event_timestamp_accepts_source_date_time_metadata():
    entry = MemoryEntry(metadata={"source_date_time": "7:55 pm on 9 June, 2023"})

    assert entry_event_timestamp(entry) == parse_temporal_timestamp("2023-06-09T19:55:00Z")


def test_temporal_query_constraints_extract_month_day_and_year():
    assert temporal_query_constraints("Which book did Jolene read in January 2023?") == {
        "month": 1,
        "year": 2023,
    }
    assert temporal_query_constraints("What happened on 8th May, 2023?") == {
        "day": 8,
        "month": 5,
        "year": 2023,
    }


@pytest.mark.asyncio
async def test_recall_as_of_excludes_future_source_events(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "as-of.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()

    await backend.restore(
        MemoryEntry(
            key="memory:before",
            value="the deployment target is the stable cluster",
            memory_type=MemoryType.SEMANTIC,
            metadata={"source_timestamp": "2024-01-10T12:00:00+00:00"},
        )
    )
    await backend.restore(
        MemoryEntry(
            key="memory:after",
            value="the deployment target is the experimental cluster",
            memory_type=MemoryType.SEMANTIC,
            metadata={"source_timestamp": "2024-02-10T12:00:00+00:00"},
        )
    )

    results = await plane.recall_intelligent(
        "deployment target",
        limit=10,
        query_timestamp="2024-01-31T12:00:00+00:00",
    )

    assert [result["key"] for result in results] == ["memory:before"]


@pytest.mark.asyncio
async def test_recall_without_as_of_preserves_existing_behavior(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "no-as-of.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()

    for key, timestamp in (("memory:before", "2024-01-10T12:00:00+00:00"), ("memory:after", "2024-02-10T12:00:00+00:00")):
        await backend.restore(
            MemoryEntry(
                key=key,
                value="deployment target evidence",
                memory_type=MemoryType.SEMANTIC,
                metadata={"source_timestamp": timestamp},
            )
        )

    results = await plane.recall_intelligent("deployment target", limit=10)

    assert {result["key"] for result in results} == {"memory:before", "memory:after"}


@pytest.mark.asyncio
async def test_recall_as_of_restores_historical_superseded_state(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "as-of-superseded.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()

    await backend.restore(
        MemoryEntry(
            key="memory:old",
            value="the deployment target is the stable cluster",
            memory_type=MemoryType.SEMANTIC,
            superseded_by="memory:new",
            metadata={"source_timestamp": "2024-01-10T12:00:00+00:00"},
        )
    )
    await backend.restore(
        MemoryEntry(
            key="memory:new",
            value="the deployment target is the experimental cluster",
            memory_type=MemoryType.SEMANTIC,
            metadata={"source_timestamp": "2024-02-10T12:00:00+00:00"},
        )
    )

    results = await plane.recall_intelligent(
        "deployment target",
        limit=10,
        query_timestamp="2024-01-31T12:00:00+00:00",
    )

    assert [result["key"] for result in results] == ["memory:old"]


@pytest.mark.asyncio
async def test_recall_as_of_honors_invalid_at_and_ttl_cutoffs(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "as-of-expiry.sqlite"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()

    await backend.restore(
        MemoryEntry(
            key="memory:expired",
            value="the region is eu-west",
            memory_type=MemoryType.SEMANTIC,
            metadata={"source_timestamp": "2024-01-01T00:00:00+00:00"},
            invalid_at="2024-01-15T00:00:00+00:00",
        )
    )
    await backend.restore(
        MemoryEntry(
            key="memory:ttl",
            value="the region is us-east",
            memory_type=MemoryType.SEMANTIC,
            metadata={"source_timestamp": "2024-01-01T00:00:00+00:00"},
            created_at=1704067200.0,
            ttl=86400.0,
        )
    )

    results = await plane.recall_intelligent(
        "region",
        limit=10,
        query_timestamp="2024-01-31T00:00:00+00:00",
    )

    assert results == []


def test_invalid_as_of_is_non_filtering_and_does_not_raise():
    plane = StatePlane()
    candidates = {
        "before": MemoryEntry(metadata={"source_timestamp": "not-a-date"}),
        "after": MemoryEntry(metadata={"source_timestamp": "2024-02-10T12:00:00+00:00"}),
    }

    filtered = plane._filter_candidates_as_of(candidates, "also-not-a-date")

    assert set(filtered) == set(candidates)


def test_temporal_direction_rank_uses_source_event_time_only_for_directional_queries():
    plane = StatePlane()
    candidates = {
        "memory:old": MemoryEntry(
            key="memory:old",
            value="the launch happened",
            metadata={"source_timestamp": "2024-01-01T00:00:00Z"},
        ),
        "memory:middle": MemoryEntry(
            key="memory:middle",
            value="the launch happened",
            metadata={"source_timestamp": "2024-02-01T00:00:00Z"},
        ),
        "memory:new": MemoryEntry(
            key="memory:new",
            value="the launch happened",
            metadata={"source_timestamp": "2024-03-01T00:00:00Z"},
        ),
    }

    assert plane._rank_temporal_keys("What happened before the launch?", candidates) == [
        "memory:old",
        "memory:middle",
        "memory:new",
    ]
    assert plane._rank_temporal_keys("What happened after the launch?", candidates) == [
        "memory:new",
        "memory:middle",
        "memory:old",
    ]
    assert plane._rank_temporal_keys("When did the launch happen?", candidates) == []


def test_temporal_direction_rank_accepts_natural_source_date_time():
    plane = StatePlane()
    candidates = {
        "memory:old": MemoryEntry(
            key="memory:old",
            value="the launch happened",
            metadata={"source_date_time": "1:00 pm on 8 May, 2023"},
        ),
        "memory:new": MemoryEntry(
            key="memory:new",
            value="the launch happened",
            metadata={"source_date_time": "2:00 pm on 8 May, 2023"},
        ),
    }

    assert plane._rank_temporal_keys("What happened before the launch?", candidates) == [
        "memory:old",
        "memory:new",
    ]


def test_temporal_rank_prefers_explicit_date_constraint():
    plane = StatePlane()
    candidates = {
        "memory:february": MemoryEntry(
            key="memory:february",
            value="the launch happened",
            metadata={"source_date_time": "1:00 pm on 8 February, 2023"},
        ),
        "memory:january": MemoryEntry(
            key="memory:january",
            value="the launch happened",
            metadata={"source_date_time": "1:00 pm on 8 January, 2023"},
        ),
    }

    assert plane._rank_temporal_keys("Which event happened in January 2023?", candidates) == [
        "memory:january",
    ]


def test_temporal_rank_ignores_non_discriminating_year_constraint():
    plane = StatePlane()
    candidates = {
        "memory:old": MemoryEntry(
            key="memory:old",
            value="the launch happened",
            metadata={"source_date_time": "1:00 pm on 8 January, 2023"},
        ),
        "memory:new": MemoryEntry(
            key="memory:new",
            value="the launch happened",
            metadata={"source_date_time": "1:00 pm on 8 February, 2023"},
        ),
    }

    assert plane._rank_temporal_keys("Which event happened in 2023?", candidates) == []
