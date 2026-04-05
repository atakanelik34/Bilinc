"""
StatePlane: Context-Independent Typed State Storage

Based on StatePlane (arXiv:2603.13644) — decouples cognitive state
from context windows entirely. The model prompt receives clean
result vectors, not raw data.

Key innovation: State is stored separately from the model's context window,
and only the most relevant, verified portions are injected.
"""

from __future__ import annotations

import time
import json
import logging
from typing import Any, Dict, List, Optional, Union, Set
from dataclasses import dataclass, field

from synaptic_state.core.models import (
    MemoryEntry, MemoryType, BeliefState, CCSDimension
)
from synaptic_state.core.agm import AGMEngine, AGMResult
from synaptic_state.core.verification import VerificationGate, VerificationResult, VerificationStatus
from synaptic_state.retrieval.hybrid import HybridRetriever
from synaptic_state.adaptive.budget import ContextBudgetRL
from synaptic_state.adaptive.forgetting import LearnableForgetting

logger = logging.getLogger(__name__)


@dataclass
class StatePlaneConfig:
    """Configuration for the StatePlane."""
    # Storage
    backend: str = "memory"  # memory, postgresql, sqlite
    connection_string: str = ""
    
    # Neural (System 1) 
    neural_backend: str = "vector"  # vector, embeddings, in-memory
    embedding_model: str = "all-MiniLM-L6-v2"
    vector_dim: int = 384
    
    # Symbolic (System 2)
    symbolic_backend: str = "graph"  # graph, rules, in-memory
    graph_max_nodes: int = 10_000
    
    # Verification
    verification_min_confidence: float = 0.5
    verification_check_staleness: bool = True
    verification_stale_hours: float = 168.0  # 1 week
    
    # Budget
    default_budget_tokens: int = 2048
    max_budget_tokens: int = 8192
    budget_strategy: str = "rl_optimized"  # greedy, rl_optimized
    
    # Forgetting
    default_decay_rate: float = 0.01
    forgetting_enabled: bool = True
    
    # AGM
    agm_allow_inconsistency: bool = False
    
    # Observability
    tracing_enabled: bool = True
    audit_enabled: bool = True


@dataclass
class RecallResult:
    """Result of a recall operation."""
    memories: List[MemoryEntry]
    total_tokens_estimated: int
    strategy_used: str
    budget_requested: int
    budget_allocated: Dict[str, int]
    verification_results: List[VerificationResult]
    stale_count: int
    conflict_count: int
    provenance_info: Dict[str, Any]


class StatePlane:
    """
    The core state plane for SynapticAI.
    
    Manages neuro-symbolic memory across two systems:
    - System 1 (Neural): Fast, approximate retrieval
    - System 2 (Symbolic): Slow, precise reasoning
    
    Features:
    - Context-independent storage
    - Verification-gated commits
    - AGM belief revision
    - Budget-aware recall
    - Learnable forgetting
    - Full observability
    """
    
    def __init__(self, config: Optional[StatePlaneConfig] = None, **kwargs):
        self.config = config or StatePlaneConfig(**kwargs)
        
        # Core components
        self.belief_state = BeliefState()
        self.agm_engine = AGMEngine(self.belief_state)
        self.verification_gate = VerificationGate(
            min_confidence=self.config.verification_min_confidence,
            check_staleness=self.config.verification_check_staleness,
            stale_threshold_hours=self.config.verification_stale_hours,
        )
        self.retriever = HybridRetriever(
            dim=self.config.vector_dim,
            backend=self.config.neural_backend,
        )
        self.budget_optimizer = ContextBudgetRL(
            default_budget=self.config.default_budget_tokens,
            max_budget=self.config.max_budget_tokens,
        )
        self.forgetting_engine = LearnableForgetting(
            default_decay_rate=self.config.default_decay_rate,
            enabled=self.config.forgetting_enabled,
        )
        
        # Memory storage (in-memory for now, extensible to postgresql/sqlite)
        self._storage: Dict[str, MemoryEntry] = {}
        
        # Observability
        self._trace_log: List[Dict[str, Any]] = []
        self._stats = {
            "total_commits": 0,
            "total_recalls": 0,
            "total_verifications": 0,
            "total_revisions": 0,
            "total_conflicts": 0,
            "total_forgets": 0,
        }
    
    # ─── Commit Pipeline ─────────────────────────────────────────
    
    def commit(
        self,
        key: str,
        value: Any,
        memory_type: Union[MemoryType, str] = MemoryType.EPISODIC,
        metadata: Optional[Dict[str, Any]] = None,
        verify: bool = True,
        ttl: Optional[float] = None,
        source: str = "user",
        session_id: str = "",
    ) -> Dict[str, Any]:
        """
        Commit a new memory entry through the full pipeline:
        1. Create entry with typed state
        2. Apply forgetting decay
        3. Verify against existing beliefs
        4. Commit via AGM (EXPAND, CONTRACT, or REVISE)
        """
        if isinstance(memory_type, str):
            memory_type = MemoryType(memory_type)
        
        # Step 1: Create entry
        entry = MemoryEntry(
            key=key,
            value=value,
            memory_type=memory_type,
            metadata=metadata or {},
            source=source,
            session_id=session_id,
            ttl=ttl,
        )
        
        # Step 2: Apply initial importance scoring
        entry.importance = self._estimate_importance(entry)
        entry.decay_rate = self.config.default_decay_rate
        
        # Step 3: Verification gate
        verification_result = None
        if verify:
            verification_result = self.verification_gate.verify(
                entry, self.belief_state
            )
            self._stats["total_verifications"] += 1
            
            if verification_result.status == VerificationStatus.FAIL:
                self._trace("COMMIT_FAILED_VERIFICATION", {
                    "key": key,
                    "reason": verification_result.reasons,
                    "status": verification_result.status.value,
                })
                return self._build_result("FAILED", entry, verification_result)
            
            if verification_result.status == VerificationStatus.CONFLICT:
                # Attempt AGM revision
                revision_result = self.agm_engine.revise(entry)
                self._stats["total_revisions"] += 1
                self._stats["total_conflicts"] += 1
                
                if not revision_result.success:
                    self._trace("COMMIT_REVISION_FAILED", {
                        "key": key,
                        "reason": revision_result.audit_log,
                    })
                    return self._build_result("REVISION_FAILED", entry, verification_result, revision_result)
                
                self._trace("COMMIT_REVISED", {"key": key, "audit": revision_result.audit_log})
                self._add_to_storage(entry)
                self._apply_to_retriever(entry)
                self._stats["total_commits"] += 1
                return self._build_result("REVISED", entry, verification_result, revision_result)
            
            entry.is_verified = True
            entry.verification_score = verification_result.confidence
            entry.verification_method = "verification_gate"
        
        # Step 4: AGM commit
        if self.belief_state.has_belief(key):
            agm_result = self.agm_engine.revise(entry)
            self._stats["total_revisions"] += 1
        else:
            agm_result = self.agm_engine.expand(entry)
            self._stats["total_conflicts"] += agm_result.conflicts_resolved
        
        if not agm_result.success:
            self._trace("COMMIT_AGM_FAILED", {"key": key, "audit": agm_result.audit_log})
            return self._build_result("AGM_FAILED", entry, verification_result, agm_result)
        
        # Step 5: Store
        self._add_to_storage(entry)
        self._apply_to_retriever(entry)
        self.forgetting_engine.on_commit(entry)
        
        self._stats["total_commits"] += 1
        self._trace("COMMIT_SUCCESS", {
            "key": key,
            "type": entry.memory_type.value,
            "verified": entry.is_verified,
            "confidence": entry.verification_score,
        })
        
        return self._build_result("SUCCESS", entry, verification_result, agm_result)
    
    # ─── Recall Pipeline ─────────────────────────────────────────
    
    def recall(
        self,
        intent: str = "",
        budget_tokens: Optional[int] = None,
        strategy: Optional[str] = None,
        memory_types: Optional[List[MemoryType]] = None,
        min_confidence: float = 0.3,
    ) -> RecallResult:
        """
        Recall memories with budget-aware allocation.
        
        Uses the ContextBudget RL strategy to allocate tokens across
        memory types, then retrieves the most relevant entries.
        """
        requested_budget = budget_tokens or self.config.default_budget_tokens
        strategy_name = strategy or self.config.budget_strategy
        
        # Step 1: Budget allocation
        allocation = self.budget_optimizer.allocate_budget(
            requested_budget=requested_budget,
            strategy=strategy_name,
        )
        
        # Step 2: Apply forgetting decay to all entries
        if self.config.forgetting_enabled:
            self.forgetting_engine.apply_global_decay()
        
        # Step 3: Retrieve across all memory types
        memories = self._retrieve_with_budget(intent, allocation, memory_types, min_confidence)
        
        # Step 4: Verify recalled memories
        verification_results = []
        stale_count = 0
        conflict_count = 0
        
        for entry in memories:
            vr = self.verification_gate.verify_recall(entry, intent)
            verification_results.append(vr)
            if vr.status == VerificationStatus.STALE:
                stale_count += 1
            if vr.status == VerificationStatus.CONFLICT:
                conflict_count += 1
        
        # Estimate token count
        total_tokens = sum(self._estimate_tokens(m) for m in memories)
        
        result = RecallResult(
            memories=memories,
            total_tokens_estimated=total_tokens,
            strategy_used=strategy_name,
            budget_requested=requested_budget,
            budget_allocated=allocation,
            verification_results=verification_results,
            stale_count=stale_count,
            conflict_count=conflict_count,
            provenance_info={
                "retrieved_from_neural": len([m for m in memories if m.memory_type in (MemoryType.EPISODIC, MemoryType.PROCEDURAL)]),
                "retrieved_from_symbolic": len([m for m in memories if m.memory_type in (MemoryType.SEMANTIC, MemoryType.SYMBOLIC)]),
                "total_candidates": len(self._storage),
            }
        )
        
        self._stats["total_recalls"] += 1
        self._trace("RECALL", {
            "intent": intent[:100] if intent else "",
            "budget_requested": requested_budget,
            "memories_recalled": len(memories),
            "tokens_allocated": total_tokens,
            "stale_filter": stale_count,
        })
        
        return result
    
    def forget(self, key: str, reason: str = "manual") -> Optional[MemoryEntry]:
        """
        Explicitly forget (remove) a memory entry.
        """
        if key not in self._storage:
            return None
        
        entry = self._storage.pop(key)
        self.belief_state.remove_belief(key)
        self.retriever.remove(key)
        self.forgetting_engine.on_forget(entry, reason)
        
        self._stats["total_forgets"] += 1
        self._trace("FORGET", {"key": key, "reason": reason})
        
        return entry
    
    def explain_forgetting(self, key: str) -> Dict[str, Any]:
        """
        Explainable forgetting: "Why was this forgotten?"
        """
        if key not in self.forgetting_engine.decay_history:
            return {
                "key": key,
                "status": "not_found",
                "explanation": "No decay history found for this key"
            }
        
        history = self.forgetting_engine.decay_history[key]
        
        return {
            "key": key,
            "status": "found",
            "history": history,
            "explanation": self.forgetting_engine.generate_explanation(key),
        }
    
    # ─── Observability ──────────────────────────────────────────
    
    def get_provenance(self, key: str) -> Optional[List[Dict[str, Any]]]:
        """Get the full provenance chain for a memory entry."""
        traces = [
            t for t in self._trace_log
            if t.get("metadata", {}).get("key") == key
        ]
        return traces if traces else None
    
    def get_drift_report(self) -> Dict[str, Any]:
        """
        Generate drift report: memory quality indicators.
        """
        stale_entries = [
            k for k, v in self._storage.items()
            if v.is_stale()
        ]
        unverified_entries = [
            k for k, v in self._storage.items()
            if not v.is_verified
        ]
        conflicts = self.belief_state.get_conflicts()
        
        return {
            "total_entries": len(self._storage),
            "stale_count": len(stale_entries),
            "stale_keys": stale_entries[:10],
            "unverified_count": len(unverified_entries),
            "unverified_keys": unverified_entries[:10],
            "conflict_groups": conflicts,
            "drift_score": len(stale_entries) / max(len(self._storage), 1),
            "quality_score": 1 - (len(unverified_entries) / max(len(self._storage), 1) * 0.5
                              + len(conflicts) / max(len(self._storage), 1)),
        }
    
    def get_trace_log(self) -> List[Dict[str, Any]]:
        """Get the full trace log."""
        return self._trace_log
    
    def get_stats(self) -> Dict[str, Any]:
        """Get operational statistics."""
        state_summary = self.agm_engine.get_state_summary()
        return {
            **self._stats,
            **state_summary,
            "storage_size": len(self._storage),
            "trace_log_size": len(self._trace_log),
        }
    
    # ─── Internal Methods ───────────────────────────────────────
    
    def _add_to_storage(self, entry: MemoryEntry) -> None:
        """Add entry to internal storage."""
        self._storage[entry.key] = entry
    
    def _apply_to_retriever(self, entry: MemoryEntry) -> None:
        """Add entry to the hybrid retriever."""
        content = f"{entry.key}: {entry.value}"
        if isinstance(entry.value, dict):
            import json
            content = f"{entry.key}: {json.dumps(entry.value)}"
        
        metadata = {
            "type": entry.memory_type.value,
            "source": entry.source,
            "importance": entry.importance,
            "verified": entry.is_verified,
        }
        
        self.retriever.add(entry.id, content, metadata)
    
    def _retrieve_with_budget(
        self,
        intent: str,
        allocation: Dict[str, int],
        memory_types: Optional[List[MemoryType]],
        min_confidence: float,
    ) -> List[MemoryEntry]:
        """Retrieve memories within budget constraints."""
        type_names = [mt.value for mt in memory_types] if memory_types else None
        
        if not intent:
            entries = sorted(
                self._storage.values(),
                key=lambda e: e.importance * e.current_strength,
                reverse=True,
            )
            if memory_types:
                entries = [e for e in entries if e.memory_type in memory_types]
            total_tokens = 0
            result = []
            for entry in entries:
                tokens = self._estimate_tokens(entry)
                if total_tokens + tokens <= self.config.default_budget_tokens:
                    result.append(entry)
                    total_tokens += tokens
            return result
        
        scores = self.retriever.search(intent, top_k=len(self._storage) or 50)
        result = []
        total_tokens = 0
        
        for entry_id, score, metadata in scores:
            entry = None
            for v in self._storage.values():
                if v.id == entry_id:
                    entry = v
                    break
            if entry is None:
                continue
            if entry.current_strength < min_confidence:
                continue
            if memory_types and entry.memory_type not in memory_types:
                continue
            tokens = self._estimate_tokens(entry)
            if total_tokens + tokens > self.config.default_budget_tokens:
                continue
            result.append(entry)
            total_tokens += tokens
        
        return result
    
    def _estimate_tokens(self, entry: MemoryEntry) -> int:
        """Estimate token count for an entry."""
        import json
        content = f"{entry.key}: {json.dumps(entry.value) if isinstance(entry.value, (dict, list)) else str(entry.value)}"
        # Rough estimate: 1 token ≈ 4 characters
        return len(content) // 4 + 50  # +50 for metadata overhead
    
    def _estimate_importance(self, entry: MemoryEntry) -> float:
        """
        Estimate importance of a new entry.
        Heuristic-based for MVP; RL-based in Phase 2.
        """
        importance = 0.5  # Base
        
        # Verification increases importance
        if entry.is_verified:
            importance += 0.2
        
        # Source matters
        source_weights = {
            "tool_call": 0.7,
            "code_change": 0.8,
            "user_input": 0.6,
            "decision": 0.9,
            "constraint": 0.85,
        }
        importance += source_weights.get(entry.source, 0.3)
        
        return min(1.0, importance)
    
    def _trace(self, event_type: str, metadata: Dict[str, Any]) -> None:
        """Add an event to the trace log."""
        if not self.config.tracing_enabled:
            return
        
        self._trace_log.append({
            "timestamp": time.time(),
            "event": event_type,
            "metadata": metadata,
        })
    
    def _build_result(
        self,
        status: str,
        entry: MemoryEntry,
        verification: Optional[VerificationResult] = None,
        agm_result: Optional[AGMResult] = None,
    ) -> Dict[str, Any]:
        """Build a standardized result dict."""
        return {
            "status": status,
            "key": entry.key,
            "entry_id": entry.id,
            "memory_type": entry.memory_type.value,
            "verified": entry.is_verified,
            "verification": verification.to_dict() if verification else None,
            "agm": agm_result.audit_log if agm_result else None,
            "importance": entry.importance,
            "confidence": entry.current_strength,
        }
