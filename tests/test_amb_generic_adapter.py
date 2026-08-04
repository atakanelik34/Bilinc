"""Unit tests for the provider-neutral AMB adapter helpers."""

from benchmarks.adapters.amb_generic_mcp import _scope_visible


def test_agent_scope_requires_matching_agent():
    metadata = {"scope": "agent", "agent_id": "a"}
    assert _scope_visible(metadata, "a", "agent")
    assert not _scope_visible(metadata, "b", "agent")


def test_private_agent_memory_is_hidden_without_matching_agent():
    metadata = {"scope": "agent", "agent_id": "a"}
    assert not _scope_visible(metadata, "b", None)
    assert _scope_visible(metadata, "a", None)


def test_shared_memory_is_visible_to_other_agents():
    metadata = {"scope": "org", "agent_id": "a"}
    assert _scope_visible(metadata, "b", None)
