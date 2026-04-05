"""
ContextBudget RL Policy Network

Reinforcement learning policy for optimal context budget allocation.
Based on ContextBudget paper (arXiv:2604.01664):
- Formulates context management as sequential decision problem
- Curriculum-based RL under varying context budgets

Architecture:
- State: [task_type_embed, budget_remaining, memory_importance_dist, 
          confidence_scores, access_frequency, staleness_ratios]
- Action: Discrete allocation % for each memory type
- Reward: Task success rate + (1 - cost / budget) + recall_accuracy - drift_penalty

For MVP: Simple Q-learning policy.
Phase 2: Full PPO with transformer-based state encoding.
"""

from __future__ import annotations

import json
import time
import math
import random
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
from collections import deque

logger = logging.getLogger(__name__)

# ─── Memory Types (consistent with core) ───────────────────────
MEMORY_TYPES = ["episodic", "procedural", "semantic", "symbolic"]
N_TYPES = len(MEMORY_TYPES)

# ─── State Representation ───────────────────────────────────────
class BudgetState:
    """
    RL state vector for context budget allocation.
    
    Features (dim = 16):
    - Budget ratio (4 dims): fraction of budget allocated per type
    - Importance distribution (4 dims): avg importance per type
    - Confidence distribution (4 dims): avg confidence per type
    - Staleness ratios (4 dims): fraction of stale memories per type
    """
    DIM = 16
    
    def __init__(
        self,
        budget_ratios: List[float] = None,
        importance_dist: List[float] = None,
        confidence_dist: List[float] = None,
        staleness_ratios: List[float] = None,
    ):
        self.budget_ratios = budget_ratios or [0.25] * N_TYPES
        self.importance_dist = importance_dist or [0.5] * N_TYPES
        self.confidence_dist = confidence_dist or [0.5] * N_TYPES
        self.staleness_ratios = staleness_ratios or [0.0] * N_TYPES
    
    def to_vector(self) -> List[float]:
        return (
            self.budget_ratios +
            self.importance_dist +
            self.confidence_dist +
            self.staleness_ratios
        )
    
    @classmethod
    def from_vector(cls, vec: List[float]) -> "BudgetState":
        assert len(vec) >= cls.DIM
        return cls(
            budget_ratios=list(vec[0:4]),
            importance_dist=list(vec[4:8]),
            confidence_dist=list(vec[8:12]),
            staleness_ratios=list(vec[12:16]),
        )


# ─── Discrete Action Space ─────────────────────────────────────
class BudgetAction:
    """
    Discretized allocation action.
    
    5 discretization levels per type = 125 possible allocations.
    For each type: [10%, 20%, 30%, 40%, 50%] of total budget.
    Then normalized to sum=100%.
    """
    DISCRETIZATION = [0.1, 0.2, 0.3, 0.4, 0.5]
    N_LEVELS = len(DISCRETIZATION)
    TOTAL_ACTIONS = N_LEVELS ** N_TYPES  # 5^4 = 625
    
    @classmethod
    def decode(cls, action_idx: int) -> Dict[str, float]:
        """Convert action index to allocation ratios."""
        ratios = []
        idx = action_idx
        for _ in range(N_TYPES):
            level = idx % cls.N_LEVELS
            ratios.append(cls.DISCRETIZATION[level])
            idx //= cls.N_LEVELS
        
        # Normalize to sum=1
        total = sum(ratios)
        return {MEMORY_TYPES[i]: ratios[i] / total for i in range(N_TYPES)}
    
    @classmethod
    def encode(cls, allocation: Dict[str, float]) -> int:
        """Convert allocation ratios to action index."""
        action_idx = 0
        for i in range(N_TYPES - 1, -1, -1):
            alloc = allocation.get(MEMORY_TYPES[i], 0.25)
            level = min(cls.N_LEVELS - 1, max(0, round(alloc * cls.N_LEVELS) - 1))
            action_idx = action_idx * cls.N_LEVELS + level
        return action_idx


# ─── Reward Function ───────────────────────────────────────────
class BudgetReward:
    """
    Composite reward function for context budget RL.
    
    R = w1 * task_success + w2 * budget_efficiency + 
        w3 * recall_accuracy - w4 * drift_penalty - w5 * staleness
    """
    
    def __init__(
        self,
        w_success: float = 0.35,
        w_budget: float = 0.25,
        w_recall: float = 0.20,
        w_drift: float = 0.10,
        w_staleness: float = 0.10,
    ):
        self.w_success = w_success
        self.w_budget = w_budget
        self.w_recall = w_recall
        self.w_drift = w_drift
        self.w_staleness = w_staleness
    
    def compute(
        self,
        task_success: float,      # 0-1: did the task succeed?
        budget_used: float,        # 0-1: fraction of budget used
        recall_accuracy: float,   # 0-1: accuracy of recalled memories
        drift_score: float,       # 0-1: lower is better (0 = no drift)
        stale_fraction: float,    # 0-1: fraction of stale memories loaded
    ) -> float:
        budget_efficiency = 1.0 - abs(budget_used - 0.8)  # Optimal: 80% budget use
        
        reward = (
            self.w_success * task_success +
            self.w_budget * budget_efficiency +
            self.w_recall * recall_accuracy -
            self.w_drift * drift_score -
            self.w_staleness * stale_fraction
        )
        
        return max(0.0, min(1.0, reward))


# ─── Q-Learning Policy Network ─────────────────────────────────
class ContextBudgetPolicy:
    """
    Tabular Q-learning policy for Context Budget optimization.
    
    MVP: Simple Q-table with state discretization.
    Phase 2: Neural network (PyTorch) with PPO training.
    """
    
    def __init__(
        self,
        learning_rate: float = 0.1,
        discount_factor: float = 0.95,
        epsilon: float = 0.3,
        n_state_discretizations: int = 5,
    ):
        self.lr = learning_rate
        self.gamma = discount_factor
        self.epsilon = epsilon
        self.n_bins = n_state_discretizations
        
        # Q-table: state_idx → action_idx → Q-value
        # State discretization: n_bins^(state_dim) → too big, use feature hashing
        # For MVP: use a smaller representation (only 4 key features, 5 bins = 625 states)
        self._q_table: Dict[int, Dict[int, float]] = {}
        
        # Reward function
        self.reward_fn = BudgetReward()
        
        # Training data
        self._episode_history: deque = deque(maxlen=10000)
        self._recent_rewards: deque = deque(maxlen=100)
        
        # Epsilon decay
        self.epsilon_decay = 0.995
        self.epsilon_min = 0.05
    
    def select_action(
        self,
        state: BudgetState,
        training: bool = True,
    ) -> Tuple[int, Dict[str, float]]:
        """Select action using epsilon-greedy policy."""
        state_idx = self._discretize_state(state)
        
        # Epsilon-greedy
        if training and random.random() < self.epsilon:
            action_idx = random.randint(0, BudgetAction.TOTAL_ACTIONS - 1)
        else:
            # Greedy: select best action
            q_values = self._q_table.get(state_idx, {})
            if q_values:
                action_idx = max(q_values.items(), key=lambda x: x[1])[0]
            else:
                action_idx = 124  # Default: roughly equal allocation
        
        allocation = BudgetAction.decode(action_idx)
        return action_idx, allocation
    
    def update(
        self,
        state: BudgetState,
        action_idx: int,
        reward: float,
        next_state: Optional[BudgetState] = None,
        done: bool = False,
    ) -> None:
        """Update Q-value using Bellman equation."""
        state_idx = self._discretize_state(state)
        
        if state_idx not in self._q_table:
            self._q_table[state_idx] = {}
        
        current_q = self._q_table[state_idx].get(action_idx, 0.0)
        
        # Compute target
        if done or next_state is None:
            target = reward
        else:
            next_state_idx = self._discretize_state(next_state)
            next_q_values = self._q_table.get(next_state_idx, {})
            max_next_q = max(next_q_values.values()) if next_q_values else 0.0
            target = reward + self.gamma * max_next_q
        
        # Update Q-value
        new_q = current_q + self.lr * (target - current_q)
        self._q_table[state_idx][action_idx] = new_q
        
        # Store experience
        self._episode_history.append({
            "state": state.to_vector(),
            "action": action_idx,
            "reward": reward,
            "done": done,
        })
        self._recent_rewards.append(reward)
        
        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)
    
    def train_from_episodes(
        self,
        episodes: List[Dict[str, Any]],
        n_epochs: int = 10,
    ) -> Dict[str, List[float]]:
        """
        Train on collected episodes.
        
        Each episode: {
            "states": [BudgetState, ...],
            "actions": [int, ...],
            "rewards": [float, ...],
        }
        """
        loss_history = []
        reward_history = []
        
        for epoch in range(n_epochs):
            total_reward = 0
            total_loss = 0
            n_updates = 0
            
            for episode in episodes:
                states = episode["states"]
                actions = episode["actions"]
                rewards = episode["rewards"]
                
                for t in range(len(rewards)):
                    state = states[t] if isinstance(states[t], BudgetState) else BudgetState.from_vector(states[t])
                    action = actions[t]
                    reward = rewards[t]
                    next_state = BudgetState.from_vector(states[t+1]) if t+1 < len(states) else None
                    
                    state_idx = self._discretize_state(state)
                    if state_idx not in self._q_table:
                        self._q_table[state_idx] = {}
                    current_q = self._q_table[state_idx].get(action, 0.0)
                    
                    if next_state:
                        ns_idx = self._discretize_state(next_state)
                        next_q = self._q_table.get(ns_idx, {})
                        max_next = max(next_q.values()) if next_q else 0.0
                        target = reward + self.gamma * max_next
                    else:
                        target = reward
                    
                    loss = (target - current_q) ** 2
                    new_q = current_q + self.lr * (target - current_q)
                    self._q_table[state_idx][action] = new_q
                    
                    total_loss += loss
                    total_reward += reward
                    n_updates += 1
            
            avg_loss = total_loss / max(n_updates, 1)
            avg_reward = total_reward / max(n_updates, 1)
            loss_history.append(avg_loss)
            reward_history.append(avg_reward)
            
            # Learning rate decay
            self.lr *= 0.95
        
        return {"loss": loss_history, "reward": reward_history}
    
    def save(self, path: str) -> None:
        """Save Q-table and metadata."""
        data = {
            "q_table": {
                str(k): v for k, v in self._q_table.items()
            },
            "epsilon": self.epsilon,
            "learning_rate": self.lr,
            "discount_factor": self.gamma,
            "n_bins": self.n_bins,
            "recent_rewards": list(self._recent_rewards),
            "timestamp": time.time(),
        }
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Policy saved to {path} ({len(self._q_table)} states)")
    
    def load(self, path: str) -> None:
        """Load Q-table and metadata."""
        with open(path, 'r') as f:
            data = json.load(f)
        self._q_table = {int(k): v for k, v in data["q_table"].items()}
        self.epsilon = data.get("epsilon", self.epsilon)
        self.lr = data.get("learning_rate", self.lr)
        self.gamma = data.get("discount_factor", self.gamma)
        self.n_bins = data.get("n_bins", self.n_bins)
        self._recent_rewards = deque(data.get("recent_rewards", []), maxlen=100)
        logger.info(f"Policy loaded from {path} ({len(self._q_table)} states)")
    
    def _discretize_state(self, state: BudgetState) -> int:
        """
        Discretize continuous state to integer index.
        
        Uses only budget_ratios (4 dims) for state representation.
        Each dimension discretized into n_bins levels.
        """
        vec = state.budget_ratios[:4]  # Only 4 features
        idx = 0
        for v in vec:
            level = min(self.n_bins - 1, max(0, int(v * self.n_bins)))
            idx = idx * self.n_bins + level
        return idx
    
    def get_stats(self) -> Dict[str, Any]:
        """Get policy statistics."""
        return {
            "n_states": len(self._q_table),
            "n_actions_per_state": {
                str(k): len(v) for k, v in self._q_table.items()
            },
            "epsilon": round(self.epsilon, 4),
            "learning_rate": round(self.lr, 6),
            "n_episodes_trained": len(self._episode_history),
            "avg_recent_reward": (
                round(sum(self._recent_rewards) / len(self._recent_rewards), 4)
                if self._recent_rewards
                else None
            ),
        }


# ─── Neural Policy (Phase 2) ──────────────────────────────────
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

if HAS_TORCH:
    class NNPolicyNetwork(nn.Module):
        """
        Neural network policy for Context Budget allocation.
        
        Phase 2 replacement for tabular Q-learning.
        Uses PPO (Proximal Policy Optimization) for training.
        """
        
        def __init__(self, state_dim: int = BudgetState.DIM, n_actions: int = BudgetAction.TOTAL_ACTIONS, hidden_dim: int = 128):
            super().__init__()
            self.network = nn.Sequential(
                nn.Linear(state_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.ReLU(),
                nn.Linear(hidden_dim, n_actions),
            )
        
        def forward(self, state: torch.Tensor, action: Optional[torch.Tensor] = None):
            """Return action logits and value."""
            logits = self.network(state)  # (batch, n_actions)
            
            if action is not None:
                log_probs = torch.nn.functional.log_softmax(logits, dim=-1)
                action_log_probs = log_probs.gather(1, action.unsqueeze(-1))
                return action_log_probs, logits
            return logits
        
        def get_action(self, state: torch.Tensor, deterministic: bool = False):
            """Sample or select action."""
            logits = self.forward(state)
            if deterministic:
                action = torch.argmax(logits, dim=-1)
                log_prob = torch.nn.functional.log_softmax(logits, dim=-1).gather(1, action.unsqueeze(-1))
                return action, log_prob
            
            dist = torch.distributions.Categorical(logits=logits)
            action = dist.sample()
            log_prob = dist.log_prob(action)
            return action, log_prob
