"""Neutral tests for corpus-aware lexical ranking."""

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane


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


def test_current_state_boost_recognizes_common_temporal_intents():
    plane = StatePlane()
    older = MemoryEntry(key="older", created_at=10.0, updated_at=10.0)
    newer = MemoryEntry(key="newer", created_at=20.0, updated_at=20.0)

    for query in (
        "what do we currently use",
        "where do we deploy now",
        "what is the latest API version",
        "what is the newest deployment target",
        "what is the present deployment target",
    ):
        scores = {"older": 1.0, "newer": 1.0}
        plane._apply_current_state_boost(query, scores, {"older": older, "newer": newer})
        assert scores["newer"] > scores["older"], query


def test_current_state_boost_can_reproduce_legacy_intent_mode(monkeypatch):
    plane = StatePlane()
    older = MemoryEntry(key="older", created_at=10.0, updated_at=10.0)
    newer = MemoryEntry(key="newer", created_at=20.0, updated_at=20.0)
    monkeypatch.setenv("BILINC_CURRENT_STATE_INTENTS", "legacy")

    scores = {"older": 1.0, "newer": 1.0}
    plane._apply_current_state_boost("what is the latest deployment target", scores, {"older": older, "newer": newer})

    assert scores == {"older": 1.0, "newer": 1.0}
