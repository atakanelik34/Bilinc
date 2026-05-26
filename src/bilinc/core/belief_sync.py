"""
Multi-Agent Belief Sync — Step 3.3

Synchronize beliefs across multiple agent instances with:
- Vector Clock for causal ordering
- Push/Pull/Merge sync modes
- Conflict resolution via AGM revision
- Consensus-based and authority-based weighting
- Divergence detection
"""

from __future__ import annotations

import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from bilinc.core.models import MemoryEntry, BeliefState

logger = logging.getLogger(__name__)


# ─── Enums ─────────────────────────────────────────────────────

class SyncMode(str, Enum):
    PUSH = "push"
    PULL = "pull"
    MERGE = "merge"


# ─── Data Classes ──────────────────────────────────────────────

@dataclass
class AgentIdentity:
    """Named agent with its own belief state and reliability weight."""
    agent_id: str
    belief_state: BeliefState = field(default_factory=BeliefState)
    reliability: float = 1.0      # 0.0–1.0, used for authority-based sync
    registered_at: float = field(default_factory=time.time)
    last_sync_at: float = 0.0
    sync_count: int = 0


@dataclass
class SyncResult:
    """Result of a sync operation."""
    mode: SyncMode
    agent_id: str
    beliefs_pushed: int = 0
    beliefs_pulled: int = 0
    conflicts_resolved: int = 0
    divergence_count: int = 0
    success: bool = True
    detail: str = ""
    timestamp: float = field(default_factory=time.time)


# ─── Belief Sync Engine ────────────────────────────────────────

class BeliefSyncEngine:
    """
    Synchronize beliefs across multiple agent instances.
    
    Uses vector clocks for causal ordering and AGM-compatible
    conflict resolution when beliefs diverge.
    """

    def __init__(self):
        self.agents: Dict[str, AgentIdentity] = {}
        self._vector_clocks: Dict[str, Dict[str, int]] = {}
        self.sync_log: List[SyncResult] = []

    # ─── Agent Registration ────────────────────────────────────

    def init_sync(self, agent_id: str, reliability: float = 1.0) -> AgentIdentity:
        """Register an agent for sync."""
        if agent_id not in self.agents:
            self.agents[agent_id] = AgentIdentity(
                agent_id=agent_id,
                reliability=max(0.0, min(1.0, reliability)),
            )
            self._vector_clocks[agent_id] = {}
        return self.agents[agent_id]

    def _vclock(self, agent_id: str) -> Dict[str, int]:
        """Get or create vector clock for an agent."""
        if agent_id not in self._vector_clocks:
            self._vector_clocks[agent_id] = {}
        return self._vector_clocks[agent_id]

    def _vclock_tick(self, agent_id: str, key: str) -> None:
        """Increment vector clock entry."""
        vc = self._vclock(agent_id)
        vc[key] = vc.get(key, 0) + 1

    def _vclock_merge(self, vc_a: Dict[str, int], vc_b: Dict[str, int]) -> Dict[str, int]:
        """Merge two vector clocks (element-wise max)."""
        merged = dict(vc_a)
        for k, v in vc_b.items():
            merged[k] = max(merged.get(k, 0), v)
        return merged

    @staticmethod
    def _vclock_compare(vc_a: Dict[str, int], vc_b: Dict[str, int]) -> str:
        """
        Compare two vector clocks.
        Returns: 'before', 'after', 'concurrent', or 'equal'.
        """
        all_keys = set(list(vc_a.keys()) + list(vc_b.keys()))
        if not all_keys:
            return "equal"

        a_leq_b = all(vc_a.get(k, 0) <= vc_b.get(k, 0) for k in all_keys)
        b_leq_a = all(vc_b.get(k, 0) <= vc_a.get(k, 0) for k in all_keys)

        if a_leq_b and b_leq_a:
            return "equal"
        elif a_leq_b:
            return "before"
        elif b_leq_a:
            return "after"
        else:
            return "concurrent"

    # ─── Push ──────────────────────────────────────────────────

    def push_beliefs(
        self,
        agent_id: str,
        entries: List[MemoryEntry],
    ) -> SyncResult:
        """
        Agent pushes its beliefs to the shared belief space.
        Each pushed entry gets a vector clock tick.
        """
        agent = self.agents.get(agent_id)
        if agent is None:
            return SyncResult(mode=SyncMode.PUSH, agent_id=agent_id, success=False, detail="Agent not registered")

        pushed = 0
        for entry in entries:
            self._vclock_tick(agent_id, entry.key)
            # Upsert into shared space
            existing = agent.belief_state.get_belief(entry.key)
            if existing is None or entry.created_at > existing.created_at:
                agent.belief_state.add_belief(entry)
                agent.belief_state.revision_count += 1
                pushed += 1

        agent.last_sync_at = time.time()
        agent.sync_count += 1

        result = SyncResult(
            mode=SyncMode.PUSH,
            agent_id=agent_id,
            beliefs_pushed=pushed,
            detail=f"Pushed {pushed} beliefs to shared space",
        )
        self.sync_log.append(result)
        return result

    # ─── Pull ──────────────────────────────────────────────────

    def pull_updates(
        self,
        agent_id: str,
        since_timestamp: Optional[float] = None,
        from_agents: Optional[List[str]] = None,
    ) -> SyncResult:
        """
        Agent pulls updates from other agents' shared belief spaces.
        Only gets entries newer than since_timestamp.
        """
        agent = self.agents.get(agent_id)
        if agent is None:
            return SyncResult(mode=SyncMode.PULL, agent_id=agent_id, success=False, detail="Agent not registered")

        pulled = 0
        sources = from_agents or [a for a in self.agents if a != agent_id]

        for source_id in sources:
            source = self.agents.get(source_id)
            if source is None:
                continue

            for key, entry in source.belief_state.beliefs.items():
                # Skip if we have a newer version
                existing = agent.belief_state.get_belief(key)
                if existing and existing.created_at >= entry.created_at:
                    continue
                if since_timestamp and entry.created_at < since_timestamp:
                    continue

                self._vclock_tick(agent_id, key)
                agent.belief_state.add_belief(entry)
                agent.belief_state.revision_count += 1
                pulled += 1

        agent.last_sync_at = time.time()
        agent.sync_count += 1

        result = SyncResult(
            mode=SyncMode.PULL,
            agent_id=agent_id,
            beliefs_pulled=pulled,
            detail=f"Pulled {pulled} beliefs from {sources}",
        )
        self.sync_log.append(result)
        return result

    # ─── Merge (Bidirectional) ─────────────────────────────────

    def merge_sync(
        self,
        agent_id: str,
        with_agent: str,
    ) -> SyncResult:
        """
        Full bidirectional reconciliation between two agents.
        Conflicts resolved by reliability-weighted preference.
        """
        a = self.agents.get(agent_id)
        b = self.agents.get(with_agent)
        if a is None or b is None:
            return SyncResult(mode=SyncMode.MERGE, agent_id=agent_id, success=False, detail="One or both agents not registered")

        # 1. Push A → B
        a_entries = list(a.belief_state.beliefs.values())
        b_entries = list(b.belief_state.beliefs.values())

        conflicts = 0
        merged_a = 0
        merged_b = 0

        # A → B
        for entry in a_entries:
            existing = b.belief_state.get_belief(entry.key)
            if existing is None:
                b.belief_state.add_belief(entry)
                b.belief_state.revision_count += 1
                merged_b += 1
                self._vclock_tick(with_agent, entry.key)
            elif entry.value != existing.value:
                # Conflict: pick winner by reliability
                conflicts += 1
                if a.reliability >= b.reliability:
                    # A wins
                    b.belief_state.add_belief(entry)
                    merged_b += 1
                # else: B keeps its version
                self._vclock_tick(with_agent, entry.key)

        # B → A
        for entry in b_entries:
            existing = a.belief_state.get_belief(entry.key)
            if existing is None:
                a.belief_state.add_belief(entry)
                a.belief_state.revision_count += 1
                merged_a += 1
                self._vclock_tick(agent_id, entry.key)
            elif entry.value != existing.value:
                conflicts += 1
                if b.reliability >= a.reliability:
                    # B wins
                    a.belief_state.add_belief(entry)
                    merged_a += 1
                self._vclock_tick(agent_id, entry.key)

        a.last_sync_at = time.time()
        a.sync_count += 1
        b.last_sync_at = time.time()
        b.sync_count += 1

        result = SyncResult(
            mode=SyncMode.MERGE,
            agent_id=agent_id,
            beliefs_pushed=merged_b,
            beliefs_pulled=merged_a,
            conflicts_resolved=conflicts,
            detail=f"Merged {merged_a}+{merged_b} beliefs, resolved {conflicts} conflicts",
        )
        self.sync_log.append(result)
        return result

    # ─── Consensus (multi-agent) ──────────────────────────────

    def consensus_sync(
        self,
        agent_ids: List[str],
    ) -> SyncResult:
        """
        Majority vote sync across multiple agents.
        Most common belief value wins. Ties broken by reliability.
        """
        if len(agent_ids) < 2:
            return SyncResult(
                mode=SyncMode.MERGE,
                agent_id="consensus",
                success=False,
                detail="Need at least 2 agents for consensus",
            )

        # Collect all beliefs
        all_beliefs: Dict[str, List[MemoryEntry]] = {}
        for aid in agent_ids:
            agent = self.agents.get(aid)
            if agent is None:
                continue
            for key, entry in agent.belief_state.beliefs.items():
                all_beliefs.setdefault(key, []).append(entry)

        conflicts = 0
        # For each key with multiple different values, vote
        for key, entries in all_beliefs.items():
            if len(entries) < 2:
                continue
            values = set(str(e.value) for e in entries)
            if len(values) <= 1:
                continue  # All same

            conflicts += 1
            # Vote: count occurrences of each value
            value_votes: Dict[str, List[MemoryEntry]] = {}
            for e in entries:
                val_str = str(e.value)
                value_votes.setdefault(val_str, []).append(e)

            # Find highest vote count
            max_votes = max(len(v) for v in value_votes.values())
            candidates = [v for v in value_votes.values() if len(v) == max_votes]

            if len(candidates) == 1:
                winner = candidates[0][0]
            else:
                # Tie: pick highest reliability
                best_rel = -1
                winner = candidates[0][0]
                for group in candidates:
                    best_in_group = max(group, key=lambda e: self.agents.get(e.source, agent).reliability if hasattr(e, 'source') else 0.5)
                    rel = self.agents.get(best_in_group.source, agent).reliability if hasattr(best_in_group, 'source') else 0.5
                    if rel > best_rel:
                        best_rel = rel
                        winner = best_in_group

            # Set winner in all agents
            for aid in agent_ids:
                agent = self.agents.get(aid)
                if agent:
                    agent.belief_state.add_belief(winner)

        # After consensus, sync all agents
        for aid in agent_ids:
            agent = self.agents.get(aid)
            if agent:
                agent.last_sync_at = time.time()
                agent.sync_count += 1

        result = SyncResult(
            mode=SyncMode.MERGE,
            agent_id="consensus",
            conflicts_resolved=conflicts,
            detail=f"Consensus across {len(agent_ids)} agents, resolved {conflicts} conflicts",
        )
        self.sync_log.append(result)
        return result

    # ─── Divergence Detection ──────────────────────────────────

    def get_divergence(
        self,
        agent_a: str,
        agent_b: str,
    ) -> List[Dict[str, Any]]:
        """
        List all beliefs where agent_a and agent_b differ.
        Returns list of dicts with key, value_a, value_b.
        """
        a = self.agents.get(agent_a)
        b = self.agents.get(agent_b)
        if a is None or b is None:
            return []

        divergence: List[Dict[str, Any]] = []
        all_keys = set(list(a.belief_state.beliefs.keys()) + list(b.belief_state.beliefs.keys()))

        for key in all_keys:
            entry_a = a.belief_state.get_belief(key)
            entry_b = b.belief_state.beliefs.get(key)

            if entry_a is None and entry_b is not None:
                divergence.append({
                    "key": key,
                    "status": "missing_in_a",
                    "value_a": None,
                    "value_b": entry_b.value,
                })
            elif entry_b is None and entry_a is not None:
                divergence.append({
                    "key": key,
                    "status": "missing_in_b",
                    "value_a": entry_a.value,
                    "value_b": None,
                })
            elif entry_a is not None and entry_b is not None and entry_a.value != entry_b.value:
                divergence.append({
                    "key": key,
                    "status": "conflict",
                    "value_a": entry_a.value,
                    "value_b": entry_b.value,
                })

        return divergence

    # ─── Stats ─────────────────────────────────────────────────

    def get_sync_stats(self) -> Dict[str, Any]:
        """Summary of sync activity."""
        return {
            "agents": len(self.agents),
            "total_syncs": sum(a.sync_count for a in self.agents.values()),
            "sync_log_entries": len(self.sync_log),
            "active_agents": [
                aid for aid, a in self.agents.items()
                if a.last_sync_at > 0
            ],
        }
