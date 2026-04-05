"""
ContextBudget RL: Adaptive Context Budget Allocation

Based on ContextBudget paper (arXiv:2604.01664):
- Formulates context management as a sequential decision problem
- Learns optimal compression strategies under varying budgets

For MVP: Heuristic-based allocation (Phase 2: actual RL)
"""

from __future__ import annotations

import time
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ContextBudgetRL:
    """
    Adaptive context budget optimizer.
    
    Allocates token budget across memory types based on:
    1. Task type (coding, analysis, conversation, etc.)
    2. History of what was most useful
    3. Current context constraints
    
    MVP: Rule-based allocation with learning hooks.
    Phase 2: Actual RL-trained policy network.
    """
    
    # Default allocation percentages by strategy
    ALLOCATION_PROFILES = {
        "greedy": {
            "episodic": 0.4,
            "procedural": 0.2,
            "semantic": 0.25,
            "symbolic": 0.15,
        },
        "rl_optimized": {
            "episodic": 0.3,
            "procedural": 0.3,
            "semantic": 0.25,
            "symbolic": 0.15,
        },
        "symbolic_heavy": {
            "episodic": 0.15,
            "procedural": 0.2,
            "semantic": 0.3,
            "symbolic": 0.35,
        },
        "conversation": {
            "episodic": 0.5,
            "procedural": 0.1,
            "semantic": 0.3,
            "symbolic": 0.1,
        },
    }
    
    def __init__(
        self,
        default_budget: int = 2048,
        max_budget: int = 8192,
        learning_rate: float = 0.01,
    ):
        self.default_budget = default_budget
        self.max_budget = max_budget
        self.learning_rate = learning_rate
        
        # Learning state (for Phase 2 RL)
        self._task_history: list = []
        self._allocation_history: list = []
        self._feedback_scores: list = []  # 0-1 scores post-task
    
    def allocate_budget(
        self,
        requested_budget: Optional[int] = None,
        strategy: str = "rl_optimized",
        task_type: str = "generic",
        available_types: Optional[Dict[str, int]] = None,
    ) -> Dict[str, int]:
        """
        Allocate token budget across memory types.
        
        Returns: {"episodic": N, "procedural": N, "semantic": N, "symbolic": N}
        """
        budget = min(
            requested_budget or self.default_budget,
            self.max_budget,
        )
        
        profile = self.ALLOCATION_PROFILES.get(strategy, self.ALLOCATION_PROFILES["rl_optimized"])
        
        # Apply task-type adjustments
        adjusted = self._adjust_for_task_type(profile, task_type)
        
        # Normalize
        total = sum(adjusted.values())
        if total > 0:
            allocation = {
                k: int(budget * v / total)
                for k, v in adjusted.items()
            }
        else:
            allocation = {k: budget // len(adjusted) for k in adjusted}
        
        # Log for learning
        self._allocation_history.append({
            "timestamp": time.time(),
            "budget": budget,
            "strategy": strategy,
            "task_type": task_type,
            "allocation": allocation,
        })
        
        # Apply available constraints
        if available_types:
            for mem_type, available_count in available_types.items():
                if mem_type in allocation and available_count == 0:
                    allocation[mem_type] = 0
        
        return allocation
    
    def record_feedback(self, task_type: str, score: float, allocation: Dict[str, int]) -> None:
        """
        Record task feedback for future learning.
        
        score: 0.0 (bad allocation) to 1.0 (perfect allocation)
        """
        self._feedback_scores.append({
            "timestamp": time.time(),
            "task_type": task_type,
            "score": score,
            "allocation": allocation,
        })
    
    def _adjust_for_task_type(self, profile: Dict[str, float], task_type: str) -> Dict[str, float]:
        """Adjust allocation ratios based on task type."""
        adjusted = dict(profile)
        
        adjustments = {
            "coding": {"procedural": 0.15, "symbolic": 0.1, "episodic": -0.1, "semantic": -0.05},
            "debug": {"episodic": 0.15, "procedural": 0.1, "symbolic": 0.0, "semantic": 0.0},
            "analysis": {"semantic": 0.15, "episodic": 0.05, "procedural": -0.05, "symbolic": -0.05},
            "conversation": {"episodic": 0.2, "semantic": 0.1, "procedural": -0.15, "symbolic": -0.05},
        }
        
        task_adjust = adjustments.get(task_type, {})
        for mem_type, delta in task_adjust.items():
            if mem_type in adjusted:
                adjusted[mem_type] = max(0.05, adjusted[mem_type] + delta)
        
        return adjusted
    
    def get_optimal_strategy(self, task_type: str = "generic") -> str:
        """
        Suggest optimal strategy based on historical feedback.
        
        For Phase 2: this will use learned RL policy.
        For MVP: simple heuristic.
        """
        if not self._feedback_scores:
            return "rl_optimized"
        
        # Find highest-scoring strategy for this task type
        task_feedback = [f for f in self._feedback_scores if f["task_type"] == task_type]
        if not task_feedback:
            return "rl_optimized"
        
        # Simple averaging
        avg_scores: Dict[str, float] = {}
        for fb in task_feedback:
            strategy = fb.get("allocation", {}).get("_strategy", "rl_optimized")
            if strategy not in avg_scores:
                avg_scores[strategy] = []
            avg_scores[strategy].append(fb["score"])
        
        if not avg_scores:
            return "rl_optimized"
        
        best_strategy = max(
            avg_scores.items(),
            key=lambda x: sum(x[1]) / len(x[1])
        )
        return best_strategy[0]
