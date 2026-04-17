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
import time, json
from typing import Any, Dict, List, Optional
from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.working_memory import WorkingMemory
from bilinc.core.confidence import ConfidenceEstimator
from bilinc.core.dual_process import System1Engine, System2Engine, Arbiter
from bilinc.core.verifier import StateVerifier, VerificationResult
from bilinc.core.audit import AuditTrail, OpType
from bilinc.storage.backend import StorageBackend
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
    
    async def consolidate(self):
        ready = self.working_memory.gate_to_episodic()
        count = 0
        if ready and self.backend:
            for e in ready:
                await self.backend.save(e)
                if self.enable_audit and self.audit:
                    self.audit.log(OpType.CONSOLIDATE, e.key,
                                   before_value={"type": "working"}, after_value=e.to_dict())
                count += 1
        return count
    
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

    def init_knowledge_graph(self, kg=None):
        """Initialize Knowledge Graph on this StatePlane."""
        from bilinc.core.knowledge_graph import KnowledgeGraph
        self.knowledge_graph = kg or KnowledgeGraph()
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
        start_time = time.perf_counter()
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
                if hasattr(self, "knowledge_graph") and self.knowledge_graph:
                    self.knowledge_graph.ingest_memory_entry(entry)

                previous_entry = await self.backend.load(key) if self.backend else None
                if self.backend and result.success:
                    saved = await self.backend.save(entry)
                    if not saved:
                        raise PersistenceWriteError(
                            f"persistence_write_failed: backend save returned false for key '{key}'"
                        )

                if self.enable_audit and self.audit and result.success:
                    self.audit.log(
                        OpType.UPDATE if previous_entry else OpType.CREATE,
                        key,
                        before_value=previous_entry.to_dict() if previous_entry else None,
                        after_value=entry.to_dict(),
                    )

                duration = time.perf_counter() - start_time
                return result
            else:
                # Fallback mode
                if self.backend:
                    saved = await self.backend.save(entry)
                    if not saved:
                        raise PersistenceWriteError(
                            f"persistence_write_failed: backend save returned false for key '{key}'"
                        )
                duration = time.perf_counter() - start_time
                return entry
        except Exception as exc:
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
