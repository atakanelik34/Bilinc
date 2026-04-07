"""Core: StatePlane, WorkingMemory, Confidence, Arbiter, Verifier, Audit.

Lazy imports — heavy deps (z3, networkx) only load when accessed.
"""
__all__ = [
    "StatePlane", "WorkingMemory",
    "ConfidenceEstimator", "ConfidenceScore", "System1Engine", "System2Engine",
    "Arbiter", "StateVerifier", "VerificationResult", "AuditTrail", "OpType",
    "MemoryType", "MemoryEntry", "BeliefState", "CCSDimension",
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
