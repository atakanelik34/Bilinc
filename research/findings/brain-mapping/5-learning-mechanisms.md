# 5. LEARNING MECHANISMS — Brain to AI Mapping
> Source: research/01-human-brain-cognitive-architecture.md
---


### 5.1 Hebbian Learning

**Brain Mechanism:**
- "Cells that fire together, wire together"
- **Spike-timing-dependent plasticity (STDP)**: 
  - Pre before post → LTP (strengthen)
  - Post before pre → LTD (weaken)
- **Oja's rule**: Normalized Hebbian learning
- **BCM theory**: Sliding modification threshold

**AI Agent Implementation:**
```
- Correlation-based weight updates: Δw = η × x × y
- Implement STDP in spiking neural networks (if using SNNs)
- For standard networks: Co-activation strengthens connections
- Association learning: When A and B co-occur, strengthen A↔B link
- Knowledge graph edge weight updates based on co-occurrence frequency
```

### 5.2 Synaptic Plasticity

**Brain Mechanism:**
- **LTP**: NMDA receptor activation → Ca2+ influx → AMPA insertion
- **LTD**: Low-frequency stimulation → AMPA removal
- **Metaplasticity**: Plasticity of plasticity (threshold adjustment)
- **Homeostatic plasticity**: Synaptic scaling maintains stability

**AI Agent Implementation:**
```
- Adaptive learning rates per parameter (Adam, RMSProp analogs)
- Meta-learning: Learn the learning rate
- Stability-plasticity balance: 
  - Elastic Weight Consolidation (EWC): Protect important weights
  - Synaptic Intelligence: Track parameter importance
- Homeostatic regularization: Prevent weight explosion/collapse
- Implement "critical periods": High plasticity early, reduced later
```

### 5.3 Long-Term Potentiation

**Brain Mechanism:**
- **Early LTP** (1-3 hrs): Post-translational modifications
- **Late LTP** (hours-days): Gene expression, protein synthesis, structural changes
- **Three-stage model**: Induction → Expression → Maintenance

**AI Agent Implementation:**
```
Three-Stage Learning:
1. Induction: Rapid weight update from single experience (fast system)
2. Expression: Consolidate through replay (offline processing)
3. Maintenance: Periodic re-training to prevent catastrophic forgetting

Implementation:
- Fast weights (cache) + slow weights (long-term)
- Fast weights updated immediately, slow weights updated during consolidation
- Implement "synaptic tagging and capture": Mark important synapses, consolidate later
```

### 5.4 Neurogenesis

**Brain Mechanism:**
- **Adult hippocampal neurogenesis**: Dentate gyrus generates new neurons
- **Pattern separation**: New neurons increase encoding capacity
- **Exercise, enrichment, learning** promote neurogenesis
- **Stress, aging** reduce neurogenesis

**AI Agent Implementation:**
```
- Dynamic architecture: Add new neurons/nodes when capacity is reached
- Network expansion: Grow network for new domains
- Pruning: Remove unused nodes (synaptic pruning analog)
- Implement "adult neurogenesis": Periodically add fresh random units to hidden layers
- Capacity management: Monitor representational capacity, expand when saturated
```

---

