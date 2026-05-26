"""Bilinc: Verifiable agent brain runtime — v2.1.0"""

# Lazy imports — avoid heavy deps (z3, networkx) at package level
__all__ = [
    "StatePlane", "WorkingMemory", "AuditTrail", "OpType",
    "StateVerifier", "VerificationResult", "System1Engine", "System2Engine",
    "Arbiter", "ConfidenceEstimator", "ConfidenceScore",
    "MemoryType", "MemoryEntry", "BeliefState", "CCSDimension",
    "KnowledgeGraph", "NodeType", "EdgeType",
    "ContextAssembler", "CognitiveWorkspace", "BilincAgentRuntime",
    "LangGraphWorkspace", "ProjectRuntimeManager", "EvalReceipt",
]

__version__ = "2.1.0"


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
        "ContextAssembler": "bilinc.core.context_assembler",
        "CognitiveWorkspace": "bilinc.core.cognitive_workspace",
        "BilincAgentRuntime": "bilinc.integrations.agent_runtime",
        "LangGraphWorkspace": "bilinc.integrations.langgraph_workspace",
        "ProjectRuntimeManager": "bilinc.cloud.runtime",
        "EvalReceipt": "bilinc.eval.receipts",
    }
    if name in _lazy:
        import importlib
        mod = importlib.import_module(_lazy[name])
        return getattr(mod, name)
    raise AttributeError(f"module 'bilinc' has no attribute '{name}'")
