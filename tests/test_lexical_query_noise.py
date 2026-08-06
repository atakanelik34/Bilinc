"""Neutral tests for bounded lexical query-noise handling."""

from bilinc.core.models import MemoryEntry
from bilinc.core.stateplane import StatePlane


def test_lexical_ranking_prioritizes_content_terms_over_question_words():
    plane = StatePlane()
    candidates = {
        "memory:content": MemoryEntry(
            key="memory:content",
            value="Caroline researched adoption agencies.",
            importance=0.5,
        ),
        "memory:function": MemoryEntry(
            key="memory:function",
            value="What did the team do about the deployment?",
            importance=0.5,
        ),
    }

    ranked = plane._rank_lexical_keys("What did Caroline research?", candidates)

    assert ranked[0] == "memory:content"


def test_lexical_ranking_returns_no_signal_for_function_words_only():
    plane = StatePlane()
    candidates = {
        "memory:one": MemoryEntry(key="memory:one", value="What did we do?"),
        "memory:two": MemoryEntry(key="memory:two", value="How are you?"),
    }

    assert plane._rank_lexical_keys("What did we do?", candidates) == []


def test_query_intent_tokenization_remains_available_outside_lexical_ranking():
    plane = StatePlane()

    assert "current" in plane._tokenize_query("What is the current state?")
    assert "before" in plane._tokenize_query("What happened before launch?")
