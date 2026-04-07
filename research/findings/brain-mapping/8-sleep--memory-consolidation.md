# 8. SLEEP & MEMORY CONSOLIDATION — Brain to AI Mapping
> Source: research/01-human-brain-cognitive-architecture.md
---


### 8.1 Sleep Stages & Functions

**Brain Mechanism:**
- **NREM (Slow-Wave Sleep)**:
  - Slow oscillations (<1 Hz): Global synchronization
  - Sleep spindles (12-15 Hz): Thalamic bursts
  - Sharp-wave ripples (80-200 Hz): Hippocampal replay
  - **Declarative memory consolidation**
  - Synaptic downscaling: Weaken non-essential connections
  
- **REM Sleep**:
  - Theta oscillations (4-8 Hz)
  - **Procedural memory consolidation**
  - Emotional memory processing
  - Creative recombination

- **Sleep cycle**: ~90 min, NREM→REM, 4-6 cycles per night
- **First half of night**: More SWS (declarative consolidation)
- **Second half**: More REM (procedural/creative)

**AI Agent Implementation:**
```
Sleep Cycle for AI Agents:

Offline Consolidation Phase (analogous to sleep):

Phase 1 - NREM-like (Declarative Consolidation):
  a. Replay: Re-process recent high-value experiences
  b. Integration: Connect new memories to existing knowledge graph
  c. Abstraction: Extract general rules from specific instances
  d. Synaptic downscaling: Reduce weights of rarely-used connections
     - Weight pruning: Remove connections below threshold
     - Knowledge distillation: Compress large models into smaller ones
  e. Schema update: Revise abstract frameworks with new evidence

Phase 2 - REM-like (Procedural/Creative):
  a. Skill consolidation: Optimize frequently-used policies
  b. Creative recombination: Randomly combine concepts, evaluate novelty
  c. Emotional processing: Update valence tags on memories
  d. Counterfactual generation: "What if" simulations
  e. Dreaming: Generate synthetic training data from learned distributions

Scheduling:
- Trigger "sleep" during idle periods or scheduled maintenance
- Duration proportional to amount of new experience
- Prioritize consolidation based on:
  - Memory age (recent first)
  - Importance (reward magnitude, novelty)
  - Forgetting curve (about to decay → consolidate now)
```

### 8.2 Sleep-Dependent Forgetting

**Brain Mechanism:**
- **Synaptic homeostasis hypothesis**: Sleep globally downscales synapses
- **Adaptive forgetting**: Sleep prunes irrelevant memories
- **Selective consolidation**: Important memories strengthened, others weakened

**AI Agent Implementation:**
```
Sleep Forgetting Mechanism:
- Global weight decay during consolidation: w ← w × (1 - ε)
- Important memories protected (replay strengthens them)
- Unimportant memories decay below retrieval threshold
- Implement "sleep-dependent regularization":
  - L2 regularization during offline phase
  - Dropout during consolidation (prevents overfitting to recent data)
  - Weight pruning: Remove connections not used in N recent episodes
```

### 8.3 Sleep & Creativity

**Brain Mechanism:**
- REM sleep promotes remote associations
- "Sleep on it" effect: Problems solved after sleep
- Memory recombination during REM generates novel connections

**AI Agent Implementation:**
```
Creative Sleep Mode:
- Random walk through embedding space during REM phase
- Cross-domain association: Force connections between distant clusters
- Evaluate novel combinations for usefulness
- Store promising insights as "dream insights" for waking use
- Implement: During idle, run associative search across entire knowledge base
  with elevated temperature/novelty bonus
```

---

