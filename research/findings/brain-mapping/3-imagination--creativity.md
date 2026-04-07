# 3. IMAGINATION & CREATIVITY — Brain to AI Mapping
> Source: research/01-human-brain-cognitive-architecture.md
---


### 3.1 Mental Simulation

**Brain Mechanism:**
- **Hippocampal construction**: Scene construction from elements
- **Default mode network**: Simulating future scenarios
- **Motor imagery**: Premotor cortex activates without execution
- **Predictive coding**: Brain as prediction machine, simulating outcomes

**AI Agent Implementation:**
```
- World model: Learn P(s'|s,a) for environment dynamics
- Rollout simulation: Simulate action sequences before executing
- Imagination-augmented RL: Train on imagined trajectories
- Model-based planning: MuZero-style internal simulation
- Counterfactual simulation: "What if I had taken action B?"
```

### 3.2 Counterfactual Thinking

**Brain Mechanism:**
- **Hippocampus + PFC**: Constructing alternative scenarios
- **Temporal parietal junction**: Distinguishing real from imagined
- **Regret processing**: Orbitofrontal cortex computes "what might have been"

**AI Agent Implementation:**
```
- Store alternative outcomes during decision-making
- Post-hoc analysis: "What was the value of the action I didn't take?"
- Counterfactual regret minimization (CFR) for game-theoretic settings
- Update policy based on counterfactual value, not just realized value
- Implement "close call" detection: Near-misses trigger learning
```

### 3.3 Divergent Thinking

**Brain Mechanism:**
- **Default mode network + executive control network**: Unusual coupling during creativity
- **Reduced latent inhibition**: More stimuli reach awareness
- **Dopamine**: Facilitates cognitive flexibility and novelty-seeking

**AI Agent Implementation:**
```
- Temperature-scaled generation: Increase randomness during ideation
- Beam search with diversity penalty: Encourage varied outputs
- Random perturbation: Add noise to embeddings to explore novel regions
- Cross-domain association: Force connections between distant concepts
- Implement "brainstorming mode": Generate N ideas before evaluating any
- Novelty search: Reward exploration of behavior space, not just task reward
```

### 3.4 Creative Problem Solving

**Brain Mechanism:**
- **Insight (Aha! moment)**: Anterior superior temporal gyrus activation
- **Incubation**: Unconscious processing during rest
- **Restructuring**: Breaking functional fixedness
- **Analogical transfer**: Applying solutions from distant domains

**AI Agent Implementation:**
```
Creative Problem Solving Pipeline:
1. Preparation: Encode problem deeply, gather relevant knowledge
2. Incubation: Step away, let associative processes work (background tasks)
3. Illumination: Detect sudden insight (high-confidence novel connection)
4. Verification: System 2 validates the insight

Implementation:
- Problem encoding: Multiple representations (graph, text, symbolic)
- Incubation: Background embedding similarity search across entire knowledge base
- Insight detection: Sudden high-similarity match between distant concepts
- Verification: Run solution through constraint checker / simulator
- Implement "functional fixedness breaking": Deliberately re-represent objects
```

---

