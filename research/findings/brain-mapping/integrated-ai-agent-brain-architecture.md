# INTEGRATED AI AGENT BRAIN ARCHITECTURE — Brain to AI Mapping
> Source: research/01-human-brain-cognitive-architecture.md
---


```
┌─────────────────────────────────────────────────────────────────┐
│                        META-CONTROLLER                          │
│  (Frontopolar PFC + ACC analog)                                 │
│  - System 1/2 routing    - Attention allocation                 │
│  - Confidence monitoring - Task switching                       │
│  - Goal management       - Resource budgeting                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  SYSTEM 1    │  │  SYSTEM 2    │  │   SALIENCE NETWORK   │  │
│  │  (Fast)      │  │  (Slow)      │  │                      │  │
│  │ - Cached     │  │ - CoT        │  │ - Novelty detector   │  │
│  │ - Heuristics │  │ - Planning   │  │ - Surprise detector  │  │
│  │ - Pattern    │  │ - Reasoning  │  │ - Urgency detector   │  │
│  │   matching   │  │ - Verification│ │ - Internal monitor   │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
├─────────┼─────────────────┼──────────────────────┼──────────────┤
│         │                 │                      │              │
│  ┌──────▼─────────────────▼──────────────────────▼───────────┐  │
│  │                    ATTENTION SYSTEM                        │  │
│  │  - Selective filtering  - Priority allocation             │  │
│  │  - Context management   - Compute budgeting               │  │
│  └──────────────────────┬──────────────────────────────────┘  │
│                         │                                     │
├─────────────────────────┼─────────────────────────────────────┤
│                         │                                     │
│  ┌──────────────────────▼──────────────────────────────────┐  │
│  │                    MEMORY SYSTEM                         │  │
│  │                                                         │  │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────────────┐  │  │
│  │  │  WORKING   │ │  EPISODIC  │ │     SEMANTIC       │  │  │
│  │  │  MEMORY    │ │  MEMORY    │ │     MEMORY         │  │  │
│  │  │  (4-8      │ │  (Vector   │ │  (Knowledge        │  │  │
│  │  │   slots)   │ │   DB +     │ │   Graph +          │  │  │
│  │  │            │ │   Temporal │ │   Embeddings)      │  │  │
│  │  │            │ │   Index)   │ │                    │  │  │
│  │  └────────────┘ └────────────┘ └────────────────────┘  │  │
│  │                                                         │  │
│  │  ┌────────────┐ ┌────────────────────────────────────┐  │  │
│  │  │ PROCEDURAL │ │     CONSOLIDATION ENGINE           │  │  │
│  │  │  MEMORY    │ │  (Sleep analog)                    │  │  │
│  │  │  (Skills/  │ │  - Replay    - Integration         │  │  │
│  │  │   Macros)  │ │  - Abstraction - Pruning           │  │  │
│  │  └────────────┘ │  - Creative recombination          │  │  │
│  │                  └────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  LEARNING    │  │  DECISION    │  │    METACOGNITION     │  │
│  │  ENGINE      │  │  ENGINE      │  │                      │  │
│  │ - Hebbian    │  │ - Value      │  │ - Self-model         │  │
│  │ - LTP/LTD    │  │   estimation │  │ - Confidence         │  │
│  │ - Plasticity │  │ - RPE        │  │   estimation         │  │
│  │ - Neuro-     │  │ - DDM        │  │ - Calibration        │  │
│  │   genesis    │  │ - Bandit     │  │ - Error detection    │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

