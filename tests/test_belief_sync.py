"""
Tests for Multi-Agent Belief Sync (Step 3.3).

Covering:
1. Basic push/pull roundtrip
2. Bidirectional merge reconcile
3. Same key, different values → resolution
4. Majority vote across 3 agents
5. Detect and list conflicts
"""

import pytest
import time
from bilinc.core.models import MemoryType, MemoryEntry
from bilinc.core.belief_sync import BeliefSyncEngine, SyncMode


# ── Helpers ───────────────────────────────────────────────────

def _entry(key: str, value, importance: float = 1.0) -> MemoryEntry:
    return MemoryEntry(
        key=key,
        value=value,
        importance=importance,
        memory_type=MemoryType.SEMANTIC,
    )


@pytest.fixture
def sync_engine():
    return BeliefSyncEngine()


@pytest.fixture
def two_agents(sync_engine: BeliefSyncEngine):
    sync_engine.init_sync("alice", reliability=0.9)
    sync_engine.init_sync("bob", reliability=0.7)
    return sync_engine


@pytest.fixture
def three_agents(sync_engine: BeliefSyncEngine):
    sync_engine.init_sync("alice", reliability=0.8)
    sync_engine.init_sync("bob", reliability=0.6)
    sync_engine.init_sync("charlie", reliability=0.5)
    return sync_engine


# ── Test 1: Push/Pull ────────────────────────────────────────

class TestBeliefSyncPushPull:
    def test_belief_sync_push(self, two_agents: BeliefSyncEngine):
        """Basic push should add beliefs to shared space."""
        entries = [
            _entry("config_theme", "dark"),
            _entry("config_lang", "tr"),
        ]
        result = two_agents.push_beliefs("alice", entries)

        assert result.success is True
        assert result.beliefs_pushed == 2
        assert result.mode == SyncMode.PUSH

    def test_belief_sync_pull(self, two_agents: BeliefSyncEngine):
        """Bob should pull Alice's beliefs."""
        alice_entries = [
            _entry("db_host", "prod.db.internal"),
            _entry("cache_ttl", 3600),
        ]
        two_agents.push_beliefs("alice", alice_entries)

        result = two_agents.pull_updates("bob")

        assert result.success is True
        assert result.beliefs_pulled == 2
        assert result.mode == SyncMode.PULL

        # Verify Bob has Alice's beliefs
        bob = two_agents.agents["bob"]
        stored = bob.belief_state.get_belief("db_host")
        assert stored is not None
        assert stored.value == "prod.db.internal"

    def test_belief_sync_pull_since_timestamp(self, two_agents: BeliefSyncEngine):
        """Pull should respect since_timestamp."""
        ts_before = time.time()

        # Push old entry (before our timestamp)
        old = _entry("old_key", "old_val")
        old.created_at = ts_before - 100
        two_agents.push_beliefs("alice", [old])

        # Push new entry (after our timestamp)
        new = _entry("new_key", "new_val")
        new.created_at = time.time()
        two_agents.push_beliefs("alice", [new])

        result = two_agents.pull_updates("bob", since_timestamp=ts_before)

        # Should pull the new one
        assert result.beliefs_pulled >= 1
        stored = two_agents.agents["bob"].belief_state.get_belief("new_key")
        assert stored is not None


# ── Test 2: Merge (Bidirectional) ────────────────────────────

class TestBeliefSyncMerge:
    def test_belief_sync_merge_no_conflict(self, two_agents: BeliefSyncEngine):
        """Merge with completely different keys should merge all."""
        two_agents.push_beliefs("alice", [_entry("a_key", "a_val")])
        two_agents.push_beliefs("bob", [_entry("b_key", "b_val")])

        result = two_agents.merge_sync("alice", "bob")

        assert result.success is True
        assert result.conflicts_resolved == 0

        # Both agents should have both keys
        alice_b = two_agents.agents["alice"].belief_state.get_belief("b_key")
        bob_a = two_agents.agents["bob"].belief_state.get_belief("a_key")
        assert alice_b is not None
        assert bob_a is not None

    def test_belief_sync_merge_conflict_reliability_wins(self, two_agents: BeliefSyncEngine):
        """Same key, different values → higher reliability wins."""
        two_agents.push_beliefs("alice", [_entry("shared", "alice_value")])
        two_agents.push_beliefs("bob", [_entry("shared", "bob_value")])

        # Alice has higher reliability (0.9 > 0.7)
        result = two_agents.merge_sync("alice", "bob")

        assert result.conflicts_resolved >= 1

        # Bob should adopt Alice's value (higher reliability)
        bob_entry = two_agents.agents["bob"].belief_state.get_belief("shared")
        assert bob_entry is not None
        assert bob_entry.value == "alice_value"


# ── Test 3: Conflict Resolution ──────────────────────────────

class TestBeliefSyncConflict:
    def test_belief_sync_conflict_different_values(self, two_agents: BeliefSyncEngine):
        """Same key with different values should trigger resolution."""
        two_agents.push_beliefs("alice", [_entry("mode", "debug", importance=0.9)])
        two_agents.push_beliefs("bob", [_entry("mode", "production", importance=0.5)])

        result = two_agents.merge_sync("alice", "bob")

        assert result.conflicts_resolved >= 1

    def test_belief_sync_conflict_equal_reliability(self, two_agents: BeliefSyncEngine):
        """Equal reliability → first agent's value should win (>= check)."""
        sync = BeliefSyncEngine()
        sync.init_sync("x", reliability=0.5)
        sync.init_sync("y", reliability=0.5)
        sync.push_beliefs("x", [_entry("k", "v_x")])
        sync.push_beliefs("y", [_entry("k", "v_y")])

        result = sync.merge_sync("x", "y")
        assert result.conflicts_resolved >= 1


# ── Test 4: Consensus ────────────────────────────────────────

class TestBeliefSyncConsensus:
    def test_belief_sync_consensus_majority(self, three_agents: BeliefSyncEngine):
        """2 out of 3 agents agree → majority wins."""
        three_agents.push_beliefs("alice", [_entry("db", "postgres")])
        three_agents.push_beliefs("bob", [_entry("db", "postgres")])
        three_agents.push_beliefs("charlie", [_entry("db", "mysql")])

        result = three_agents.consensus_sync(["alice", "bob", "charlie"])

        assert result.success is True
        assert result.conflicts_resolved >= 1

        # All agents should now have the majority value
        for aid in ["alice", "bob", "charlie"]:
            agent = three_agents.agents[aid]
            stored = agent.belief_state.get_belief("db")
            assert stored is not None
            assert stored.value == "postgres"

    def test_belief_sync_consensus_needs_two_agents(self, three_agents: BeliefSyncEngine):
        """Consensus with < 2 agents should fail."""
        result = three_agents.consensus_sync(["alice"])
        assert result.success is False


# ── Test 5: Divergence Detection ─────────────────────────────

class TestBeliefSyncDivergence:
    def test_belief_sync_divergence_detect_conflict(self, two_agents: BeliefSyncEngine):
        """Detect and list conflicting beliefs."""
        two_agents.push_beliefs("alice", [
            _entry("theme", "dark"),
            _entry("lang", "tr"),
        ])
        two_agents.push_beliefs("bob", [
            _entry("theme", "light"),
            _entry("lang", "tr"),  # Same → no divergence
        ])

        divergence = two_agents.get_divergence("alice", "bob")

        conflicts = [d for d in divergence if d["status"] == "conflict"]
        assert len(conflicts) >= 1
        assert conflicts[0]["key"] == "theme"

        # lang should NOT diverge (same value)
        lang_divs = [d for d in divergence if d["key"] == "lang"]
        assert len(lang_divs) == 0

    def test_belief_sync_divergence_missing_in_one(self, two_agents: BeliefSyncEngine):
        """Key exists in Alice but not Bob."""
        two_agents.push_beliefs("alice", [_entry("secret_key", "value")])

        divergence = two_agents.get_divergence("alice", "bob")

        missing = [d for d in divergence if d["status"] == "missing_in_b"]
        assert len(missing) >= 1
        assert missing[0]["key"] == "secret_key"

    def test_belief_sync_divergence_no_diff(self, two_agents: BeliefSyncEngine):
        """Identical beliefs → no divergence."""
        two_agents.push_beliefs("alice", [_entry("k", "v")])
        two_agents.push_beliefs("bob", [_entry("k", "v")])

        divergence = two_agents.get_divergence("alice", "bob")
        assert len(divergence) == 0

    def test_belief_sync_divergence_unregistered(self, two_agents: BeliefSyncEngine):
        """Query with unregistered agent returns empty list."""
        d = two_agents.get_divergence("alice", "nonexistent")
        assert d == []
