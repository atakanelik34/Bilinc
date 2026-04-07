# 4. ATTENTION MECHANISMS — Brain to AI Mapping
> Source: research/01-human-brain-cognitive-architecture.md
---


### 4.1 Selective Attention

**Brain Mechanism:**
- **Frontoparietal attention network**: Goal-directed (top-down) attention
- **Ventral attention network**: Stimulus-driven (bottom-up) attention
- **Thalamic gating**: Pulvinar filters sensory input
- **Biased competition**: Attended stimuli win neural competition
- **Feature-based attention**: Enhance specific features across visual field

**AI Agent Implementation:**
```
- Attention masks: Zero out irrelevant context tokens
- Multi-head attention as feature-based attention
- Top-down bias: Task embedding modulates attention weights
- Bottom-up salience: Novel/unusual stimuli get attention boost
- Implement attention budgeting: Allocate compute to most relevant inputs
- Sparse attention: Only attend to top-k most relevant items
```

### 4.2 Divided Attention

**Brain Mechanism:**
- **Limited capacity resource**: Attention as finite cognitive resource
- **Task switching cost**: ~200-500ms penalty per switch
- **Automaticity reduces load**: Well-practiced tasks need less attention
- **Central bottleneck**: Some operations must be serial

**AI Agent Implementation:**
```
- Compute budgeting: Allocate tokens/compute across subtasks
- Parallel processing: Independent subtasks run concurrently
- Task switching: Save/restore context state, incur switching penalty
- Priority queue: Highest-priority task gets most attention
- Implement "inattentional blindness": Deliberately ignore low-priority streams
```

### 4.3 Attentional Control

**Brain Mechanism:**
- **Anterior cingulate cortex (ACC)**: Conflict monitoring, error detection
- **Dorsolateral PFC**: Maintaining task goals, inhibiting distractions
- **Norepinephrine (locus coeruleus)**: Arousal modulation, explore/exploit
- **Adaptive gain theory**: Phasic (task-focused) vs tonic (scanning) modes

**AI Agent Implementation:**
```
Meta-Attention Controller:
- Conflict detector: When multiple actions have similar values → escalate
- Goal maintenance: Periodically re-check task objectives
- Distraction filtering: Suppress inputs unrelated to current goal
- Arousal modulation: 
  - Low arousal → increase exploration (tonic mode)
  - High arousal → focus on best option (phasic mode)
- Implement "attentional blink": Brief refractory period after processing important event
```

### 4.4 Salience Network

**Brain Mechanism:**
- **Anterior insula + ACC**: Detect behaviorally relevant stimuli
- **Network switching**: Salience network switches between DMN and CEN
- **Interoceptive awareness**: Insula monitors internal state

**AI Agent Implementation:**
```
Salience Detector:
- Novelty: Distance from known patterns
- Surprise: Prediction error magnitude
- Urgency: Time-sensitivity of input
- Value: Expected impact on objectives
- Internal state monitoring: Confidence, uncertainty, resource levels
- Trigger system switching based on salience score
```

---

