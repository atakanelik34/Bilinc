"""Bilinc: Verifiable State Plane for Autonomous Agents — v0.4.0"""
from bilinc.core.stateplane import StatePlane
from bilinc.core.working_memory import WorkingMemory
from bilinc.core.audit import AuditTrail, OpType
from bilinc.core.verifier import StateVerifier, VerificationResult
from bilinc.core.dual_process import System1Engine, System2Engine, Arbiter
from bilinc.core.confidence import ConfidenceEstimator, ConfidenceScore
from bilinc.core.models import MemoryType, MemoryEntry, BeliefState, CCSDimension
from bilinc.core.knowledge_graph import KnowledgeGraph, NodeType, EdgeType

__version__ = "1.0.0a1"
__all__ = [
    "StatePlane", "WorkingMemory", "AuditTrail", "OpType",
    "StateVerifier", "VerificationResult", "System1Engine", "System2Engine",
    "Arbiter", "ConfidenceEstimator", "ConfidenceScore",
    "MemoryType", "MemoryEntry", "BeliefState", "CCSDimension",
    "KnowledgeGraph", "NodeType", "EdgeType",
]
