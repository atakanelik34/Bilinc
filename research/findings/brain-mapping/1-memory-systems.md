# 1. MEMORY SYSTEMS — Brain to AI Mapping
> Source: research/01-human-brain-cognitive-architecture.md
---


### 1.1 Working Memory

**Brain Mechanism:**
- **Prefrontal cortex (PFC)** maintains information via persistent neuronal firing
- **Baddeley's model**: Central executive (PFC), phonological loop (left temporoparietal), visuospatial sketchpad (right hemisphere), episodic buffer
- Capacity: ~4±1 chunks (Cowan's revision of Miller's 7±2)
- **Dopaminergic gating**: D1 receptors stabilize representations, D2 receptors enable updating
- Neural mechanism: Recurrent excitation in PFC microcircuits with GABAergic inhibition preventing interference

**Computational Models:**
- **LSTM/GRU**: Gated recurrent networks mirror gating mechanisms
- **Transformer attention**: Self-attention as content-addressable working memory
- **Differentiable Neural Computer (DNC)**: Explicit external memory matrix with read/write heads
- **Slot-based working memory**: Fixed-capacity vector slots with attention-based allocation

**AI Agent Implementation:**
```
Architecture: Hybrid Transformer + External Memory Buffer
- Maintain a "context window" as working memory (4-8 key items)
- Implement priority-based eviction: recency × relevance × novelty
- Use attention weights to simulate central executive control
- Chunk information hierarchically (embeddings → clusters → slots)
- Implement gating: decide what to keep/discard based on task relevance score
```

### 1.2 Short-Term Memory

**Brain Mechanism:**
- Transient synaptic facilitation (seconds to minutes)
- **Activity-silent WM**: Hidden states in synaptic weights, not just firing rates
- Decay time constant: ~15-30 seconds without rehearsal
- **Chunking**: Grouping items into meaningful units expands effective capacity

**AI Agent Implementation:**
```
- Rolling buffer with exponential decay: weight(t) = weight(0) × e^(-t/τ)
- Rehearsal mechanism: Periodically re-encode important items
- Auto-chunking: Cluster similar embeddings, store cluster centroid + residuals
- Implement "synaptic tagging": Mark important transitions for consolidation
```

### 1.3 Long-Term Memory

#### Episodic Memory

**Brain Mechanism:**
- **Hippocampus** (CA1, CA3, dentate gyrus) encodes event-specific memories
- **Pattern separation**: Dentate gyrus creates orthogonal representations
- **Pattern completion**: CA3 autoassociative network retrieves from partial cues
- **Context-dependent retrieval**: Hippocampal-cortical binding
- **Time cells**: Hippocampal neurons encode temporal context
- Systems consolidation: Hippocampus → neocortex over weeks/months

**Computational Models:**
- **Hopfield networks**: Autoassociative memory
- **Transformer episodic memory**: Store (state, action, reward, next_state) tuples
- **Vector databases**: FAISS, Pinecone for similarity-based retrieval
- **Neural episodic control**: DNC + experience replay

**AI Agent Implementation:**
```
Architecture: Vector DB + Temporal Indexing
- Store experiences as: {embedding, timestamp, context_vector, outcome, metadata}
- Dual retrieval: similarity search + temporal proximity
- Implement pattern separation: Add noise to similar embeddings before storage
- Implement pattern completion: Retrieve from partial query via attention
- Temporal context: Append time-decay embedding to each memory
- Consolidation pipeline: High-value memories → compressed summary storage
```

#### Semantic Memory

**Brain Mechanism:**
- **Anterior temporal lobe** as semantic hub
- **Distributed cortical representations**: Features stored in modality-specific areas
- **Schema formation**: Abstract knowledge structures in mPFC
- **Semantic networks**: Concepts linked by associative strength

**AI Agent Implementation:**
```
- Knowledge graph: Nodes = concepts, edges = relationships (weighted)
- Embedding space: Pre-trained LLM embeddings as semantic representations
- Ontology learning: Cluster embeddings, extract hierarchical structure
- Schema storage: Abstract templates extracted from repeated patterns
- Update mechanism: Bayesian updating of edge weights based on new evidence
```

#### Procedural Memory

**Brain Mechanism:**
- **Basal ganglia** (striatum): Action-outcome learning
- **Cerebellum**: Motor timing and coordination
- **Dopamine-mediated reinforcement**: Reward prediction error drives learning
- Gradual automatization: Prefrontal → striatal shift with practice

**AI Agent Implementation:**
```
- Policy networks: Separate "learned skills" as reusable sub-policies
- Skill library: Store successful action sequences as macros
- Automaticity: Frequently used sequences → cached policy (skip deliberation)
- Q-learning / PPO for procedural skill acquisition
- Hierarchical RL: High-level planner selects skills, low-level executes
```

### 1.4 Memory Consolidation

**Brain Mechanism:**
- **Synaptic consolidation** (hours): Protein synthesis, structural changes
- **Systems consolidation** (weeks-years): Hippocampal replay → cortical integration
- **Replay during rest**: Hippocampal sharp-wave ripples (SWRs) reactivate recent experiences
- **Reconsolidation**: Retrieved memories become labile, can be updated
- **Sleep-dependent consolidation**: Slow-wave sleep (SWS) for declarative, REM for procedural

**AI Agent Implementation:**
```
Consolidation Pipeline:
1. Online phase: Store raw experiences in episodic buffer
2. Offline phase (idle time / scheduled):
   a. Prioritize experiences by: reward magnitude × novelty × uncertainty
   b. Replay: Re-process top experiences through learning algorithm
   c. Compress: Extract generalizable patterns → semantic memory
   d. Integrate: Update knowledge graph with new relationships
   e. Prune: Delete redundant/low-value episodic memories
3. Reconsolidation: When retrieving old memory, update with new context
```

### 1.5 Memory Retrieval

**Brain Mechanism:**
- **Cue-dependent retrieval**: Partial cue activates full pattern via completion
- **Context reinstatement**: Re-encoding context improves retrieval
- **Retrieval-induced forgetting**: Retrieving one memory suppresses competitors
- **Tip-of-the-tongue**: Partial activation, incomplete pattern completion

**AI Agent Implementation:**
```
- Multi-cue retrieval: Combine semantic similarity + temporal + contextual cues
- Retrieval scoring: score = α·similarity + β·recency + γ·relevance + δ·novelty
- Competitive retrieval: Top-k results, suppress near-duplicates (RIF simulation)
- Context reinstatement: When stuck, re-encode current state to trigger relevant memories
- Implement "feeling of knowing" heuristic: Confidence score on retrieval quality
```

### 1.6 Memory Decay & Forgetting

**Brain Mechanism:**
- **Synaptic decay**: Long-term depression (LTD), synaptic pruning
- **Interference**: Proactive (old blocks new) and retroactive (new blocks old)
- **Motivated forgetting**: Prefrontal suppression of hippocampal retrieval
- **Adaptive forgetting**: Forgetting is feature, not bug — reduces interference, improves generalization

**AI Agent Implementation:**
```
- Exponential decay: weight(t) = weight(0) × e^(-λt) where λ is task-dependent
- Interference management: Orthogonalize similar memories during storage
- Active forgetting: Delete memories that conflict with updated beliefs
- Forgetting curve (Ebbinghaus): R = e^(-t/S) where S = memory strength
- Spaced repetition: Re-encode memories at optimal intervals to maintain strength
- Regularization as forgetting: L2 weight decay = synaptic decay analog
```

---

