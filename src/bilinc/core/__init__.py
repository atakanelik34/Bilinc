"""Core: StatePlane, WorkingMemory, Confidence, Arbiter, Verifier, Audit.

Lazy imports — heavy deps (z3, networkx) only load when accessed.
"""
__all__ = [
    "StatePlane", "WorkingMemory",
    "ConfidenceEstimator", "ConfidenceScore", "System1Engine", "System2Engine",
    "Arbiter", "StateVerifier", "VerificationResult", "AuditTrail", "OpType",
    "MemoryType", "MemoryEntry", "BeliefState", "CCSDimension",
    # Temporal reasoning (Fix #16)
    "TemporalRelation", "classify_temporal_query", "temporal_relation",
    "format_duration", "temporal_boost", "sort_by_temporal", "find_temporal_context",
    # KG-enhanced retrieval (Fix #17)
    "KGSpreadingActivation", "ActivationResult", "kg_enhanced_recall",
    # Vector search (Fix #7)
    "VectorStore", "HybridSearch",
]

# Lazy imports for all core classes
_IMPORTS = {
    "StatePlane": "bilinc.core.stateplane",
    "WorkingMemory": "bilinc.core.working_memory",
    "ConfidenceEstimator": "bilinc.core.confidence",
    "ConfidenceScore": "bilinc.core.confidence",
    "System1Engine": "bilinc.core.dual_process",
    "System2Engine": "bilinc.core.dual_process",
    "Arbiter": "bilinc.core.dual_process",
    "StateVerifier": "bilinc.core.verifier",
    "VerificationResult": "bilinc.core.verifier",
    "AuditTrail": "bilinc.core.audit",
    "OpType": "bilinc.core.audit",
    # Temporal
    "TemporalRelation": "bilinc.core.temporal",
    "classify_temporal_query": "bilinc.core.temporal",
    "temporal_relation": "bilinc.core.temporal",
    "format_duration": "bilinc.core.temporal",
    "temporal_boost": "bilinc.core.temporal",
    "sort_by_temporal": "bilinc.core.temporal",
    "find_temporal_context": "bilinc.core.temporal",
    # KG retrieval
    "KGSpreadingActivation": "bilinc.core.kg_retrieval",
    "ActivationResult": "bilinc.core.kg_retrieval",
    "kg_enhanced_recall": "bilinc.core.kg_retrieval",
    # Vector search
    "VectorStore": "bilinc.core.vector_search",
    "HybridSearch": "bilinc.core.vector_search",
}
# Models are lightweight, always import
from bilinc.core.models import MemoryType, MemoryEntry, BeliefState, CCSDimension


def __getattr__(name: str):
    """Lazy attribute access for heavy imports."""
    if name in _IMPORTS:
        import importlib
        mod = importlib.import_module(_IMPORTS[name])
        return getattr(mod, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
