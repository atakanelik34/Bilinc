"""Core components: StatePlane, AGM Belief Revision, Verification Gate."""
from synaptic_state.core.stateplane import StatePlane
from synaptic_state.core.agm import AGMEngine, BeliefState
from synaptic_state.core.verification import VerificationGate, VerificationResult

__all__ = ["StatePlane", "AGMEngine", "BeliefState", "VerificationGate", "VerificationResult"]
