# 2. OpenAI Swarm — Multi-Agent Coordination — Architecture Deep Dive
> Source: research/05-ai-agent-architectures-analysis.md
---


### Architecture Overview
Swarm is a lightweight, experimental multi-agent orchestration framework. It uses a simple but powerful pattern: agents have instructions, tools, and handoff functions that transfer control to other agents. There is no complex graph — just agents that can delegate to other agents.

### Memory Model
Minimal — each agent maintains its own instruction set and context. No shared memory layer; state is passed through the conversation during handoffs.

### Reasoning Approach
Each agent is a specialized expert. The routing agent determines which specialist should handle the current request and hands off control. The receiving agent takes over the full conversation context.

### State Management
State flows through the conversation thread. When Agent A hands off to Agent B, Agent B receives the full conversation history. Handoffs are reversible — agents can hand back.

### Strengths
- Extremely simple and intuitive
- No complex orchestration layer to manage
- Easy to debug (linear conversation flow)
- Natural for conversational workflows

### Weaknesses
- No parallel execution — purely sequential
- No shared state between agents beyond conversation
- No built-in memory persistence
- Limited to conversational handoff patterns
- Educational/experimental — not production-ready

### Key Insight for AI Agent Brain
The handoff pattern is elegant but insufficient. We need **parallel agent execution** with a shared knowledge graph that persists across sessions, not just conversation-thread state.

---

