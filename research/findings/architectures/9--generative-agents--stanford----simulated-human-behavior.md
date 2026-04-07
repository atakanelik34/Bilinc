# 9. Generative Agents (Stanford) — Simulated Human Behavior
> Deep dive | research/05-ai-agent-architectures-analysis.md
---


### Architecture Overview
Generative agents simulate believable human behavior through three key mechanisms:
1. **Memory Stream** — Complete record of agent experiences stored as natural language observations
2. **Retrieval Model** — Combines recency, importance, and relevance to retrieve memories
3. **Reflection Mechanism** — Synthesizes memories into higher-level inferences (traits, goals, relationships)

### Memory Model
- **Memory Stream** — Chronological list of all observations (like a diary)
- **Retrieval scoring** — recency(t) x importance x relevance(query)
- **Reflection memories** — Higher-level conclusions drawn from clusters of observations
- **Planning** — Future intentions derived from reflections and current state

### Reasoning Approach
Observe -> Retrieve -> Reflect -> Plan -> Act. Agents continuously observe their environment, retrieve relevant memories, reflect on patterns, form plans, and execute actions. Reflection creates abstract knowledge from concrete experiences.

### State Management
Each agent maintains its own memory stream and reflection state. The environment (Smallville town) provides shared context. Agents interact through natural language and physical actions.

### Strengths
- Emergent social behavior (parties, relationships, information spread)
- 5,600+ citations — highly influential
- Reflection creates genuine learning from experience
- Memory retrieval is cognitively plausible
- 5,000+ unique observations per agent over 2 days

### Weaknesses
- Computationally expensive (many LLM calls per agent per step)
- Memory stream grows unbounded
- No mechanism for forgetting or memory consolidation
- Reflection quality depends on LLM capability
- Simulation-focused, not task-oriented

### Key Insight for AI Agent Brain
The **memory stream + reflection** architecture is the closest to human-like cognition. Our system must implement: (1) importance-weighted memory storage, (2) periodic reflection that creates abstract knowledge, (3) multi-factor retrieval (recency + importance + relevance), and (4) planning derived from reflection.

---
