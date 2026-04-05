"""
SynapticAI: Verifiable State Plane for Autonomous Agents

Remember less. Stay correct longer.
Neuro-Symbolic Memory That Learns What to Forget.
"""

__version__ = "0.1.0"
__author__ = "SynapticAI Team"
__license__ = "MIT"

from synaptic_state.core.stateplane import StatePlane
from synaptic_state.core.agm import AGMEngine, BeliefState
from synaptic_state.core.verification import VerificationGate, VerificationResult
from synaptic_state.adaptive.forgetting import LearnableForgetting
from synaptic_state.retrieval.hybrid import HybridRetriever
from synaptic_state.adaptive.budget import ContextBudgetRL

__all__ = [
    "StatePlane",
    "AGMEngine",
    "BeliefState", 
    "VerificationGate",
    "VerificationResult",
    "LearnableForgetting",
    "HybridRetriever",
    "ContextBudgetRL",
]
