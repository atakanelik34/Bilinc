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


class StatePlane:
    """Phase 2: Full brain-inspired agent memory with verification."""
    
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
        self.audit = AuditTrail() if enable_audit else None
        self._ops_count = 0

        # Observability (Phase 5)
        self.metrics = MetricsCollector()
        self.health = HealthCheck(state_plane=self)
    
    async def init(self):
        """Initialize persistent backend. Required only when using SQLite/PostgreSQL."""
        if self.backend:
            await self.backend.init()
        if self.enable_audit and self.audit:
            await self.audit.init()
    
    async def commit(self, key, value, memory_type=MemoryType.EPISODIC,
                     verify=False, importance=1.0, metadata=None):
        entry = MemoryEntry(key=key, value=value, memory_type=memory_type,
                           importance=importance, metadata=metadata or {})
        entry.decay_rate = memory_type.default_decay_rate
        
        # Verification pre-check
        if self.enable_verification and self.verifier and entry.value is not None:
            entries_data = [{"key": key, "value": value, "memory_type": memory_type.value,
                           "importance": importance, "is_verified": False,
                           "current_strength": 1.0, "verification_score": 0.0}]
            results = self.verifier.verify_state(entries_data)
            failed = [r for r in results if not r.valid]
            if failed:
                entry.is_verified = False
                entry.verification_score = 0.0
                entry.metadata["verification_failed"] = [r.rule_name for r in failed]
            else:
                entry.is_verified = True
                entry.verification_score = 0.8
        
        # Store entry
        if memory_type == MemoryType.WORKING:
            evicted = self.working_memory.put(entry)
            if evicted and self.backend:
                await self.backend.save(evicted)
                if self.enable_audit and self.audit:
                    self.audit.log(OpType.CONSOLIDATE, evicted.key,
                                   before_value=evicted.to_dict(), metadata={"auto_evicted": True})
        else:
            if self.backend:
                await self.backend.save(entry)
        
        # Audit log
        if self.enable_audit and self.audit:
            self.audit.log(OpType.CREATE, key, after_value=entry.to_dict())
        
        self._ops_count += 1
        return entry
    
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
        import asyncio
        start_time = time.perf_counter()
        effective_memory_type = memory_type
        if self.backend is None and memory_type != MemoryType.WORKING:
            effective_memory_type = MemoryType.WORKING
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return self.commit(key, value, effective_memory_type, verify, importance, metadata)
            return loop.run_until_complete(
                self.commit(key, value, effective_memory_type, verify, importance, metadata)
            )
        except RuntimeError:
            return asyncio.run(
                self.commit(key, value, effective_memory_type, verify, importance, metadata)
            )
        finally:
            if hasattr(self, 'metrics'):
                elapsed = (time.perf_counter() - start_time) * 1000
                self.metrics.increment("commits_total")
                self.metrics.record_latency("commit_latency_ms", elapsed)
            if hasattr(self, 'health'):
                self.health.update_gauge_on_metrics(self.metrics)
    
    def recall_all_sync(self):
        """Synchronous recall of all entries from working memory. For in-memory/test use."""
        return self.working_memory.get_all()
    
    async def recall(self, key=None, memory_type=None, limit=50):
        results = []
        if key:
            wm = self.working_memory.get(key)
            if wm: results.append(wm)
        if self.backend:
            if key and not results:
                p = await self.backend.load(key)
                if p: results.append(p)
            elif memory_type:
                results.extend(await self.backend.load_by_type(memory_type, limit=limit))
        self._ops_count += 1
        return results
    
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
    
    async def diff(self, timestamp_a: float, timestamp_b: float) -> Dict[str, List[str]]:
        """Get diff between two timestamps using audit trail."""
        if not self.enable_audit or not self.audit:
            return {"added": [], "modified": [], "removed": []}
        
        history = self.audit.get_history(limit=1000)
        state_a = {}
        state_b = {}
        
        for entry in history:
            if entry.timestamp <= timestamp_a:
                if entry.op_type in ("create", "update"):
                    state_a[entry.key] = json.loads(entry.after_value) if entry.after_value else None
                elif entry.op_type == "delete":
                    state_a.pop(entry.key, None)
            if entry.timestamp <= timestamp_b:
                if entry.op_type in ("create", "update"):
                    state_b[entry.key] = json.loads(entry.after_value) if entry.after_value else None
                elif entry.op_type == "delete":
                    state_b.pop(entry.key, None)
        
        all_keys = set(list(state_a.keys()) + list(state_b.keys()))
        added = [k for k in all_keys if k in state_b and k not in state_a]
        removed = [k for k in all_keys if k in state_a and k not in state_b]
        modified = [k for k in all_keys if k in state_a and k in state_b and state_a[k] != state_b[k]]
        
        return {"added": added, "modified": modified, "removed": removed}
    
    async def rollback(self, target_timestamp: float) -> int:
        """Rollback state to a previous point in time."""
        if not self.enable_audit or not self.audit:
            return 0
        
        restored_state = self.audit.get_state_at(target_timestamp)
        restored_count = 0
        
        # Restore each key
        for key, state_info in restored_state.items():
            if state_info.get("restored"):
                continue
            if state_info.get("value") is not None and self.backend:
                existing = await self.backend.load(key)
                if existing:
                    existing.value = state_info["value"]
                    existing.updated_at = time.time()
                    await self.backend.save(existing)
                    restored_count += 1
        
        if self.enable_audit:
            self.audit.log(OpType.ROLLBACK, "__system",
                          before_value={"target": target_timestamp},
                          after_value={"restored_count": restored_count},
                          metadata={"restored_keys": list(restored_state.keys())})
        
        return restored_count
    
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
        """Create a verifiable state snapshot."""
        total = 0
        by_type = {}
        if self.backend:
            total = (await self.backend.stats()).get("total_entries", 0)
            by_type = (await self.backend.stats()).get("by_type", {})
        
        return {
            "timestamp": time.time(),
            "total_entries": total,
            "by_type": by_type,
            "working_memory_count": self.working_memory.count,
            "root_hash": self.audit.get_root_hash() if self.enable_audit else None,
            "integrity": self.audit.verify_integrity() if self.enable_audit else None,
            "ops_count": self._ops_count,
        }
    
    def forget_sync(self, key):
        """Synchronous wrapper for forget."""
        import asyncio
        return asyncio.run(self.forget(key))

    async def forget(self, key):
        self.working_memory.remove(key)
        result = False
        if self.backend:
            result = await self.backend.delete(key)
        if self.enable_audit:
            self.audit.log(OpType.FORGET, key, metadata={"deleted": result})
        return result
    
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
        return {
            "working_memory": wm_stats,
            "backend": backend_stats,
            "audit": audit_info,
            "ops_count": self._ops_count,
            "arbiter": self.arbiter.get_stats(),
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
                        importance: float = 1.0) -> Any:
        """
        Commit a memory entry and auto-apply AGM revision.
        If AGM engine is not initialized, falls back to basic storage.
        """
        entry = MemoryEntry(
            key=key, value=value, memory_type=MemoryType(memory_type),
            importance=importance,
        )
        if hasattr(self, "agm_engine") and self.agm_engine:
            result = self.agm_engine.revise(entry)
            # Also ingest into knowledge graph if available
            if hasattr(self, "knowledge_graph") and self.knowledge_graph:
                self.knowledge_graph.ingest_memory_entry(entry)
            return result
        # Fallback: no AGM — just return the entry
        return entry

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
