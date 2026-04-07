# 6. DECISION MAKING — Brain to AI Mapping
> Source: research/01-human-brain-cognitive-architecture.md
---


### 6.1 Prefrontal Cortex Role

**Brain Mechanism:**
- **dlPFC**: Working memory, rule maintenance, abstract reasoning
- **vmPFC**: Value integration, emotional decision-making
- **OFC**: Outcome expectation, reward value representation
- **ACC**: Conflict monitoring, effort-cost computation
- **Frontopolar cortex (BA10)**: Prospective memory, branching (maintain goal while exploring subgoal)

**AI Agent Implementation:**
```
PFC-inspired Architecture:
- dlPFC analog: Task/goal representation module (persistent state)
- vmPFC analog: Value estimator network
- OFC analog: Outcome predictor (world model)
- ACC analog: Conflict/uncertainty detector
- Frontopolar analog: Meta-controller that manages subgoal hierarchies

Implementation:
- Maintain explicit goal stack
- Value-based action selection: softmax over Q-values
- Effort-cost computation: Include compute cost in decision
- Branching: Suspend current task, explore subtask, resume
```

### 6.2 Reward Prediction Error

**Brain Mechanism:**
- **Dopamine neurons** (VTA/SNc) encode: δ = R - E[R]
- **Positive RPE**: Better than expected → increase behavior
- **Negative RPE**: Worse than expected → decrease behavior
- **Temporal difference learning**: Brain implements TD(λ)

**AI Agent Implementation:**
```
- TD learning: δ_t = r_t + γV(s_{t+1}) - V(s_t)
- Use RPE to:
  - Update value functions
  - Modulate learning rate (high RPE → high learning)
  - Trigger memory consolidation (surprising events)
  - Drive exploration (high uncertainty → explore)
- Implement intrinsic reward: Novelty, learning progress, empowerment
```

### 6.3 Value-Based Decision Making

**Brain Mechanism:**
- **Common currency**: vmPFC represents all options on single value scale
- **Drift-diffusion model**: Evidence accumulation to threshold
- **Orbital frontal cortex**: Relative value comparison
- **Somatic marker hypothesis**: Emotional tags guide decisions

**AI Agent Implementation:**
```
Value-Based Decision Pipeline:
1. Option generation: Retrieve/construct possible actions
2. Value estimation: V(a) = E[reward] - cost + intrinsic_bonus
3. Evidence accumulation: Drift-diffusion or sequential sampling
4. Threshold crossing: Commit when evidence > threshold
5. Post-decision: Monitor outcome, update values

Implementation:
- Multi-armed bandit for exploration-exploitation
- UCB1: Select action with highest upper confidence bound
- Thompson sampling: Sample from posterior, select best
- Implement "somatic markers": Tag actions with emotional valence
- Risk sensitivity: Include variance in value computation
```

---

