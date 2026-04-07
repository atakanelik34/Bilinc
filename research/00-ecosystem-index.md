# AI Agent Brain — Master Research Ecosystem Index

> The complete research foundation for building a brain-inspired AI Agent system.
> 378+ sources surveyed across 5 comprehensive documents.
> Date: April 2026

---

## RESEARCH OVERVIEW

This ecosystem represents the most comprehensive research collection for building an AI Agent Brain system. Every major component of human cognition has been studied, mapped to computational models, and connected to existing open-source implementations.

### Total Sources Surveyed
| Source Type | Count | Document |
|---|---|---|
| ArXiv Papers | 107+ | [02-arxiv-papers-survey.md](./02-arxiv-papers-survey.md) |
| GitHub Projects | 91+ | [03-github-projects-survey.md](./03-github-projects-survey.md) |
| PyPI Packages | 80+ | [04-pypi-packages-survey.md](./04-pypi-packages-survey.md) |
| Agent Architectures | 10 deep-dives | [05-ai-agent-architectures-analysis.md](./05-ai-agent-architectures-analysis.md) |
| Brain Mechanisms | 8 systems | [01-human-brain-cognitive-architecture.md](./01-human-brain-cognitive-architecture.md) |
| **TOTAL** | **378+** | |

---

## DOCUMENT MAP

### 01. Human Brain Cognitive Architecture
**File:** [01-human-brain-cognitive-architecture.md](./01-human-brain-cognitive-architecture.md)

Complete mapping of human brain mechanisms to AI agent implementations:
- **Memory Systems**: Working, Short-term, Long-term (Episodic, Semantic, Procedural), Consolidation, Retrieval, Decay/Forgetting
- **Thinking & Reasoning**: System 1/2, Deductive, Inductive, Abductive, Analogical, Causal
- **Imagination & Creativity**: Mental Simulation, Counterfactual Thinking, Divergent Thinking, Creative Problem Solving
- **Attention Mechanisms**: Selective, Divided, Attentional Control, Salience Network
- **Learning Mechanisms**: Hebbian, Synaptic Plasticity, Long-Term Potentiation, Neurogenesis
- **Decision Making**: Prefrontal Cortex, Reward Prediction Error, Value-Based
- **Metacognition**: Self-Awareness, Monitoring, Confidence Calibration
- **Sleep & Consolidation**: NREM/REM cycles, Sleep-dependent forgetting, Sleep & creativity

Each section includes brain mechanism description, computational models, and specific AI agent implementation patterns.

---

### 02. ArXiv Papers Survey (107+ papers)
**File:** [02-arxiv-papers-survey.md](./02-arxiv-papers-survey.md)

10 categories, 107+ papers with full citations, summaries, and relevance analysis:

| Category | Papers | Key Papers |
|---|---|---|
| AI Agent Memory Systems | 17 | Mem0, A-Mem, Memory OS, All-Mem, AriadneMem |
| LLM Reasoning & Planning | 15 | CoT, ReAct, GoT, ToT, Forest-of-Thought |
| Long-Term Memory for LLMs | 10 | MemoryLLM, Larimar, Human-Inspired Episodic |
| Cognitive Architectures | 8 | Cognitive Architectures for Language Agents, Centaur, Unified Mind |
| Neural-Symbolic Reasoning | 9 | Neuro-Symbolic AI 2024 Review, Dolphin, SymBa |
| Memory-Augmented NNs | 8 | MATTER, TransformerFAM, MELODI, Evolved Transformer Memory |
| RAG & Variants | 10 | GraphRAG, DeepRAG, RetrievalAttention, MemSifter |
| Self-Reflection & Metacognition | 11 | Reflexion, MetaReflection, MUSE, PreFlect |
| Forgetting Mechanisms | 9 | Catastrophic Forgetting surveys, FIT, Orthogonal Fine-tuning |
| Imagination & Mental Simulation | 10 | Imagine-then-Plan, Dyna-Mind, SimuRA, WorldCoder |

---

### 03. GitHub Projects Survey (91+ projects)
**File:** [03-github-projects-survey.md](./03-github-projects-survey.md)

10 categories, 91+ projects with stars, tech stack, and brain relevance:

| Category | Projects | Top Stars |
|---|---|---|
| Agent Frameworks | 13 | AutoGPT (183K), LangChain (132K), MetaGPT (66K) |
| Memory Systems | 23 | Mem0 (52K), Graphiti (24.5K), Letta (22K) |
| Cognitive Architectures | 8 | OpenCog (2.4K), SPAUN 2.0, BrainCog |
| Neuro-Symbolic Reasoning | 7 | Nucleoid (734), IBM LNN (313) |
| RAG & Knowledge Graphs | 9 | GraphRAG (32K), LightRAG (32K), LlamaIndex (48K) |
| State Management | 4 | TaskWeaver (6.1K) |
| Self-Improving/Metacognitive | 7 | GPTSwarm (1K), Ouroboros (457) |
| Planning & Decomposition | 5 | TreeThinkerAgent, Plan-over-Graph |
| Surveys/Collections | 10 | LLM-Agents-Papers (2.3K), Agent-Memory-Paper-List (1.7K) |
| Neural Memory/Brain-Inspired | 5 | MSA (2K), neocortex (235) |

---

### 04. PyPI Packages Survey (80+ packages)
**File:** [04-pypi-packages-survey.md](./04-pypi-packages-survey.md)

10 categories, 80+ packages with versions, features, and use cases:

| Category | Packages | Key Packages |
|---|---|---|
| Vector DBs & Embedding Stores | 13 | chromadb, qdrant-client, faiss-cpu, weaviate-client |
| Memory Management Libraries | 30 | mem0ai, letta, neural-memory, langmem |
| Graph DBs & Knowledge Graphs | 18 | networkx, graphrag, neo4j, rdflib |
| State Management | 9 | langgraph, python-statemachine, pytransitions |
| Cognitive Computing | 7 | braincog, thinking-engine, cortex-omega |
| Neural Network Architectures | 7 | torch-geometric, dgl, x-transformers |
| Reasoning & Logic Engines | 10 | z3-solver, sympy, pyreason |
| Planning & Scheduling | 2 | scheduler, tarski |
| Retrieval Systems | 10 | sentence-transformers, txtai, haystack-ai |
| Serialization & Persistence | 10 | dill, msgspec, orjson, tinydb |

---

### 05. AI Agent Architectures Analysis (10 systems)
**File:** [05-ai-agent-architectures-analysis.md](./05-ai-agent-architectures-analysis.md)

Deep-dive analysis of 10 leading agent architectures:

| System | Key Innovation | Main Weakness | Our Improvement |
|---|---|---|---|
| MemGPT/Letta | OS-style virtual memory | No automatic consolidation | Add sleep-cycle consolidation |
| OpenAI Swarm | Simple handoff pattern | No shared memory | Add persistent knowledge graph |
| CrewAI | Role-based collaboration | Rigid roles | Make roles dynamic/learnable |
| MetaGPT | SOP-driven workflows | Static SOPs | Adaptive, evolving SOPs |
| AutoGen | Conversational agents | Inefficient back-and-forth | Structured state transitions |
| LangGraph | Graph-based state machine | Static graph definition | Dynamic graph generation |
| CogAgent | Dual-resolution perception | Domain-specific | Multi-modal, resolution-adaptive |
| Voyager | Skill library + curriculum | Unbounded growth | Skill pruning + abstraction |
| Generative Agents | Memory stream + reflection | No forgetting/consolidation | Full memory lifecycle |
| Reflexion | Verbal self-reflection | Limited memory window | Persistent reflection memory |

---

## AI AGENT BRAIN ARCHITECTURE BLUEPRINT

Based on all 378+ sources, here is the unified architecture:

```
+------------------------------------------------------------------+
|                        META-CONTROLLER                            |
|  (Frontopolar PFC + ACC analog)                                   |
|  - System 1/2 routing    - Attention allocation                   |
|  - Confidence monitoring - Task switching                         |
|  - Goal management       - Resource budgeting                     |
|  - Architecture evolution - Self-improvement                      |
+------------------------------------------------------------------+
|                                                                    |
|  +----------------+  +----------------+  +----------------------+  |
|  |  SYSTEM 1      |  |  SYSTEM 2      |  |   SALIENCE NETWORK   |  |
|  |  (Fast Path)   |  |  (Slow Path)   |  |                      |  |
|  | - Cached       |  | - CoT/ToT/GoT  |  | - Novelty detector   |  |
|  | - Heuristics   |  | - Planning     |  | - Surprise detector  |  |
|  | - Pattern      |  | - Reasoning    |  | - Urgency detector   |  |
|  |   matching     |  | - Verification |  | - Internal monitor   |  |
|  +-------+--------+  +-------+--------+  +----------+-----------+  |
|          |                   |                      |              |
+----------+-------------------+----------------------+--------------+
|          |                   |                      |              |
|  +-------v-------------------v----------------------v-----------+  |
|  |                    ATTENTION SYSTEM                          |  |
|  |  - Selective filtering  - Priority allocation               |  |
|  |  - Context management   - Compute budgeting                 |  |
|  |  - Distraction filtering - Arousal modulation               |  |
|  +---------------------------+---------------------------------+  |
|                              |                                    |
+------------------------------+------------------------------------+
|                              |                                    |
|  +---------------------------v---------------------------------+  |
|  |                    MEMORY SYSTEM                            |  |
|  |                                                             |  |
|  |  +-------------+ +-------------+ +----------------------+   |  |
|  |  |  WORKING    | |  EPISODIC   | |     SEMANTIC         |   |  |
|  |  |  MEMORY     | |  MEMORY     | |     MEMORY           |   |  |
|  |  |  (4-8 slots)| |  (Vector    | |  (Knowledge          |   |  |
|  |  |  + priority | |   DB +      | |   Graph +            |   |  |
|  |  |  eviction)  | |   Temporal  | |   Embeddings)        |   |  |
|  |  |             | |   Index)    | |                      |   |  |
|  |  +-------------+ +-------------+ +----------------------+   |  |
|  |                                                             |  |
|  |  +-------------+ +--------------------------------------+   |  |
|  |  | PROCEDURAL  | |     CONSOLIDATION ENGINE             |   |  |
|  |  |  MEMORY     | |  (Sleep analog)                      |   |  |
|  |  |  (Skills/   | |  - NREM: Replay, Integration,        |   |  |
|  |  |   Macros)   | |    Abstraction, Pruning              |   |  |
|  |  |             | |  - REM: Skill consolidation,         |   |  |
|  |  |             | |    Creative recombination, Dreaming  |   |  |
|  |  +-------------+ +--------------------------------------+   |  |
|  |                                                             |  |
|  |  +-----------------------------------------------------+   |  |
|  |  |  FORGETTING ENGINE                                  |   |  |
|  |  |  - Ebbinghaus decay curves                          |   |  |
|  |  |  - Spaced repetition scheduling                     |   |  |
|  |  |  - Interference management                          |   |  |
|  |  |  - Active forgetting (conflict resolution)          |   |  |
|  |  +-----------------------------------------------------+   |  |
|  +-------------------------------------------------------------+  |
|                                                                    |
+--------------------------------------------------------------------+
|                                                                    |
|  +----------------+  +----------------+  +----------------------+  |
|  |  IMAGINATION   |  |  METACOGNITION |  |    LEARNING ENGINE   |  |
|  |  ENGINE        |  |                |  |                      |  |
|  | - Mental       |  | - Self-model   |  | - Hebbian learning   |  |
|  |   simulation   |  | - Confidence   |  | - Synaptic plasticity|  |
|  | - Counter-     |  |   estimation   |  | - LTP/LTD analogs    |  |
|  |   factuals     |  | - Calibration  |  | - Neurogenesis       |
|  | - Dream        |  | - Error        |  |   (dynamic growth)   |  |
|  |   insights     |  |   detection    |  |                      |  |
|  | - Divergent    |  | - Strategy     |  |                      |  |
|  |   thinking     |  |   evaluation   |  |                      |  |
|  +----------------+  +----------------+  +----------------------+  |
|                                                                    |
+--------------------------------------------------------------------+
```

---

## IMPLEMENTATION ROADMAP

### Phase 1: Foundation (Weeks 1-4)
- [ ] Working Memory (context management with priority eviction)
- [ ] Episodic Memory (vector DB + temporal indexing)
- [ ] System 1/2 routing (confidence-based switching)
- [ ] Basic attention system (selective filtering)

### Phase 2: Core Cognition (Weeks 5-8)
- [ ] Semantic Memory (knowledge graph construction)
- [ ] Procedural Memory (skill library with automaticity)
- [ ] Consolidation Engine (NREM-like offline processing)
- [ ] Forgetting Engine (Ebbinghaus curves + spaced repetition)

### Phase 3: Higher Cognition (Weeks 9-12)
- [ ] Imagination Engine (mental simulation + counterfactuals)
- [ ] Metacognition Layer (self-model + confidence calibration)
- [ ] Learning Engine (Hebbian + plasticity analogs)
- [ ] REM-like creative consolidation (dream insights)

### Phase 4: Meta-Level (Weeks 13-16)
- [ ] Meta-Controller (full System 1/2 + attention orchestration)
- [ ] Dynamic Architecture Evolution (self-modifying structure)
- [ ] Cross-Domain Transfer Learning
- [ ] Self-Generated Curriculum (automatic goal formation)

---

## KEY DESIGN PRINCIPLES

1. **Prediction, Compression, Adaptive Control** — The brain fundamental triad. Every component should serve at least one of these purposes.

2. **Hierarchical Processing** — Information flows through multiple levels of abstraction, from raw perception to abstract concepts.

3. **Dual-Process Architecture** — Fast (System 1) for routine, slow (System 2) for novel. Route based on confidence and novelty.

4. **Memory Lifecycle** — Encode -> Store -> Retrieve -> Consolidate -> Forget. Every memory goes through this full cycle.

5. **Sleep is Essential** — Offline consolidation is not optional. It is where learning actually happens.

6. **Forgetting is a Feature** — Adaptive forgetting reduces interference, improves generalization, and prevents cognitive overload.

7. **Metacognition is the Differentiator** — The ability to think about thinking is what separates a smart agent from a reactive one.

8. **Dynamic Architecture** — The system should evolve its own structure based on experience, not remain static.

---

## CRITICAL GAPS IDENTIFIED (Our Opportunities)

1. **No existing system has true memory consolidation** — All accumulate, none reorganize. This is our biggest differentiator.

2. **No system implements sleep cycles** — smysle/agent-memory and engram have basic versions, but nothing production-grade.

3. **No system has genuine metacognition** — Agents do not evaluate their own reasoning strategies.

4. **No system has cross-domain transfer** — Skills are siloed. We need abstraction layers.

5. **No system has automatic goal formation** — All goals are externally provided. True cognition generates its own objectives.

6. **Forgetting is almost universally ignored** — Only 2-3 projects implement any form of forgetting curves.

---

## RESEARCH SOURCES CROSS-REFERENCE

### Memory Systems
- Papers: Category 1 (17 papers), Category 3 (10 papers), Category 6 (8 papers)
- GitHub: Category 2 (23 projects), Category 10 (5 projects)
- PyPI: Category 2 (30 packages), Category 1 (13 packages)
- Brain: Section 1 (Memory Systems)

### Reasoning & Planning
- Papers: Category 2 (15 papers), Category 5 (9 papers)
- GitHub: Category 4 (7 projects), Category 8 (5 projects)
- PyPI: Category 7 (10 packages), Category 8 (2 packages)
- Brain: Section 2 (Thinking & Reasoning)

### Imagination & Creativity
- Papers: Category 10 (10 papers)
- GitHub: Category 7 (7 projects - self-improving)
- PyPI: Category 5 (7 packages - cognitive computing)
- Brain: Section 3 (Imagination & Creativity)

### Attention & Salience
- Papers: Implicit in Categories 1, 2, 4
- GitHub: Category 3 (8 projects - cognitive architectures)
- PyPI: Category 4 (9 packages - state management)
- Brain: Section 4 (Attention Mechanisms)

### Metacognition & Self-Awareness
- Papers: Category 8 (11 papers)
- GitHub: Category 7 (7 projects)
- PyPI: Category 5 (7 packages)
- Brain: Section 7 (Metacognition)

### Learning & Consolidation
- Papers: Category 9 (9 papers - forgetting), Category 6 (8 papers - memory-augmented)
- GitHub: Category 2 (23 projects - memory systems)
- PyPI: Category 2 (30 packages - memory management)
- Brain: Section 5 (Learning), Section 8 (Sleep & Consolidation)

---

*This index serves as the master reference for all AI Agent Brain development. Each linked document contains detailed, actionable research that directly informs implementation decisions.*
