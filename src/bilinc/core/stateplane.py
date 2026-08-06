"""
StatePlane: Context-Independent Typed State Storage — Phase 2 (v0.2.0)

Integrates:
- 5 brain-mimetic memory types
- SQLite + PostgreSQL backends
- Working memory buffer (8 slots)
- Sleep consolidation engine
- System 1/2 dual process
- Z3 SMT verification
- Cryptographic audit trail (Merkle chain)
- State diff + rollback API
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import json
import time
from typing import Any, Dict, List, Optional
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.event_ledger import EventOperation
from bilinc.core.working_memory import WorkingMemory
from bilinc.core.confidence import ConfidenceEstimator
from bilinc.core.dual_process import System1Engine, System2Engine, Arbiter
from bilinc.core.verifier import StateVerifier
from bilinc.core.audit import AuditTrail, OpType
from bilinc.core.decay import compute_new_strength, should_prune
from bilinc.core.temporal import (
    classify_temporal_query,
    entry_event_timestamp,
    parse_temporal_timestamp,
    temporal_query_constraints,
)
from bilinc.observability.metrics import MetricsCollector
from bilinc.observability.health import HealthCheck
from bilinc.observability.logging import log_event


logger = logging.getLogger(__name__)


class PersistenceWriteError(RuntimeError):
    """Raised when a logical memory operation cannot be durably persisted."""


class StatePlane:
    """Phase 2: Full brain-inspired agent memory with verification."""
    AUTO_RECALL_IMPORTANCE_THRESHOLD = 0.7
    AUTO_RECALL_ACCESS_COUNT_THRESHOLD = 3
    AUTO_RECALL_MAX_SLOTS = 5
    AUTO_CONSOLIDATE_CAPACITY_THRESHOLD = 0.8
    AUTO_CONSOLIDATE_HEAT_THRESHOLD = 0.7
    AUTO_CONSOLIDATE_MIN_HOT_ENTRIES = 1
    SESSION_SUMMARY_MIN_EPISODES = 6
    SESSION_SUMMARY_MIN_TOKENS = 120
    SESSION_SUMMARY_MAX_HIGHLIGHTS = 5
    INTELLIGENT_RECALL_RRF_K = 60
    INTELLIGENT_RECALL_LEXICAL_WEIGHT = 0.25
    INTELLIGENT_RECALL_HYBRID_WEIGHT = 0.55
    # Entity continuity is a tie-breaker, not a replacement for lexical or
    # hybrid evidence. Inferred episodic entities can be frequent participant
    # names, so keep their RRF and direct contributions deliberately small.
    INTELLIGENT_RECALL_ENTITY_WEIGHT = 0.05
    # Directional temporal evidence is deliberately small: it resolves ties
    # among otherwise relevant memories without allowing chronology to outrank
    # lexical, hybrid, semantic, or entity relevance.
    INTELLIGENT_RECALL_TEMPORAL_WEIGHT = 0.1
    # Explicitly enabled local semantic retrieval is a small additive signal;
    # the default path remains unchanged when no semantic model is configured.
    INTELLIGENT_RECALL_SEMANTIC_WEIGHT = 0.05
    # Optional semantic gating prevents an embedding-only signal from
    # perturbing queries that already have strong lexical coverage.  It is
    # enabled only by an explicit deployment flag and is otherwise inert.
    INTELLIGENT_RECALL_ADAPTIVE_SEMANTIC_WEIGHT = 0.12
    INTELLIGENT_RECALL_SEMANTIC_LEXICAL_COVERAGE_THRESHOLD = 0.5
    # Graph continuity can recover a memory that does not mention the query
    # entity directly, but only through a bounded bridge path. Keep this a
    # small secondary signal so graph expansion cannot swamp lexical/current
    # evidence or common conversational participants.
    GRAPH_ENTITY_MAX_SEEDS = 8
    GRAPH_ENTITY_MAX_BRIDGE_ENTITIES = 8
    GRAPH_ENTITY_MAX_NEIGHBORS_PER_BRIDGE = 32
    GRAPH_ENTITY_BRIDGE_WEIGHT = 0.06
    # Function words are useful for query intent, but they are weak lexical
    # evidence for memory relevance. Keep this filter scoped to lexical
    # ranking so temporal/current-state intent and entity extraction retain
    # the complete query token stream.
    LEXICAL_QUERY_STOPWORDS = frozenset(
        {
            "a",
            "an",
            "and",
            "also",
            "as",
            "at",
            "about",
            "be",
            "been",
            "being",
            "but",
            "by",
            "can",
            "could",
            "did",
            "do",
            "does",
            "for",
            "from",
            "had",
            "has",
            "have",
            "he",
            "her",
            "his",
            "how",
            "i",
            "if",
            "in",
            "is",
            "it",
            "its",
            "may",
            "might",
            "of",
            "on",
            "or",
            "our",
            "she",
            "than",
            "that",
            "the",
            "their",
            "them",
            "then",
            "these",
            "they",
            "this",
            "those",
            "to",
            "was",
            "we",
            "were",
            "what",
            "when",
            "where",
            "which",
            "who",
            "why",
            "will",
            "with",
            "would",
            "you",
            "your",
        }
    )
    REFLECTION_DEFAULT_THRESHOLD = 0.55
    REFLECTION_MAX_PASSES = 3
    RECALL_EXPLAIN_SENSITIVE_KEYS = {
        "token",
        "secret",
        "password",
        "api_key",
        "apikey",
        "authorization",
        "bearer",
        "credential",
        "private",
    }
    RECALL_EXPLAIN_FIELD_REDACT_KEYS = {"source", "session_id", "provenance_id"}
    RECALL_EXPLAIN_SECRET_PATTERN = re.compile(
        r"(?i)(bearer\s+[a-z0-9._-]{12,}|sk-[a-z0-9_-]{20,}|pypi-[a-z0-9_-]{20,}|bil_live_[a-z0-9_-]{12,}|secret-token|token-[a-z0-9_-]{3,})"
    )
    
    def __init__(self, backend=None, working_memory=None, max_working_slots=8,
                 enable_verification=False, enable_audit=False):
        self.backend = backend
        self.working_memory = working_memory or WorkingMemory(max_slots=max_working_slots)
        self.estimator = ConfidenceEstimator()
        self.s1 = System1Engine(state_plane=self)
        self.s2 = System2Engine(state_plane=self)
        self.arbiter = Arbiter(system1=self.s1, system2=self.s2, estimator=self.estimator)
        
        self.enable_verification = enable_verification
        self.enable_audit = enable_audit
        self.verifier = StateVerifier() if enable_verification else None
        self.audit = self._build_audit_trail() if enable_audit else None
        self._ops_count = 0

        # Observability (Phase 4)
        self.metrics = MetricsCollector()
        self.health = HealthCheck(state_plane=self)

    def _build_audit_trail(self) -> AuditTrail:
        """Bind the audit trail to the persistence layer when possible."""
        if self.backend and hasattr(self.backend, "audit_db_path"):
            return AuditTrail(db_path=self.backend.audit_db_path)
        return AuditTrail()

    @staticmethod
    def _entry_to_state(entry: MemoryEntry) -> Dict[str, Any]:
        return entry.to_dict()

    @staticmethod
    def _coerce_audit_state_entry(key: str, raw_state: Any) -> MemoryEntry:
        """
        Convert an audit state payload into a MemoryEntry.
        Raises ValueError for malformed/legacy payloads that are not reconstructable.
        """
        if not isinstance(raw_state, dict):
            raise ValueError(f"invalid audit payload for key '{key}': expected object")
        state = dict(raw_state)
        state.setdefault("key", key)
        if "memory_type" not in state:
            raise ValueError(f"invalid audit payload for key '{key}': missing memory_type")
        return MemoryEntry.from_dict(state)

    async def _restore_backend_entry(self, entry: MemoryEntry) -> bool:
        if self.backend and hasattr(self.backend, "restore"):
            return await self.backend.restore(entry)
        return await self.backend.save(entry)

    async def _persistent_state(self) -> Dict[str, Dict[str, Any]]:
        if not self.backend:
            return {}
        entries = await self.backend.list_all()
        return {entry.key: self._entry_to_state(entry) for entry in entries}

    def _backend_name(self) -> str:
        if self.backend is None:
            return "in_memory"
        name = self.backend.__class__.__name__
        return name[:-7].lower() if name.endswith("Backend") else name.lower()

    def _apply_entry_verification(self, entry: MemoryEntry) -> MemoryEntry:
        """Apply the current verification policy to an entry in-place."""
        if not self.enable_verification or not self.verifier or entry.value is None:
            return entry

        entries_data = [{
            "key": entry.key,
            "value": entry.value,
            "memory_type": entry.memory_type.value,
            "importance": entry.importance,
            "is_verified": False,
            "current_strength": entry.current_strength,
            "verification_score": 0.0,
        }]
        results = self.verifier.verify_state(entries_data)
        failed = [r for r in results if not r.valid]
        if failed:
            entry.is_verified = False
            entry.verification_score = 0.0
            entry.verification_method = ""
            entry.metadata["verification_failed"] = [r.rule_name for r in failed]
        else:
            entry.is_verified = True
            entry.verification_score = 0.8
            entry.verification_method = "state_verifier"
            entry.metadata.pop("verification_failed", None)
        return entry

    def _record_success(self, operation: str, start_time: float, **fields: Any) -> None:
        elapsed = (time.perf_counter() - start_time) * 1000
        self.metrics.record_operation(operation, elapsed)
        self.health.update_gauge_on_metrics(self.metrics)
        log_event(
            logger,
            "info",
            "stateplane_operation",
            operation=operation,
            status="success",
            backend=self._backend_name(),
            latency_ms=round(elapsed, 3),
            **fields,
        )

    def _record_failure(self, operation: str, start_time: float, error: Exception, **fields: Any) -> None:
        elapsed = (time.perf_counter() - start_time) * 1000
        self.metrics.increment("backend_errors_total")
        self.metrics.increment(f"{operation}_failures_total")
        self.metrics.record_latency(f"{operation}_latency_ms", elapsed)
        try:
            self.health.update_gauge_on_metrics(self.metrics)
        except Exception as health_exc:
            log_event(
                logger,
                "warning",
                "health_update_failed",
                operation=operation,
                error_type=type(health_exc).__name__,
                error=str(health_exc),
            )
        log_event(
            logger,
            "error",
            "stateplane_operation",
            operation=operation,
            status="failed",
            backend=self._backend_name(),
            latency_ms=round(elapsed, 3),
            error_type=type(error).__name__,
            error=str(error),
            **fields,
        )
    
    async def init(self):
        """Initialize persistent backend. Required only when using SQLite/PostgreSQL."""
        start_time = time.perf_counter()
        try:
            if self.backend:
                await self.backend.init()
                await self._hydrate_working_memory_from_backend()
                await self._auto_recall_semantic_to_working()
            if self.enable_audit and self.audit:
                await self.audit.init()
            self._record_success("init", start_time)
        except Exception as exc:
            self._record_failure("init", start_time, exc)
            raise

    async def _hydrate_working_memory_from_backend(self) -> None:
        """Restore persisted working memory entries into the in-process buffer."""
        if not self.backend:
            return
        entries = await self.backend.load_by_type(MemoryType.WORKING, limit=self.working_memory.max_slots)
        for entry in entries:
            if self.working_memory.count >= self.working_memory.max_slots:
                break
            if self.working_memory.get(entry.key):
                continue
            self.working_memory.put(entry)

    async def _auto_recall_semantic_to_working(self) -> int:
        """
        Warm up working memory from high-signal semantic memories.
        Rule: importance > 0.7 AND access_count > 3, capped at 5 slots.
        """
        if not self.backend or self.working_memory.count >= self.working_memory.max_slots:
            return 0

        semantic_entries = await self.backend.load_by_type(MemoryType.SEMANTIC, limit=200)
        candidates = [
            entry for entry in semantic_entries
            if entry.importance > self.AUTO_RECALL_IMPORTANCE_THRESHOLD
            and entry.access_count > self.AUTO_RECALL_ACCESS_COUNT_THRESHOLD
        ]
        candidates = sorted(
            candidates,
            key=lambda e: (e.importance, e.last_accessed, e.access_count),
            reverse=True,
        )

        loaded = 0
        slots_available = self.working_memory.max_slots - self.working_memory.count
        max_to_load = min(self.AUTO_RECALL_MAX_SLOTS, slots_available)
        for entry in candidates[:max_to_load]:
            if self.working_memory.get(entry.key):
                continue
            self.working_memory.put(entry)
            loaded += 1
        return loaded
    
    async def commit(self, key: str, value: Any, memory_type: MemoryType = MemoryType.EPISODIC,
                     verify: bool = False, importance: float = 1.0, metadata: Optional[Dict[str, Any]] = None) -> MemoryEntry:
        start_time = time.perf_counter()
        entry = MemoryEntry(key=key, value=value, memory_type=memory_type,
                           importance=importance, metadata=metadata or {})
        entry.decay_rate = memory_type.default_decay_rate
        previous_entry = None

        try:
            # Verification pre-check
            self._apply_entry_verification(entry)

            # Store entry
            if memory_type == MemoryType.WORKING:
                previous_entry = self.working_memory.get(key)
                evicted = self.working_memory.put(entry)
                if self.backend:
                    saved = await self.backend.save(entry)
                    if not saved:
                        raise PersistenceWriteError(
                            f"persistence_write_failed: backend save returned false for key '{key}'"
                        )
                if evicted and self.backend:
                    evicted.memory_type = MemoryType.SEMANTIC
                    saved = await self.backend.save(evicted)
                    if not saved:
                        raise PersistenceWriteError(
                            f"persistence_write_failed: backend save returned false for evicted key '{evicted.key}'"
                        )
                    if self.enable_audit and self.audit:
                        self.audit.log(OpType.CONSOLIDATE, evicted.key,
                                       before_value=evicted.to_dict(), metadata={"auto_evicted": True})
                    await self._append_memory_event(
                        operation=EventOperation.CONSOLIDATE.value,
                        subject=evicted.key,
                        memory_key=evicted.key,
                        memory_type=evicted.memory_type.value if hasattr(evicted.memory_type, "value") else str(evicted.memory_type),
                        after_value=evicted.to_dict(),
                        payload_json={"auto_evicted": True},
                    )
                if self._should_auto_consolidate_working():
                    await self.consolidate()
            else:
                if self.backend:
                    previous_entry = await self.backend.load(key)
                    saved = await self.backend.save(entry)
                    if not saved:
                        raise PersistenceWriteError(
                            f"persistence_write_failed: backend save returned false for key '{key}'"
                        )

            # Audit log
            if self.enable_audit and self.audit:
                op_type = OpType.UPDATE if previous_entry else OpType.CREATE
                self.audit.log(
                    op_type,
                    key,
                    before_value=previous_entry.to_dict() if previous_entry else None,
                    after_value=entry.to_dict(),
                )

            self._ops_count += 1
            await self._project_claims_for_entry(entry)
            await self._project_entities_for_entry(entry)
            ledger_operation = EventOperation.REVISE.value if previous_entry else EventOperation.COMMIT.value
            await self._append_memory_event(
                operation=ledger_operation,
                subject=key,
                memory_key=key,
                memory_type=memory_type.value if hasattr(memory_type, "value") else str(memory_type),
                before_value=previous_entry.to_dict() if previous_entry else None,
                after_value=entry.to_dict(),
                payload_json={
                    "metadata": entry.metadata,
                    "source": entry.source,
                    "session_id": entry.session_id,
                    "request_id": (entry.metadata or {}).get("request_id") if isinstance(entry.metadata, dict) else None,
                },
            )
            self._record_success(
                "commit",
                start_time,
                key=key,
                memory_type=memory_type.value if hasattr(memory_type, "value") else str(memory_type),
            )
            return entry
        except Exception as exc:
            self._record_failure(
                "commit",
                start_time,
                exc,
                key=key,
                memory_type=memory_type.value if hasattr(memory_type, "value") else str(memory_type),
            )
            raise
    
    def commit_sync(self, key, value, memory_type=MemoryType.EPISODIC,
                    verify=False, importance=1.0, metadata=None):
        """Synchronous wrapper for commit with input validation."""
        from bilinc.security.validator import InputValidator
        from bilinc.security.resource_limits import ResourceLimits
        
        # 1. Validate Input
        key = InputValidator.validate_key(key)
        value = InputValidator.validate_value(value)
        
        # 2. Check Resource Limits
        if memory_type == MemoryType.WORKING:
            if hasattr(self, 'working_memory'):
                if not ResourceLimits.check_entry_capacity(memory_type, self.working_memory.count):
                    raise ValueError("Working memory is full.")

        # 3. Execute
        effective_memory_type = memory_type
        if self.backend is None and memory_type != MemoryType.WORKING:
            effective_memory_type = MemoryType.WORKING
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.commit(key, value, effective_memory_type, verify, importance, metadata)
            )
        raise RuntimeError(
            "commit_sync cannot be used while an event loop is running; use `await commit(...)` instead."
        )
    
    def recall_all_sync(self):
        """Synchronous recall of all entries from working memory. For in-memory/test use."""
        return self.working_memory.get_all()

    async def _append_memory_event(self, **kwargs) -> None:
        """Best-effort semantic event ledger append; never breaks existing runtime operations."""
        if not self.backend or not hasattr(self.backend, "append_memory_event"):
            return
        try:
            await self.backend.append_memory_event(**kwargs)
        except Exception:
            logger.debug("memory event ledger append failed", exc_info=True)

    async def _record_eval_capture(
        self,
        *,
        tool_name: str,
        query: str,
        results: List[Any],
        started_at: float,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Best-effort opt-in retrieval capture. Never breaks recall."""
        if not self.backend or not hasattr(self.backend, "record_eval_candidate"):
            return
        try:
            from bilinc.eval.capture import capture_enabled, row_from_results

            if not capture_enabled():
                return
            if getattr(self, "_suppress_eval_capture", False):
                return
            row = row_from_results(
                tool_name=tool_name,
                query=query,
                results=results,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
                detail=detail,
            )
            await self.backend.record_eval_candidate(row)
        except Exception:
            logger.debug("eval capture failed", exc_info=True)

    async def _project_claims_for_entry(self, entry: MemoryEntry) -> None:
        """Best-effort deterministic claim projection. Never breaks commit."""
        if not self.backend or not hasattr(self.backend, "save_claim"):
            return
        try:
            from bilinc.core.claims import extract_claims_from_entry

            claims = extract_claims_from_entry(entry)
            keep_ids = [claim.id for claim in claims]
            for claim in claims:
                await self.backend.save_claim(claim)
            if hasattr(self.backend, "deactivate_claims_for_memory_key"):
                await self.backend.deactivate_claims_for_memory_key(entry.key, keep_ids=keep_ids)
        except Exception:
            logger.debug("claim projection failed", exc_info=True)

    async def _project_entities_for_entry(self, entry: MemoryEntry) -> None:
        """Best-effort deterministic entity/backlink projection. Never breaks commit."""
        if not self.backend or not hasattr(self.backend, "save_entity"):
            return
        try:
            from bilinc.core.entities import Entity, entity_from_raw, extract_entities_from_entry

            if hasattr(self.backend, "delete_entity_mentions_for_memory_key"):
                await self.backend.delete_entity_mentions_for_memory_key(entry.key)

            mentions = extract_entities_from_entry(entry)
            metadata_entities = entry.metadata.get("entities", []) if isinstance(entry.metadata, dict) else []
            raw_entities = metadata_entities if isinstance(metadata_entities, list) else [metadata_entities]
            explicit_by_id = {}
            for raw_entity in raw_entities:
                entity = entity_from_raw(raw_entity)
                if entity:
                    explicit_by_id[entity.id] = entity

            for mention in mentions:
                entity = explicit_by_id.get(mention.entity_id) or Entity(canonical_name=mention.mention_text)
                await self.backend.save_entity(entity)
                await self.backend.save_entity_mention(mention)
        except Exception:
            logger.debug("entity projection failed", exc_info=True)

    async def recall(self, key: Optional[str] = None, memory_type: Optional[MemoryType] = None, limit: int = 50) -> List[MemoryEntry]:
        start_time = time.perf_counter()
        try:
            results = []
            if key:
                wm = self.working_memory.get(key)
                if wm:
                    results.append(wm)
            if self.backend:
                if key and not results:
                    p = await self.backend.load(key)
                    if p:
                        results.append(p)
                elif memory_type:
                    results.extend(await self.backend.load_by_type(memory_type, limit=limit))
            self._ops_count += 1
            self._record_success(
                "recall",
                start_time,
                key=key,
                memory_type=memory_type.value if hasattr(memory_type, "value") else memory_type,
                result_count=len(results),
            )
            await self._record_eval_capture(
                tool_name="recall",
                query=key or (memory_type.value if hasattr(memory_type, "value") else str(memory_type or "")),
                results=results,
                started_at=start_time,
                detail={"key": key, "memory_type": memory_type.value if hasattr(memory_type, "value") else memory_type, "limit": limit},
            )
            return results
        except Exception as exc:
            self._record_failure(
                "recall",
                start_time,
                exc,
                key=key,
                memory_type=memory_type.value if hasattr(memory_type, "value") else memory_type,
            )
            raise
    
    async def recall_all_working(self):
        return self.working_memory.get_all()

    async def preview_graph_projection(
        self,
        memory_types: Optional[List[MemoryType]] = None,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        """Read-only graph projection preview over backend or working memory entries."""
        from bilinc.core.graph_doctor import preview_projection

        limit = max(0, int(limit))
        source = "backend" if self.backend else "working_memory"
        if self.backend:
            candidates = await self._collect_recall_candidates(
                memory_types=memory_types,
                include_stale=True,
            )
            entries = list(candidates.values())[:limit]
        else:
            allowed_types = None
            if memory_types:
                allowed_types = {
                    mt.value if hasattr(mt, "value") else str(mt)
                    for mt in memory_types
                }
            entries = []
            for entry in self.working_memory.get_all():
                if allowed_types and entry.memory_type.value not in allowed_types:
                    continue
                entries.append(entry)
                if len(entries) >= limit:
                    break

        preview = preview_projection(entries)
        preview["read_only"] = True
        preview["source"] = source
        return preview

    async def recall_intelligent(
        self,
        query: str,
        limit: int = 10,
        memory_types: Optional[List[MemoryType]] = None,
        explain: bool = False,
        include_stale: bool = False,
        query_timestamp: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Multi-path retrieval with lightweight fusion:
        lexical (FTS/token overlap) + hybrid (FTS/vector rerank) + entity overlap.

        Current-state entries are the default retrieval surface. Historical or
        expired entries can be requested explicitly for audit and timeline
        workflows with ``include_stale=True``.
        """
        start_time = time.perf_counter()
        try:
            query = (query or "").strip()
            if not query or limit <= 0:
                return []

            valid_as_of = parse_temporal_timestamp(query_timestamp)
            candidates = await self._collect_recall_candidates(
                memory_types=memory_types,
                include_stale=include_stale or valid_as_of is not None,
            )
            candidates = self._filter_candidates_as_of(candidates, query_timestamp)
            if not candidates:
                return []

            lexical_ranked = self._rank_lexical_keys(query, candidates)
            candidate_keys = set(candidates)
            hybrid_ranked = self._rank_hybrid_keys(
                query,
                top_k=max(limit * 3, 10),
                candidate_keys=candidate_keys,
            )
            semantic_ranked = self._rank_semantic_keys(
                query,
                top_k=max(limit * 10, 50),
                candidate_keys=candidate_keys,
            )
            semantic_weight = self._semantic_recall_weight(
                query,
                candidates,
                lexical_ranked,
            )
            temporal_ranked = self._rank_temporal_keys(
                query,
                candidates,
                candidate_keys=set(lexical_ranked[: max(limit * 10, 50)])
                | set(hybrid_ranked[: max(limit * 10, 50)]),
            )
            bridge_protected_keys = (
                set(lexical_ranked[:limit])
                | set(hybrid_ranked[:limit])
                | set(semantic_ranked[:limit])
            )
            entity_boosts = self._compute_entity_boosts(
                query,
                candidates,
                bridge_protected_keys=bridge_protected_keys,
            )
            entity_ranked = [
                key for key, score in sorted(entity_boosts.items(), key=lambda kv: kv[1], reverse=True) if score > 0
            ]

            fused_scores: Dict[str, float] = {}
            signals: Dict[str, Dict[str, float]] = {}
            self._apply_rrf_signal(
                fused_scores,
                signals,
                lexical_ranked,
                weight=self.INTELLIGENT_RECALL_LEXICAL_WEIGHT,
                signal_name="lexical",
            )
            self._apply_rrf_signal(
                fused_scores,
                signals,
                hybrid_ranked,
                weight=self.INTELLIGENT_RECALL_HYBRID_WEIGHT,
                signal_name="hybrid",
            )
            self._apply_rrf_signal(
                fused_scores,
                signals,
                semantic_ranked,
                weight=semantic_weight,
                signal_name="semantic",
            )
            self._apply_rrf_signal(
                fused_scores,
                signals,
                temporal_ranked,
                weight=self.INTELLIGENT_RECALL_TEMPORAL_WEIGHT,
                signal_name="temporal",
            )
            self._apply_rrf_signal(
                fused_scores,
                signals,
                entity_ranked,
                weight=self.INTELLIGENT_RECALL_ENTITY_WEIGHT,
                signal_name="entity_rrf",
            )

            # Entity overlap acts as an additional direct relevance signal.
            for key, boost in entity_boosts.items():
                if boost <= 0:
                    continue
                fused_scores[key] = fused_scores.get(key, 0.0) + (0.02 * boost)
                bucket = signals.setdefault(
                    key,
                    {
                        "lexical": 0.0,
                        "hybrid": 0.0,
                        "semantic": 0.0,
                        "temporal": 0.0,
                        "entity": 0.0,
                        "entity_rrf": 0.0,
                    },
                )
                bucket["entity"] = boost

            self._apply_current_state_boost(query, fused_scores, candidates)
            ranked_keys = [k for k, _ in sorted(fused_scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]]
            claims_by_key = await self._active_claims_by_memory_key(ranked_keys) if explain else {}
            results = []
            for key in ranked_keys:
                entry = candidates.get(key)
                if not entry:
                    continue
                entry_signals = signals.get(
                    key,
                    {
                        "lexical": 0.0,
                        "hybrid": 0.0,
                        "semantic": 0.0,
                        "temporal": 0.0,
                        "entity": 0.0,
                        "entity_rrf": 0.0,
                    },
                )
                result = {
                    "key": entry.key,
                    "value": entry.value,
                    "memory_type": entry.memory_type.value,
                    "importance": entry.importance,
                    "score": round(fused_scores.get(key, 0.0), 6),
                    "signals": {
                        "lexical": round(entry_signals.get("lexical", 0.0), 6),
                        "hybrid": round(entry_signals.get("hybrid", 0.0), 6),
                        "semantic": round(entry_signals.get("semantic", 0.0), 6),
                        "temporal": round(entry_signals.get("temporal", 0.0), 6),
                        "entity": round(entry_signals.get("entity", 0.0), 6),
                    },
                }
                if explain:
                    result.update(
                        self._recall_explain_envelope(
                            query=query,
                            entry=entry,
                            score=fused_scores.get(key, 0.0),
                            signals=entry_signals,
                            supporting_claims=claims_by_key.get(key, []),
                        )
                    )
                results.append(result)

            self._record_success(
                "recall_intelligent",
                start_time,
                query_len=len(query),
                result_count=len(results),
            )
            return results
        except Exception as exc:
            self._record_failure("recall_intelligent", start_time, exc, query_len=len(query or ""))
            raise

    def resolve_recall_profile(self, profile: Optional[str] = None) -> Dict[str, Any]:
        """Resolve named recall quality/cost/safety profiles without changing defaults."""
        profiles: Dict[str, Dict[str, Any]] = {
            "fast": {
                "name": "fast",
                "max_reflections": 0,
                "adequacy_threshold": 0.0,
                "include_claims": False,
                "include_contradictions": False,
            },
            "balanced": {
                "name": "balanced",
                "max_reflections": 2,
                "adequacy_threshold": 0.55,
                "include_claims": False,
                "include_contradictions": False,
            },
            "verified": {
                "name": "verified",
                "max_reflections": 2,
                "adequacy_threshold": 0.7,
                "include_claims": True,
                "include_contradictions": True,
            },
            "deep": {
                "name": "deep",
                "max_reflections": 4,
                "adequacy_threshold": 0.75,
                "include_claims": True,
                "include_contradictions": True,
            },
        }
        name = (profile or "balanced").strip().lower()
        if name not in profiles:
            raise ValueError(f"unknown recall profile: {profile}")
        return dict(profiles[name])

    async def recall_profiled(
        self,
        query: str,
        profile: Optional[str] = None,
        limit: int = 10,
        memory_types: Optional[List[MemoryType]] = None,
        max_reflections: Optional[int] = None,
        adequacy_threshold: Optional[float] = None,
        explain: bool = False,
        query_timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run recall with a named profile and attach optional read-only evidence metadata."""
        resolved = self.resolve_recall_profile(profile)
        if max_reflections is not None:
            resolved["max_reflections"] = max(0, int(max_reflections))
        if adequacy_threshold is not None:
            resolved["adequacy_threshold"] = max(0.0, min(1.0, float(adequacy_threshold)))
        payload = await self.recall_reflective(
            query,
            limit=limit,
            max_reflections=resolved["max_reflections"],
            adequacy_threshold=resolved["adequacy_threshold"],
            memory_types=memory_types,
            explain=explain,
            query_timestamp=query_timestamp,
        )
        payload["profile"] = resolved["name"]
        payload["recall_profile"] = resolved
        payload["read_only"] = True
        if resolved.get("include_claims"):
            payload["evidence"] = await self._recall_profile_evidence(payload.get("results", []), resolved)
        return payload

    async def _recall_profile_evidence(self, results: List[Dict[str, Any]], profile: Dict[str, Any]) -> Dict[str, Any]:
        evidence: Dict[str, Any] = {"claims": [], "contradictions": {"count": 0, "findings": []}}
        if not self.backend or not hasattr(self.backend, "list_claims"):
            return evidence
        keys = {str(item.get("key")) for item in results if isinstance(item, dict) and item.get("key") is not None}
        claims = await self.backend.list_claims(active=True, limit=1000)
        selected = [claim for claim in claims if claim.memory_key in keys]
        evidence["claims"] = [claim.to_dict() for claim in selected]
        if profile.get("include_contradictions") and selected:
            from bilinc.eval.contradictions import ContradictionReport, detect_claim_contradictions

            findings = detect_claim_contradictions(selected)
            evidence["contradictions"] = ContradictionReport.from_findings(findings).to_dict()
        return evidence

    async def _active_claims_by_memory_key(self, memory_keys: List[str]) -> Dict[str, List[Any]]:
        """Return active claims grouped by memory key without mutating backend state."""
        if not self.backend or not hasattr(self.backend, "list_claims"):
            return {}
        wanted = {str(key) for key in memory_keys}
        if not wanted:
            return {}
        try:
            if hasattr(self.backend, "list_claims_for_memory_keys"):
                claims = await self.backend.list_claims_for_memory_keys(sorted(wanted), active=True)
            else:
                claims = await self.backend.list_claims(active=True, limit=max(1000, len(wanted) * 100))
        except Exception:
            return {}
        grouped: Dict[str, List[Any]] = {}
        for claim in claims:
            if claim.memory_key in wanted:
                grouped.setdefault(claim.memory_key, []).append(claim)
        return grouped

    def _recall_explain_envelope(
        self,
        query: str,
        entry: MemoryEntry,
        score: float,
        signals: Dict[str, float],
        supporting_claims: List[Any],
    ) -> Dict[str, Any]:
        return {
            "why_retrieved": self._why_retrieved(query, entry, score, signals),
            "provenance": self._recall_provenance(entry),
            "risk_flags": self._recall_risk_flags(entry),
            "supporting_claims": [self._safe_claim_dict(claim) for claim in supporting_claims],
        }

    def _why_retrieved(
        self,
        query: str,
        entry: MemoryEntry,
        score: float,
        signals: Dict[str, float],
    ) -> List[str]:
        reasons: List[str] = []
        tokens = set(self._tokenize_query(query))
        text = f"{entry.key} {entry.value}".lower()
        matching_tokens = sorted(token for token in tokens if token and token in text)
        if signals.get("lexical", 0.0) > 0:
            token_note = f" ({', '.join(matching_tokens[:5])})" if matching_tokens else ""
            reasons.append(f"lexical match{token_note}")
        if signals.get("hybrid", 0.0) > 0:
            reasons.append("hybrid/vector rerank match")
        if signals.get("semantic", 0.0) > 0:
            reasons.append("semantic embedding match")
        if signals.get("temporal", 0.0) > 0:
            reasons.append("directional temporal evidence")
        if signals.get("entity", 0.0) > 0:
            reasons.append("entity overlap match")
        if entry.importance >= 0.8:
            reasons.append(f"high importance {entry.importance:.2f}")
        if isinstance(entry.metadata, dict) and entry.metadata.get("canonical"):
            reasons.append("canonical memory")
        if not reasons:
            reasons.append(f"fused recall score {score:.6f}")
        return reasons

    def _recall_provenance(self, entry: MemoryEntry) -> Dict[str, Any]:
        metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
        provenance: Dict[str, Any] = {
            "memory_key": entry.key,
            "memory_type": entry.memory_type.value,
            "source": self._redact_recall_explain_value(entry.source, key_hint="source"),
            "session_id": self._redact_recall_explain_value(entry.session_id, key_hint="session_id"),
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "valid_at": entry.valid_at,
            "invalid_at": entry.invalid_at,
            "ttl": entry.ttl,
            "is_verified": entry.is_verified,
            "verification_score": entry.verification_score,
            "verification_method": entry.verification_method,
            "current_strength": entry.current_strength,
            "access_count": entry.access_count,
        }
        for field in ("source_hash", "provenance_id", "authority", "sensitivity"):
            if field in metadata:
                provenance[field] = self._redact_recall_explain_value(metadata[field], key_hint=field)
        return provenance

    def _recall_risk_flags(self, entry: MemoryEntry) -> List[str]:
        flags: List[str] = []
        now = time.time()
        metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
        if entry.current_strength < 0.25:
            flags.append("low_strength")
        if not entry.is_verified:
            flags.append("unverified")
        if entry.invalid_at is not None:
            try:
                flags.append("expired" if float(entry.invalid_at) <= now else "stale_possible")
            except (TypeError, ValueError):
                flags.append("stale_possible")
        if entry.ttl is not None:
            try:
                if entry.created_at + float(entry.ttl) <= now:
                    flags.append("expired")
            except (TypeError, ValueError):
                flags.append("stale_possible")
        sensitivity = str(metadata.get("sensitivity") or metadata.get("classification") or "").lower()
        if sensitivity in {"internal", "private", "secret", "confidential"}:
            flags.append("sensitive_metadata")
        if metadata.get("private") or metadata.get("secret"):
            flags.append("sensitive_metadata")
        deduped: List[str] = []
        for flag in flags:
            if flag not in deduped:
                deduped.append(flag)
        return deduped

    def _safe_claim_dict(self, claim: Any) -> Dict[str, Any]:
        return {
            "id": claim.id,
            "memory_key": claim.memory_key,
            "holder": claim.holder,
            "subject": claim.subject,
            "claim": claim.claim,
            "kind": claim.kind.value if hasattr(claim.kind, "value") else str(claim.kind),
            "confidence": claim.confidence,
            "source": self._redact_recall_explain_value(claim.source, key_hint="source"),
            "provenance_id": self._redact_recall_explain_value(claim.provenance_id, key_hint="provenance_id"),
            "valid_at": claim.valid_at,
            "invalid_at": claim.invalid_at,
            "active": claim.active,
        }

    def _redact_recall_explain_value(self, value: Any, *, key_hint: str = "") -> Any:
        key_l = key_hint.lower()
        if key_l in self.RECALL_EXPLAIN_FIELD_REDACT_KEYS and value not in (None, ""):
            return "[REDACTED]"
        if any(sensitive in key_l for sensitive in self.RECALL_EXPLAIN_SENSITIVE_KEYS):
            return "[REDACTED]"
        if isinstance(value, str):
            return self.RECALL_EXPLAIN_SECRET_PATTERN.sub("[REDACTED]", value)
        if isinstance(value, list):
            return [self._redact_recall_explain_value(item, key_hint=key_hint) for item in value]
        if isinstance(value, tuple):
            return [self._redact_recall_explain_value(item, key_hint=key_hint) for item in value]
        if isinstance(value, dict):
            return {str(k): self._redact_recall_explain_value(v, key_hint=str(k)) for k, v in value.items()}
        return value

    async def recall_reflective(
        self,
        query: str,
        limit: int = 10,
        max_reflections: int = 3,
        adequacy_threshold: float = 0.55,
        memory_types: Optional[List[MemoryType]] = None,
        explain: bool = False,
        query_timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Reflection loop:
        1) run intelligent recall
        2) evaluate adequacy
        3) if insufficient, expand query and retry (bounded)
        """
        start_time = time.perf_counter()
        try:
            current_query = (query or "").strip()
            max_reflections = max(0, int(max_reflections))
            adequacy_threshold = max(0.0, min(1.0, float(adequacy_threshold)))
            queries_tried = [current_query]
            reflections_used = 0

            results = await self.recall_intelligent(
                current_query,
                limit=limit,
                memory_types=memory_types,
                explain=explain,
                query_timestamp=query_timestamp,
            )
            adequacy = self._evaluate_recall_adequacy(current_query, results)

            while adequacy < adequacy_threshold and reflections_used < max_reflections:
                expanded_query = self._expand_reflection_query(current_query)
                if not expanded_query:
                    break
                if expanded_query == current_query:
                    expanded_query = f"{current_query} context"
                current_query = expanded_query
                queries_tried.append(current_query)
                reflections_used += 1

                next_results = await self.recall_intelligent(
                    current_query,
                    limit=limit,
                    memory_types=memory_types,
                    explain=explain,
                    query_timestamp=query_timestamp,
                )
                next_adequacy = self._evaluate_recall_adequacy(current_query, next_results)

                # Keep the best attempt seen so far.
                if next_adequacy >= adequacy:
                    results = next_results
                    adequacy = next_adequacy

            payload = {
                "query": query,
                "final_query": current_query,
                "adequacy": round(adequacy, 6),
                "adequacy_threshold": adequacy_threshold,
                "reflections_used": reflections_used,
                "max_reflections": max_reflections,
                "queries_tried": queries_tried,
                "results": results,
            }
            self._record_success(
                "recall_reflective",
                start_time,
                query_len=len(query or ""),
                result_count=len(results),
                reflections_used=reflections_used,
                adequacy=round(adequacy, 4),
            )
            return payload
        except Exception as exc:
            self._record_failure("recall_reflective", start_time, exc, query_len=len(query or ""))
            raise
    
    async def consolidate(self):
        if not self.backend:
            return 0
        ready = self.working_memory.gate_to_episodic()
        count = 0
        if ready:
            for e in ready:
                await self.backend.save(e)
                if self.enable_audit and self.audit:
                    self.audit.log(OpType.CONSOLIDATE, e.key,
                                   before_value={"type": "working"}, after_value=e.to_dict())
                count += 1
        await self.summarize_episodic_sessions()
        if count:
            await self._append_memory_event(
                operation=EventOperation.CONSOLIDATE.value,
                subject=f"consolidate:{int(time.time())}",
                payload_json={"consolidated_count": count, "memory_keys": [e.key for e in ready]},
            )
        return count

    async def apply_decay_pass(self, now: Optional[float] = None, prune: bool = True) -> Dict[str, int]:
        """
        Apply one global decay pass over persisted memories.

        Returns counters for scanned, updated, and pruned entries.
        """
        if not self.backend:
            return {"scanned": 0, "updated": 0, "pruned": 0}

        now = now or time.time()
        entries = await self.backend.list_all()
        scanned = 0
        updated = 0
        pruned = 0

        for entry in entries:
            scanned += 1
            last_touch = entry.last_accessed or entry.updated_at or entry.created_at
            elapsed_days = max(0.0, (now - last_touch) / 86400.0)
            if elapsed_days <= 0:
                continue

            new_strength, decay_meta = compute_new_strength(
                current_strength=entry.current_strength,
                memory_type=entry.memory_type.value,
                days_elapsed=elapsed_days,
                importance=entry.importance,
                verification_score=entry.verification_score,
                access_count=entry.access_count,
            )

            entry.current_strength = new_strength
            if not isinstance(entry.metadata, dict):
                entry.metadata = {}
            entry.metadata["decay"] = {
                "last_run": now,
                "factor": decay_meta.get("factor", 1.0),
                "phase": decay_meta.get("phase", "none"),
                "ltp": decay_meta.get("ltp", "none"),
            }
            entry.updated_at = now

            if prune and should_prune(new_strength, entry.memory_type.value):
                removed = await self.backend.delete(entry.key)
                if removed:
                    self.working_memory.remove(entry.key)
                    pruned += 1
                continue

            if hasattr(self.backend, "restore"):
                await self.backend.restore(entry)
            else:
                await self.backend.save(entry)
            updated += 1

        return {"scanned": scanned, "updated": updated, "pruned": pruned}

    async def run_kg_maintenance(self) -> Dict[str, int]:
        """
        Perform lightweight KG maintenance:
        - prune orphan nodes (degree == 0)
        - strengthen existing edges slightly.
        """
        if not hasattr(self, "knowledge_graph") or not self.knowledge_graph:
            return {"pruned_orphans": 0, "strengthened_edges": 0}

        kg = self.knowledge_graph
        orphan_nodes = [node for node in list(kg.graph.nodes()) if kg.graph.degree(node) == 0]
        for node_name in orphan_nodes:
            kg.remove_entity(node_name)

        strengthened = 0
        for source, target, edge_key, attrs in kg.graph.edges(keys=True, data=True):
            weight = float(attrs.get("weight", 1.0))
            new_weight = min(1.0, weight + 0.05)
            if new_weight != weight:
                kg.graph[source][target][edge_key]["weight"] = new_weight
                strengthened += 1
        for edge in kg._edges:
            edge.weight = min(1.0, edge.weight + 0.05)

        return {"pruned_orphans": len(orphan_nodes), "strengthened_edges": strengthened}

    async def run_entity_linking_backlog(self, limit: int = 500) -> Dict[str, int]:
        """
        Ingest semantic memories into KG when they are not yet entity-linked.
        """
        if not self.backend or not hasattr(self, "knowledge_graph") or not self.knowledge_graph:
            return {"processed": 0, "entities_created": 0, "relations_created": 0}

        semantic_entries = await self.backend.load_by_type(MemoryType.SEMANTIC, limit=limit)
        processed = 0
        entities_created = 0
        relations_created = 0

        for entry in semantic_entries:
            if self.knowledge_graph.memory_entities(entry.key):
                continue
            outcome = self.knowledge_graph.ingest_memory_entry(entry)
            processed += 1
            entities_created += int(outcome.get("entities_created", 0))
            relations_created += int(outcome.get("relations_created", 0))

        return {
            "processed": processed,
            "entities_created": entities_created,
            "relations_created": relations_created,
        }

    async def health_metrics_report(self) -> Dict[str, Any]:
        """Generate a compact health + metrics report payload."""
        readiness = self.health.readiness()
        liveness = self.health.liveness()
        self.health.update_gauges(self.metrics)
        stats = await self.stats()
        return {
            "timestamp": time.time(),
            "readiness": readiness.get("status"),
            "liveness": liveness.get("status"),
            "issues": readiness.get("issues", []),
            "ops_count": stats.get("ops_count", 0),
            "working_memory_usage": stats.get("working_memory", {}).get("capacity_usage", 0.0),
            "backend_total_entries": stats.get("backend", {}).get("total_entries", 0),
        }

    async def summarize_episodic_sessions(
        self,
        min_entries: Optional[int] = None,
        token_threshold: Optional[int] = None,
    ) -> List[MemoryEntry]:
        """
        Summarize episodic memories grouped by session into semantic memories.
        Triggered when group size or token budget threshold is reached.
        """
        if not self.backend:
            return []

        min_entries = int(min_entries or self.SESSION_SUMMARY_MIN_EPISODES)
        token_threshold = int(token_threshold or self.SESSION_SUMMARY_MIN_TOKENS)

        all_entries = await self.backend.list_all()
        episodic_entries = [
            e for e in all_entries
            if e.memory_type == MemoryType.EPISODIC
            and not (isinstance(e.metadata, dict) and e.metadata.get("is_session_summary"))
        ]
        if not episodic_entries:
            return []

        existing_summaries = {
            (e.metadata or {}).get("session_id")
            for e in all_entries
            if e.memory_type == MemoryType.SEMANTIC
            and isinstance(e.metadata, dict)
            and e.metadata.get("is_session_summary")
        }

        grouped: Dict[str, List[MemoryEntry]] = {}
        for entry in episodic_entries:
            session_id = entry.session_id or (entry.metadata or {}).get("session_id") or "__default__"
            grouped.setdefault(session_id, []).append(entry)

        created: List[MemoryEntry] = []
        now = time.time()
        for session_id, entries in grouped.items():
            if session_id in existing_summaries:
                continue

            total_tokens = sum(self._estimate_tokens(e.value) for e in entries)
            if len(entries) < min_entries and total_tokens < token_threshold:
                continue

            entries_sorted = sorted(entries, key=lambda e: (e.importance, e.created_at), reverse=True)
            highlights = self._build_session_highlights(entries_sorted[: self.SESSION_SUMMARY_MAX_HIGHLIGHTS])
            summary_payload = {
                "session_id": session_id,
                "entry_count": len(entries),
                "token_count": total_tokens,
                "highlights": highlights,
            }
            summary_entry = MemoryEntry(
                key=f"session_summary:{session_id}:{int(now)}",
                value=summary_payload,
                memory_type=MemoryType.SEMANTIC,
                source="auto_summarizer",
                session_id=session_id if session_id != "__default__" else "",
                importance=min(1.0, 0.5 + (0.05 * min(len(entries), 10))),
                metadata={
                    "is_session_summary": True,
                    "session_id": session_id,
                    "entry_count": len(entries),
                    "token_count": total_tokens,
                    "source_keys": [e.key for e in entries],
                    "generated_at": now,
                },
            )
            self._apply_entry_verification(summary_entry)
            saved = await self.backend.save(summary_entry)
            if not saved:
                raise PersistenceWriteError(
                    f"persistence_write_failed: backend save returned false for summary '{summary_entry.key}'"
                )
            created.append(summary_entry)

            if self.enable_audit and self.audit:
                self.audit.log(
                    OpType.CONSOLIDATE,
                    summary_entry.key,
                    before_value=None,
                    after_value=summary_entry.to_dict(),
                    metadata={"auto_summary": True, "session_id": session_id},
                )
        return created

    def _should_auto_consolidate_working(self) -> bool:
        """Trigger consolidation when working memory is both hot and near capacity."""
        if not self.backend:
            return False
        if self.working_memory.capacity_usage < self.AUTO_CONSOLIDATE_CAPACITY_THRESHOLD:
            return False
        hot_entries = self.working_memory.hot_entries(threshold=self.AUTO_CONSOLIDATE_HEAT_THRESHOLD)
        return len(hot_entries) >= self.AUTO_CONSOLIDATE_MIN_HOT_ENTRIES

    async def _collect_recall_candidates(
        self,
        memory_types: Optional[List[MemoryType]] = None,
        include_stale: bool = False,
    ) -> Dict[str, MemoryEntry]:
        allowed_types = None
        if memory_types:
            allowed_types = {
                mt.value if hasattr(mt, "value") else str(mt)
                for mt in memory_types
            }

        candidates: Dict[str, MemoryEntry] = {}
        for entry in self.working_memory.get_all():
            if allowed_types and entry.memory_type.value not in allowed_types:
                continue
            if not include_stale and not self._is_recallable_entry(entry):
                continue
            candidates[entry.key] = entry

        if self.backend:
            for entry in await self.backend.list_all():
                if allowed_types and entry.memory_type.value not in allowed_types:
                    continue
                if not include_stale and not self._is_recallable_entry(entry):
                    continue
                candidates[entry.key] = entry
        return candidates

    def _filter_candidates_as_of(
        self,
        candidates: Dict[str, MemoryEntry],
        query_timestamp: Optional[str],
    ) -> Dict[str, MemoryEntry]:
        """Apply explicit point-in-time visibility without changing default recall."""

        cutoff = parse_temporal_timestamp(query_timestamp)
        if cutoff is None:
            return candidates

        filtered: Dict[str, MemoryEntry] = {}
        for key, entry in candidates.items():
            event_timestamp = entry_event_timestamp(entry)
            if event_timestamp is not None and event_timestamp > cutoff:
                continue

            valid_at = parse_temporal_timestamp(entry.valid_at)
            if valid_at is not None and valid_at > cutoff:
                continue
            invalid_at = parse_temporal_timestamp(entry.invalid_at)
            if invalid_at is not None and invalid_at <= cutoff:
                continue
            created_at = parse_temporal_timestamp(entry.created_at)
            ttl = parse_temporal_timestamp(entry.ttl)
            if created_at is not None and ttl is not None and created_at + ttl <= cutoff:
                continue
            filtered[key] = entry
        return filtered

    def _is_recallable_entry(self, entry: MemoryEntry, now: Optional[float] = None) -> bool:
        """Return whether an entry belongs in the default current-state view."""
        now = time.time() if now is None else float(now)

        if entry.superseded_by:
            return False

        def _timestamp(value: Any) -> Optional[float]:
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        valid_at = _timestamp(entry.valid_at)
        if valid_at is not None and valid_at > now:
            return False

        invalid_at = _timestamp(entry.invalid_at)
        if invalid_at is not None and invalid_at <= now:
            return False

        ttl = _timestamp(entry.ttl)
        created_at = _timestamp(entry.created_at)
        if ttl is not None and created_at is not None and created_at + ttl <= now:
            return False

        return True

    def _tokenize_query(self, query: str) -> List[str]:
        return [token for token in re.findall(r"[a-zA-Z0-9_]+", query.lower()) if token]

    def _evaluate_recall_adequacy(self, query: str, results: List[Dict[str, Any]]) -> float:
        tokens = set(self._tokenize_query(query))
        if not tokens or not results:
            return 0.0
        coverage: set[str] = set()
        for result in results:
            text = f"{result.get('key', '')} {result.get('value', '')}".lower()
            for token in tokens:
                if token in text:
                    coverage.add(token)
        return len(coverage) / max(len(tokens), 1)

    def _expand_reflection_query(self, query: str) -> str:
        expansions = {
            "k8s": "kubernetes",
            "deploy": "deployment",
            "infra": "infrastructure",
            "db": "database",
            "svc": "service",
            "cfg": "configuration",
            "authn": "authentication",
            "authz": "authorization",
            "perf": "performance",
            "obs": "observability",
        }
        tokens = self._tokenize_query(query)
        expanded_tokens: List[str] = []
        for token in tokens:
            expanded_tokens.append(token)
            mapped = expansions.get(token)
            if mapped and mapped not in expanded_tokens:
                expanded_tokens.append(mapped)
        return " ".join(expanded_tokens)

    def _rank_lexical_keys(self, query: str, candidates: Dict[str, MemoryEntry]) -> List[str]:
        tokens = {
            token
            for token in self._tokenize_query(query)
            if token not in self.LEXICAL_QUERY_STOPWORDS
        }
        if not tokens:
            return []
        # Use corpus specificity as a bounded tie-breaker. Coverage remains
        # primary, while ubiquitous conversational words no longer decide the
        # order when several memories match the same number of query terms.
        document_frequency = {
            token: sum(
                1
                for entry in candidates.values()
                if token in f"{entry.key} {entry.value}".lower()
            )
            for token in tokens
        }
        corpus_size = len(candidates)
        scored: List[tuple[str, float]] = []
        for key, entry in candidates.items():
            text = f"{entry.key} {entry.value}".lower()
            matching_tokens = [token for token in tokens if token in text]
            if not matching_tokens:
                continue
            specificity = sum(
                math.log((corpus_size + 1) / (document_frequency[token] + 1))
                for token in matching_tokens
            )
            score = len(matching_tokens) + (specificity * 0.1) + (entry.importance * 0.1)
            scored.append((key, score))
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return [k for k, _ in scored]

    def _semantic_recall_weight(
        self,
        query: str,
        candidates: Dict[str, MemoryEntry],
        lexical_ranked: List[str],
    ) -> float:
        """Return the semantic RRF weight for an explicitly adaptive deployment.

        Strong lexical coverage is already a useful relevance signal, so
        semantic retrieval is gated off in that case.  With weak or absent
        lexical coverage, the semantic signal receives a bounded additive
        weight.  The environment flag keeps this experiment opt-in and
        preserves the existing default path byte-for-byte in behavior.
        """
        base_weight = self.INTELLIGENT_RECALL_SEMANTIC_WEIGHT
        enabled = os.environ.get("BILINC_SEMANTIC_ADAPTIVE_WEIGHT", "").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return base_weight

        tokens = set(self._tokenize_query(query))
        if not tokens or not lexical_ranked:
            return self.INTELLIGENT_RECALL_ADAPTIVE_SEMANTIC_WEIGHT

        probe_keys = lexical_ranked[: min(10, len(lexical_ranked))]
        best_coverage = 0.0
        for key in probe_keys:
            entry = candidates.get(key)
            if entry is None:
                continue
            text = f"{entry.key} {entry.value}".lower()
            coverage = sum(1 for token in tokens if token in text) / len(tokens)
            best_coverage = max(best_coverage, coverage)

        if best_coverage >= self.INTELLIGENT_RECALL_SEMANTIC_LEXICAL_COVERAGE_THRESHOLD:
            return 0.0
        return self.INTELLIGENT_RECALL_ADAPTIVE_SEMANTIC_WEIGHT

    def _rank_hybrid_keys(
        self,
        query: str,
        top_k: int,
        candidate_keys: Optional[set[str]] = None,
    ) -> List[str]:
        hybrid = self._get_hybrid_search()
        if hybrid is None:
            return []
        try:
            results = hybrid.search_with_reranking(
                query,
                top_k=top_k,
                allowed_keys=candidate_keys,
            )
            return [meta.get("key") for _, _, meta in results if meta.get("key")]
        except Exception:
            return []

    def _rank_semantic_keys(
        self,
        query: str,
        top_k: int,
        candidate_keys: Optional[set[str]] = None,
    ) -> List[str]:
        hybrid = self._get_hybrid_search()
        conn = self._sqlite_connection()
        if hybrid is None or conn is None:
            return []
        try:
            rowids = hybrid.semantic_search(
                query,
                top_k=top_k,
                allowed_keys=candidate_keys,
            )
            keys: List[str] = []
            for rowid, _score in rowids:
                row = conn.execute("SELECT key FROM memories WHERE rowid = ?", (rowid,)).fetchone()
                if row and row[0]:
                    keys.append(str(row[0]))
            return keys
        except Exception:
            return []

    def _rank_temporal_keys(
        self,
        query: str,
        candidates: Dict[str, MemoryEntry],
        candidate_keys: Optional[set[str]] = None,
    ) -> List[str]:
        """Rank relevant memories by explicit event time for directional queries.

        This is a bounded secondary signal. It only activates for queries that
        explicitly express an ordering direction (before/after/ordering), and
        it never substitutes ingestion time for an explicit source/event time.
        Queries such as ``when`` remain governed by lexical and hybrid
        relevance because they do not provide a direction to sort by.
        """
        query_type = classify_temporal_query(query)
        constraints = temporal_query_constraints(query)
        if query_type not in {"before", "after", "ordering"} and not constraints:
            return []

        allowed = set(candidates) if candidate_keys is None else set(candidate_keys)
        timestamped: List[tuple[str, float]] = []
        for key in allowed:
            entry = candidates.get(key)
            if entry is None:
                continue
            timestamp = entry_event_timestamp(entry)
            if timestamp is not None:
                timestamped.append((key, timestamp))
        if len(timestamped) < 2:
            return []

        # Explicit date constraints are a generic relevance signal: prefer
        # entries whose source event falls in the requested year/month/day.
        # Directional queries retain chronological ordering within each match
        # group. Stable key order makes equal timestamps deterministic across
        # SQLite/PostgreSQL backends.
        date_match_active = False
        if constraints:
            from datetime import datetime, timezone

            def match_rank(item: tuple[str, float]) -> tuple[int, float, str]:
                key, timestamp = item
                event = datetime.fromtimestamp(timestamp, timezone.utc)
                matches = 0
                if "year" in constraints:
                    matches += int(constraints["year"] == event.year)
                if "month" in constraints:
                    matches += int(constraints["month"] == event.month)
                if "day" in constraints:
                    matches += int(constraints["day"] == event.day)
                return matches, timestamp, key

            def matches_constraint(item: tuple[str, float]) -> bool:
                _key, timestamp = item
                event = datetime.fromtimestamp(timestamp, timezone.utc)
                return all(
                    getattr(event, field) == expected
                    for field, expected in constraints.items()
                )

            matched = [item for item in timestamped if matches_constraint(item)]
            if matched and len(matched) < len(timestamped):
                timestamped = matched
                date_match_active = True
            elif query_type not in {"before", "after", "ordering"}:
                # A year shared by every candidate is not a useful ranking
                # signal and should not perturb ordinary factual recall.
                return []

        reverse = query_type == "after"
        if date_match_active:
            timestamped.sort(
                key=lambda item: (
                    -match_rank(item)[0],
                    -item[1] if reverse else item[1],
                    item[0],
                )
            )
        else:
            timestamped.sort(key=lambda item: (item[1], item[0]), reverse=reverse)
        return [key for key, _timestamp in timestamped]

    def _apply_current_state_boost(
        self,
        query: str,
        fused_scores: Dict[str, float],
        candidates: Dict[str, MemoryEntry],
    ) -> None:
        """Prefer newer evidence when the query explicitly asks for current state."""
        query_tokens = set(self._tokenize_query(query))
        if "current" not in query_tokens:
            return

        timestamps = {
            key: max(float(entry.updated_at or 0.0), float(entry.created_at or 0.0))
            for key, entry in candidates.items()
            if key in fused_scores
        }
        if len(timestamps) < 2:
            return
        oldest = min(timestamps.values())
        newest = max(timestamps.values())
        span = newest - oldest

        def _timestamp(value: Any) -> Optional[float]:
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        for key, timestamp in timestamps.items():
            normalized_recency = (timestamp - oldest) / span if span > 0 else 0.0
            fused_scores[key] += 0.02 * normalized_recency

            entry = candidates[key]
            now = time.time()
            invalid_at = _timestamp(entry.invalid_at)
            created_at = _timestamp(entry.created_at) or 0.0
            ttl = _timestamp(entry.ttl)
            ttl_expired = ttl is not None and created_at + ttl <= now
            explicitly_stale = (
                entry.superseded_by is not None
                or (invalid_at is not None and float(invalid_at) <= now)
                or ttl_expired
            )
            valid_at = _timestamp(entry.valid_at)
            future_dated = valid_at is not None and valid_at > now
            if explicitly_stale or future_dated:
                fused_scores[key] -= 0.04

    def _compute_entity_boosts(
        self,
        query: str,
        candidates: Dict[str, MemoryEntry],
        bridge_protected_keys: Optional[set[str]] = None,
    ) -> Dict[str, float]:
        boosts: Dict[str, float] = {key: 0.0 for key in candidates}
        if hasattr(self, "knowledge_graph") and self.knowledge_graph:
            boosts.update(
                self._graph_entity_boosts(
                    query,
                    candidates,
                    bridge_protected_keys=bridge_protected_keys,
                )
            )

        # The graph is authoritative when initialized. The SQLite projection
        # is still used for deployments that do not keep an in-memory graph,
        # but applying both signals would double-count episodic entities.
        projection_boosts = {}
        if not (hasattr(self, "knowledge_graph") and self.knowledge_graph):
            projection_boosts = self._entity_projection_boosts(query, set(candidates.keys()))
        for memory_key, boost in projection_boosts.items():
            boosts[memory_key] = min(1.0, boosts.get(memory_key, 0.0) + boost)
        return boosts

    def _graph_entity_boosts(
        self,
        query: str,
        candidates: Dict[str, MemoryEntry],
        bridge_protected_keys: Optional[set[str]] = None,
    ) -> Dict[str, float]:
        """Score graph entities with bounded inverse-frequency weighting.

        Conversational turns often repeat participant names. Treating a
        ubiquitous participant as a strong relevance signal can swamp lexical
        and temporal evidence, so common entities contribute less while rare
        entities retain a bounded continuity signal.
        """
        graph = getattr(self, "knowledge_graph", None)
        if not graph or not candidates:
            return {}
        try:
            query_entities = {
                str(entity).casefold()
                for entity in graph._extract_entities_from_text(query)
                if str(entity).strip()
            }
        except Exception:
            return {}
        if not query_entities:
            return {}

        memory_entities: Dict[str, set[str]] = {}
        entity_frequency: Dict[str, int] = {}
        for key in candidates:
            try:
                entities = {
                    str(entity).casefold()
                    for entity in graph.memory_entities(key)
                    if str(entity).strip()
                }
            except Exception:
                entities = set()
            memory_entities[key] = entities
            for entity in entities & query_entities:
                entity_frequency[entity] = entity_frequency.get(entity, 0) + 1

        corpus_size = max(len(candidates), 1)
        denominator = math.log(corpus_size + 1.0)

        def inverse_frequency(entity: str) -> float:
            frequency = entity_frequency.get(entity, 0)
            if frequency <= 0:
                return 0.0
            if corpus_size < 20:
                return 1.0 if frequency <= 1 else 0.25
            if frequency >= corpus_size * 0.5:
                return 0.0
            return max(
                0.0,
                min(1.0, math.log((corpus_size + 1.0) / (frequency + 1.0)) / denominator),
            )

        boosts: Dict[str, float] = {}
        for key, entities in memory_entities.items():
            overlap = entities & query_entities
            if not overlap:
                continue
            boosts[key] = min(0.4, sum(0.2 * inverse_frequency(entity) for entity in overlap))

        if not getattr(self, "enable_graph_bridge_recall", False):
            return boosts

        # Bounded two-hop continuity: query entity -> seed memory -> shared
        # bridge entity -> candidate memory. This is intentionally derived
        # from the generic entity-memory index rather than benchmark text or
        # query-specific aliases. It lets a relation spread across multiple
        # memories remain retrievable without making every graph neighbor a
        # high-confidence hit.
        direct_seed_keys = [
            key for key, score in boosts.items() if score > 0
        ]
        direct_seed_keys.sort(key=lambda key: (-boosts[key], key))
        for seed_key in direct_seed_keys[: self.GRAPH_ENTITY_MAX_SEEDS]:
            seed_entities = memory_entities.get(seed_key, set())
            bridge_entities = sorted(seed_entities - query_entities)
            for bridge_entity in bridge_entities[: self.GRAPH_ENTITY_MAX_BRIDGE_ENTITIES]:
                linked_keys = graph.query_memories_by_entity(
                    bridge_entity,
                    limit=self.GRAPH_ENTITY_MAX_NEIGHBORS_PER_BRIDGE,
                )
                frequency = graph.entity_memory_count(bridge_entity)
                if frequency <= 0 or frequency >= corpus_size * 0.5:
                    continue
                bridge_specificity = max(
                    0.0,
                    min(
                        1.0,
                        math.log((corpus_size + 1.0) / (frequency + 1.0)) / denominator,
                    ),
                )
                if bridge_specificity <= 0:
                    continue
                for neighbor_key in linked_keys:
                    if neighbor_key == seed_key or neighbor_key not in candidates:
                        continue
                    if bridge_protected_keys and neighbor_key in bridge_protected_keys:
                        continue
                    neighbor_entities = memory_entities.get(neighbor_key, set())
                    if bridge_entity not in neighbor_entities:
                        continue
                    bridge_boost = self.GRAPH_ENTITY_BRIDGE_WEIGHT * bridge_specificity
                    boosts[neighbor_key] = min(
                        0.16,
                        boosts.get(neighbor_key, 0.0) + bridge_boost,
                    )
        return boosts

    def _entity_projection_boosts(self, query: str, candidate_keys: set[str]) -> Dict[str, float]:
        conn = self._sqlite_connection()
        if conn is None or not query.strip():
            return {}
        normalized_seeds = {" ".join(seed.lower().split()) for seed in self._entity_seed_phrases(query)}
        if not normalized_seeds:
            return {}
        boosts: Dict[str, float] = {}
        try:
            entity_rows = conn.execute("SELECT id, canonical_name, aliases FROM entities").fetchall()
        except Exception:
            return {}
        entity_ids: set[str] = set()
        for row in entity_rows:
            names = [row["canonical_name"]]
            try:
                names.extend(json.loads(row["aliases"] or "[]"))
            except Exception:
                pass
            normalized_names = {" ".join(str(name).lower().split()) for name in names if str(name).strip()}
            if normalized_names & normalized_seeds:
                entity_ids.add(row["id"])
        corpus_size = max(len(candidate_keys), 1)
        denominator = math.log(corpus_size + 1.0)
        for entity_id in sorted(entity_ids)[:5]:
            try:
                frequency_row = conn.execute(
                    "SELECT COUNT(DISTINCT memory_key) AS frequency FROM entity_mentions WHERE entity_id = ? AND source != ?",
                    (entity_id, "proper_noun_projection"),
                ).fetchone()
                frequency = int(frequency_row["frequency"] or 0) if frequency_row else 0
                if frequency <= 0:
                    continue
                if corpus_size < 20:
                    inverse_frequency = 1.0 if frequency <= 1 else 0.25
                else:
                    if frequency >= corpus_size * 0.5:
                        continue
                    inverse_frequency = max(
                        0.0,
                        min(1.0, math.log((corpus_size + 1.0) / (frequency + 1.0)) / denominator),
                    )
                rows = conn.execute(
                    "SELECT DISTINCT memory_key FROM entity_mentions WHERE entity_id = ? AND source != ? LIMIT 200",
                    (entity_id, "proper_noun_projection"),
                ).fetchall()
            except Exception:
                continue
            for row in rows:
                memory_key = row["memory_key"]
                if memory_key in candidate_keys:
                    boosts[memory_key] = min(
                        1.0,
                        boosts.get(memory_key, 0.0) + (0.6 * inverse_frequency),
                    )
        return boosts

    def _entity_seed_phrases(self, query: str) -> List[str]:
        query = (query or "").strip()
        if not query:
            return []
        phrases = [query]
        tokens = self._tokenize_query(query)
        phrases.extend(token for token in tokens if len(token) >= 3)
        seen = set()
        out: List[str] = []
        for phrase in phrases[:10]:
            key = phrase.lower()
            if key not in seen:
                seen.add(key)
                out.append(phrase)
        return out

    def _apply_rrf_signal(
        self,
        fused_scores: Dict[str, float],
        signals: Dict[str, Dict[str, float]],
        ranked_keys: List[str],
        weight: float,
        signal_name: str,
    ) -> None:
        for rank, key in enumerate(ranked_keys):
            contribution = weight / (self.INTELLIGENT_RECALL_RRF_K + rank + 1)
            fused_scores[key] = fused_scores.get(key, 0.0) + contribution
            bucket = signals.setdefault(
                key,
                {
                    "lexical": 0.0,
                    "hybrid": 0.0,
                    "semantic": 0.0,
                    "temporal": 0.0,
                    "entity": 0.0,
                    "entity_rrf": 0.0,
                },
            )
            bucket[signal_name] = bucket.get(signal_name, 0.0) + contribution

    def _sqlite_connection(self):
        if not self.backend:
            return None
        get_conn = getattr(self.backend, "_get_conn", None)
        if not callable(get_conn):
            return None
        try:
            return get_conn()
        except Exception:
            return None

    _cached_vector_store = None
    _cached_hybrid_search = None

    def _get_hybrid_search(self):
        """Lazy-cached HybridSearch instance to avoid re-creating on every call."""
        if self._cached_hybrid_search is not None:
            return self._cached_hybrid_search
        conn = self._sqlite_connection()
        if conn is None:
            return None
        try:
            from bilinc.core.vector_search import VectorStore, HybridSearch
            vs = VectorStore(conn)
            self._cached_vector_store = vs
            self._cached_hybrid_search = HybridSearch(conn, vs)
            return self._cached_hybrid_search
        except Exception:
            return None

    def _estimate_tokens(self, value: Any) -> int:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        tokens = re.findall(r"[a-zA-Z0-9_]+", text)
        return len(tokens)

    def _build_session_highlights(self, entries: List[MemoryEntry]) -> List[str]:
        highlights: List[str] = []
        for entry in entries:
            text = entry.value if isinstance(entry.value, str) else json.dumps(entry.value, ensure_ascii=False)
            compact = " ".join(text.split())
            if len(compact) > 180:
                compact = compact[:177] + "..."
            highlights.append(f"{entry.key}: {compact}")
        return highlights
    
    async def diff(self, timestamp_a: float, timestamp_b: float) -> Dict[str, Any]:
        """Return a reconstructable diff between two timestamps using the audit trail."""
        start_time = time.perf_counter()
        try:
            if not self.enable_audit or not self.audit:
                result = {
                    "timestamp_a": timestamp_a,
                    "timestamp_b": timestamp_b,
                    "added": [],
                    "modified": [],
                    "removed": [],
                    "counts": {"added": 0, "modified": 0, "removed": 0},
                }
                self._record_success("diff", start_time, added=0, modified=0, removed=0)
                return result

            state_a = self.audit.get_state_at(timestamp_a)
            state_b = self.audit.get_state_at(timestamp_b)
            all_keys = set(list(state_a.keys()) + list(state_b.keys()))
            added = [
                {"key": key, "after": state_b[key]}
                for key in sorted(all_keys) if key in state_b and key not in state_a
            ]
            removed = [
                {"key": key, "before": state_a[key]}
                for key in sorted(all_keys) if key in state_a and key not in state_b
            ]
            modified = [
                {"key": key, "before": state_a[key], "after": state_b[key]}
                for key in sorted(all_keys)
                if key in state_a and key in state_b and state_a[key] != state_b[key]
            ]

            result = {
                "timestamp_a": timestamp_a,
                "timestamp_b": timestamp_b,
                "added": added,
                "modified": modified,
                "removed": removed,
                "counts": {
                    "added": len(added),
                    "modified": len(modified),
                    "removed": len(removed),
                },
            }
            self._record_success(
                "diff",
                start_time,
                added=len(added),
                modified=len(modified),
                removed=len(removed),
            )
            return result
        except Exception as exc:
            self._record_failure("diff", start_time, exc)
            raise

    async def rollback(self, target_timestamp: float) -> Dict[str, Any]:
        """Restore persistent state to the exact state recorded at the target timestamp."""
        start_time = time.perf_counter()
        try:
            if not self.backend or not self.enable_audit or not self.audit:
                raise NotImplementedError("Rollback requires persistent storage with audit trail enabled.")

            target_state = self.audit.get_state_at(target_timestamp)
            current_state = await self._persistent_state()

            deleted_keys = []
            created_keys = []
            updated_keys = []

            for key in sorted(set(current_state.keys()) - set(target_state.keys())):

                existing = await self.backend.load(key)
                await self.backend.delete(key)
                self.working_memory.remove(key)
                if self.enable_audit and self.audit:
                    self.audit.log(
                        OpType.DELETE,
                        key,
                        before_value=existing.to_dict() if existing else current_state[key],
                        metadata={"rollback": True, "target_timestamp": target_timestamp},
                    )
                deleted_keys.append(key)

            for key, target_entry_dict in target_state.items():
                existing = await self.backend.load(key)
                if existing and existing.to_dict() == target_entry_dict:
                    continue

                restored_entry = self._coerce_audit_state_entry(key, target_entry_dict)
                await self._restore_backend_entry(restored_entry)
                if hasattr(self.backend, "delete_claims_for_memory_key"):
                    await self.backend.delete_claims_for_memory_key(key)
                if hasattr(self.backend, "delete_entity_mentions_for_memory_key"):
                    await self.backend.delete_entity_mentions_for_memory_key(key)
                await self._project_claims_for_entry(restored_entry)
                await self._project_entities_for_entry(restored_entry)
                self.working_memory.remove(key)

                if self.enable_audit and self.audit:
                    op_type = OpType.UPDATE if existing else OpType.CREATE
                    self.audit.log(
                        op_type,
                        key,
                        before_value=existing.to_dict() if existing else None,
                        after_value=restored_entry.to_dict(),
                        metadata={"rollback": True, "target_timestamp": target_timestamp},
                    )

                if existing:
                    updated_keys.append(key)
                else:
                    created_keys.append(key)

            if self.enable_audit and self.audit:
                self.audit.log(
                    OpType.ROLLBACK,
                    "__system",
                    before_value={"target_timestamp": target_timestamp},
                    after_value={
                        "created": created_keys,
                        "updated": updated_keys,
                        "deleted": deleted_keys,
                    },
                    metadata={"target_timestamp": target_timestamp},
                )

            result = {
                "target_timestamp": target_timestamp,
                "created": created_keys,
                "updated": updated_keys,
                "deleted": deleted_keys,
                "counts": {
                    "created": len(created_keys),
                    "updated": len(updated_keys),
                    "deleted": len(deleted_keys),
                },
            }
            self._record_success(
                "rollback",
                start_time,
                created=len(created_keys),
                updated=len(updated_keys),
                deleted=len(deleted_keys),
            )
            return result
        except Exception as exc:
            self._record_failure("rollback", start_time, exc, target_timestamp=target_timestamp)
            raise

    
    async def verify(self, key: str) -> Dict[str, Any]:
        """Full verification of a single entry + audit trail."""
        result = {"key": key, "exists": False, "audit_entries": [], "invariant_checks": []}
        
        # Load entry
        entry = await self.recall(key=key)
        if not entry:
            return result
        entry = entry[0] if entry else None
        if not entry:
            return result
        
        result["exists"] = True
        result["value"] = entry.to_dict()
        
        # Audit history
        if self.enable_audit:
            history = self.audit.get_history(key=key, limit=20)
            result["audit_entries"] = [
                {"op": h.op_type, "ts": h.timestamp, "root": h.root_hash}
                for h in history
            ]
        
        # Z3 invariant checks
        if self.enable_verification and self.verifier:
            checks = self.verifier.verify_state([entry.to_dict()])
            result["invariant_checks"] = [
                {"rule": c.rule_name, "valid": c.valid, "reason": c.reason}
                for c in checks
            ]
        
        result["root_hash"] = self.audit.get_root_hash() if self.enable_audit else None
        result["integrity_valid"] = True
        if self.enable_audit:
            integrity = self.audit.verify_integrity()
            result["integrity_valid"] = integrity["valid"]
        
        return result
    
    async def snapshot(self) -> Dict[str, Any]:
        """Create a verifiable snapshot of the current state."""
        start_time = time.perf_counter()
        try:
            total = 0
            by_type = {}
            entries = {}
            if self.backend:
                backend_stats = await self.backend.stats()
                total = backend_stats.get("total_entries", 0) or backend_stats.get("total", 0)
                by_type = backend_stats.get("by_type", {})
                entries = await self._persistent_state()

            result = {
                "timestamp": time.time(),
                "total_entries": total,
                "by_type": by_type,
                "entries": entries,
                "working_memory_count": self.working_memory.count,
                "root_hash": self.audit.get_root_hash() if self.enable_audit else None,
                "integrity": self.audit.verify_integrity() if self.enable_audit else None,
                "ops_count": self._ops_count,
            }
            await self._append_memory_event(
                operation=EventOperation.SNAPSHOT.value,
                subject=f"snapshot:{int(result['timestamp'])}",
                payload_json={"total_entries": total, "by_type": by_type, "ops_count": self._ops_count},
                checkpoint_root=result.get("root_hash"),
            )
            self._record_success("snapshot", start_time, total_entries=total)
            return result
        except Exception as exc:
            self._record_failure("snapshot", start_time, exc)
            raise
    
    def forget_sync(self, key):
        """Synchronous wrapper for forget."""
        import asyncio
        return asyncio.run(self.forget(key))

    async def forget(self, key: str) -> bool:
        start_time = time.perf_counter()
        try:
            wm_entry = self.working_memory.get(key)
            self.working_memory.remove(key)
            result = False
            existing = None
            if self.backend:
                existing = await self.backend.load(key)
                result = await self.backend.delete(key)
            if self.enable_audit:
                self.audit.log(
                    OpType.FORGET,
                    key,
                    before_value=existing.to_dict() if existing else (wm_entry.to_dict() if wm_entry else None),
                    metadata={"deleted": result},
                )
            await self._append_memory_event(
                operation=EventOperation.FORGET.value,
                subject=key,
                memory_key=key,
                memory_type=(existing.memory_type.value if existing and hasattr(existing.memory_type, "value") else None),
                before_value=existing.to_dict() if existing else (wm_entry.to_dict() if wm_entry else None),
                payload_json={"deleted": result},
            )
            self._record_success("forget", start_time, key=key, removed=result)
            return result
        except Exception as exc:
            self._record_failure("forget", start_time, exc, key=key)
            raise
    
    async def route_query(self, query, entries=None):
        """Route query through System 1/2 arbiter."""
        if entries is None:
            entries = await self.recall_all_working()
        return await self.arbiter.route(query, entries)
    
    async def stats(self):
        wm_stats = self.working_memory.stats()
        backend_stats = await self.backend.stats() if self.backend else {}
        audit_info = {}
        if self.enable_audit:
            audit_info = {
                "root_hash": self.audit.get_root_hash(),
                "integrity": self.audit.verify_integrity(),
            }
        health_readiness = self.health.readiness()
        return {
            "working_memory": wm_stats,
            "backend": backend_stats,
            "audit": audit_info,
            "ops_count": self._ops_count,
            "arbiter": self.arbiter.get_stats(),
            "health": {
                "status": health_readiness["status"],
                "issues": health_readiness["issues"],
            },
        }

    # ── Phase 3 Integrations ─────────────────────────────────
    # Added without modifying existing methods — purely additive.

    def init_agm(self, agm_engine=None):
        """Initialize AGM Belief Engine on this StatePlane."""
        from bilinc.adaptive.agm_engine import AGMEngine
        self.agm_engine = agm_engine or AGMEngine()
        return self.agm_engine

    def init_knowledge_graph(
        self,
        kg=None,
        materialize_cross_memory_links: bool = True,
        enable_graph_bridge_recall: bool = False,
    ):
        """Initialize Knowledge Graph on this StatePlane.

        The entity-memory index remains complete for retrieval. Materializing
        every co-occurrence edge is an optional graph-exploration surface and
        can be disabled explicitly for index-only deployments. The default
        keeps the existing cross-memory edge behavior for API compatibility;
        edge fan-out remains bounded by KnowledgeGraph's caps.
        """
        from bilinc.core.knowledge_graph import KnowledgeGraph
        if kg is None:
            link_limit = 64 if materialize_cross_memory_links else 0
            entry_limit = 128 if materialize_cross_memory_links else 0
            kg = KnowledgeGraph(
                max_cross_memory_links_per_entity=link_limit,
                max_cross_memory_links_per_entry=entry_limit,
            )
        self.knowledge_graph = kg
        self.enable_graph_bridge_recall = bool(enable_graph_bridge_recall)
        return self.knowledge_graph

    def init_belief_sync(self, sync_engine=None):
        """Initialize Multi-Agent Belief Sync on this StatePlane."""
        from bilinc.core.belief_sync import BeliefSyncEngine
        self.belief_sync = sync_engine or BeliefSyncEngine()
        return self.belief_sync

    def commit_with_agm(self, key: str, value: Any, memory_type: str = "semantic",
                        importance: float = 1.0, metadata: Optional[Dict[str, Any]] = None,
                        source: str = "", session_id: str = "", ttl: Optional[float] = None) -> Any:
        """
        Sync wrapper for commit_with_agm. Auto-detects event loop and delegates.
        """
        try:
            asyncio.get_running_loop()
            # We're in an async context - can't use asyncio.run
            # Return a placeholder; callers should use commit_with_agm_async directly
            return {"success": False, "error": "Use commit_with_agm_async in async context", "key": key}
        except RuntimeError:
            return asyncio.run(
                self.commit_with_agm_async(key, value, memory_type=memory_type,
                    importance=importance, metadata=metadata,
                    source=source, session_id=session_id, ttl=ttl)
            )

    async def commit_with_agm_async(self, key: str, value: Any, memory_type: str = "semantic",
                        importance: float = 1.0, metadata: Optional[Dict[str, Any]] = None,
                        source: str = "", session_id: str = "", ttl: Optional[float] = None) -> Any:
        """
        Async variant of commit_with_agm that keeps backend, verification, AGM,
        knowledge graph, and audit trail synchronized. Supports Hermes metadata.
        """
        try:
            entry = MemoryEntry(
                key=key,
                value=value,
                memory_type=MemoryType(memory_type) if isinstance(memory_type, str) else memory_type,
                importance=importance,
            )
            # Verification
            if hasattr(self, "_apply_entry_verification"):
                self._apply_entry_verification(entry)

            # Hermes metadata contract
            if metadata:
                entry.metadata.update(metadata)
            if source:
                entry.source = source
            if session_id:
                entry.session_id = session_id
            if ttl is not None:
                entry.ttl = float(ttl)
                entry.invalid_at = time.time() + float(ttl)

            if hasattr(self, "agm_engine") and self.agm_engine:
                result = self.agm_engine.revise(entry)

                previous_entry = await self.backend.load(key) if self.backend else None
                if self.backend and result.success:
                    saved = await self.backend.save(entry)
                    if not saved:
                        raise PersistenceWriteError(
                            f"persistence_write_failed: backend save returned false for key '{key}'"
                        )
                    await self._project_claims_for_entry(entry)
                    await self._project_entities_for_entry(entry)
                    await self._append_memory_event(
                        operation=EventOperation.REVISE.value if previous_entry else EventOperation.COMMIT.value,
                        subject=key,
                        memory_key=key,
                        memory_type=entry.memory_type.value if hasattr(entry.memory_type, "value") else str(entry.memory_type),
                        before_value=previous_entry.to_dict() if previous_entry else None,
                        after_value=entry.to_dict(),
                        payload_json={
                            "metadata": entry.metadata,
                            "source": entry.source,
                            "session_id": entry.session_id,
                            "agm_success": True,
                        },
                    )

                if self.enable_audit and self.audit and result.success:
                    self.audit.log(
                        OpType.UPDATE if previous_entry else OpType.CREATE,
                        key,
                        before_value=previous_entry.to_dict() if previous_entry else None,
                        after_value=entry.to_dict(),
                    )

                # Keep an explicitly enabled graph in sync even when the
                # belief revision result is the only state transition. Do it
                # after persistence so a failed write cannot leak a graph
                # projection that the backend does not contain.
                if result.success and hasattr(self, "knowledge_graph") and self.knowledge_graph:
                    self.knowledge_graph.ingest_memory_entry(entry)

                return result
            else:
                # Fallback mode
                if self.backend:
                    previous_entry = await self.backend.load(key)
                    saved = await self.backend.save(entry)
                    if not saved:
                        raise PersistenceWriteError(
                            f"persistence_write_failed: backend save returned false for key '{key}'"
                        )
                    await self._project_claims_for_entry(entry)
                    await self._project_entities_for_entry(entry)
                    await self._append_memory_event(
                        operation=EventOperation.REVISE.value if previous_entry else EventOperation.COMMIT.value,
                        subject=key,
                        memory_key=key,
                        memory_type=entry.memory_type.value if hasattr(entry.memory_type, "value") else str(entry.memory_type),
                        before_value=previous_entry.to_dict() if previous_entry else None,
                        after_value=entry.to_dict(),
                        payload_json={"metadata": entry.metadata, "source": entry.source, "session_id": entry.session_id},
                    )
                if hasattr(self, "knowledge_graph") and self.knowledge_graph:
                    self.knowledge_graph.ingest_memory_entry(entry)
                return entry
        except Exception:
            if hasattr(self, 'metrics') and self.metrics:
                self.metrics.increment("commit_with_agm_errors")
            raise

    def _persist_entry_sync(self, entry: MemoryEntry) -> bool:
        """Persist a MemoryEntry to backend if one exists."""
        if not self.backend:
            return False
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return False
            return loop.run_until_complete(self.backend.save(entry))
        except RuntimeError:
            return asyncio.run(self.backend.save(entry))

    def query_graph(self, entity: str, max_depth: int = 2) -> Dict[str, Any]:
        """Query the knowledge graph for an entity."""
        if hasattr(self, "knowledge_graph") and self.knowledge_graph:
            return self.knowledge_graph.traverse(entity, max_depth=max_depth)
        return {"nodes": [], "edges": [], "error": "Knowledge graph not initialized"}

    def get_contradictions(self) -> List[Dict[str, Any]]:
        """Get all contradictions from AGM + Knowledge Graph."""
        contradictions = []
        if hasattr(self, "knowledge_graph") and self.knowledge_graph:
            contradictions.extend(self.knowledge_graph.find_contradictions())
        return contradictions

    def phase3_stats(self) -> Dict[str, Any]:
        """Summary of all Phase 3 components."""
        stats = {"phase": 3}
        if hasattr(self, "agm_engine") and self.agm_engine:
            stats["agm"] = {
                "beliefs": len(self.agm_engine.belief_state.beliefs),
                "operations": len(self.agm_engine.operation_log),
                "entrenchment_count": len(self.agm_engine.entrenchment),
            }
        if hasattr(self, "knowledge_graph") and self.knowledge_graph:
            stats["knowledge_graph"] = self.knowledge_graph.stats
        if hasattr(self, "belief_sync") and self.belief_sync:
            stats["belief_sync"] = self.belief_sync.get_sync_stats()
        return stats
