# 5. AutoGen (Microsoft) — Conversational Agent Framework
> Deep dive | research/05-ai-agent-architectures-analysis.md
---


### Architecture Overview
AutoGen v0.4 (2025) is a framework for building agentic AI systems with conversable agents. Agents extend LLMs with tools, observe environments, reason, plan, act, and use memory. It supports **multi-agent conversations** where agents can talk to each other, humans, and tools. Key concepts: ConversableAgent, AgentRuntime, Termination, Tools.

### Memory Model
- **Conversation history** — Full dialogue between agents
- **Tool-based memory** — External tools for persistent storage
- **Context management** — Agents manage their own context windows

### Reasoning Approach
Multi-agent conversation. Agents can be configured with different personas, capabilities, and termination conditions. They engage in back-and-forth dialogue to solve problems. Supports code execution, human-in-the-loop, and tool use.

### State Management
State is maintained through the conversation thread and external tools. The AgentRuntime manages agent lifecycle, message routing, and tool execution. v0.4 introduced a redesigned architecture for scale, extensibility, and robustness.

### Strengths
- Highly flexible conversation patterns
- Strong tool integration ecosystem
- Human-in-the-loop support
- Code execution with safety controls
- Enterprise-grade with Microsoft backing
- v0.4 redesigned for production scale

### Weaknesses
- Conversational approach can be inefficient (lots of back-and-forth)
- No built-in structured memory hierarchy
- Complex to configure for non-trivial workflows
- Conversation-based state does not scale well
- Can produce verbose, unfocused outputs

### Key Insight for AI Agent Brain
The conversational paradigm is natural but wasteful. Our system should use **structured state transitions** (like LangGraph) with conversation as one channel, not the primary mechanism.

---
