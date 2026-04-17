"""Bilinc: Verifiable State Plane for Autonomous Agents — v1.2.0"""

# Lazy imports — avoid heavy deps (z3, networkx) at package level
__all__ = [
    "StatePlane", "WorkingMemory", "AuditTrail", "OpType",
    "StateVerifier", "VerificationResult", "System1Engine", "System2Engine",
    "Arbiter", "ConfidenceEstimator", "ConfidenceScore",
    "MemoryType", "MemoryEntry", "BeliefState", "CCSDimension",
    "KnowledgeGraph", "NodeType", "EdgeType",
]

__version__ = "1.2.0"


def __getattr__(name: str):
    """Lazy attribute access for heavy imports."""
    _lazy = {
        "StatePlane": "bilinc.core.stateplane",
        "WorkingMemory": "bilinc.core.working_memory",
        "AuditTrail": "bilinc.core.audit",
        "OpType": "bilinc.core.audit",
        "StateVerifier": "bilinc.core.verifier",
        "VerificationResult": "bilinc.core.verifier",
        "System1Engine": "bilinc.core.dual_process",
        "System2Engine": "bilinc.core.dual_process",
        "Arbiter": "bilinc.core.dual_process",
        "ConfidenceEstimator": "bilinc.core.confidence",
        "ConfidenceScore": "bilinc.core.confidence",
        "MemoryType": "bilinc.core.models",
        "MemoryEntry": "bilinc.core.models",
        "BeliefState": "bilinc.core.models",
        "CCSDimension": "bilinc.core.models",
        "KnowledgeGraph": "bilinc.core.knowledge_graph",
        "NodeType": "bilinc.core.knowledge_graph",
        "EdgeType": "bilinc.core.knowledge_graph",
    }
    if name in _lazy:
        import importlib
        mod = importlib.import_module(_lazy[name])
        return getattr(mod, name)
    raise AttributeError(f"module 'bilinc' has no attribute '{name}'")
