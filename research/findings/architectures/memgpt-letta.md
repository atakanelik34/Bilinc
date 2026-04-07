# 1. MemGPT / Letta — Virtual Context Management — Architecture Deep Dive
> Source: research/05-ai-agent-architectures-analysis.md
---


### Architecture Overview
MemGPT (now Letta) treats the LLM context window like an operating system virtual memory. It introduces a tiered memory system that manages what stays in the limited context window and what gets paged out to external storage. The agent can call functions to read/write between main context (like RAM) and external storage (like disk).

### Memory Hierarchy
- **Core Memory** — Always in context: agent identity, user profile, ongoing session state. Fixed-size, analogous to CPU registers.
- **Archival Memory** — External vector database (e.g., ChromaDB, Milvus): stores unlimited past conversations, documents, knowledge. Retrieved via semantic similarity search.
- **Recall Memory** — Conversation history stored as a searchable log. Enables the agent to look back at specific past interactions.

### Reasoning Approach
The agent self-manages its own context through function calls (archival_memory_search, archival_memory_insert, conversation_search). It decides what to keep in context and what to offload, mimicking OS page replacement algorithms.

### State Management
State is split between the LLM working context (editable) and persistent external stores. The agent maintains a "memory window" and actively manages it through self-directed operations.

### Strengths
- Breaks through context window limitations
- Agent has explicit control over what it remembers
- Enables truly stateful, long-running agents
- Proven at production scale (1M+ stateful agents)

### Weaknesses
- Agent must be explicitly trained/prompted to manage memory well
- No automatic consolidation or summarization of memories
- Retrieval quality depends on embedding model
- Can be token-expensive with frequent memory operations

### Key Insight for AI Agent Brain
The OS-inspired memory hierarchy is essential. Our system should add **automatic memory consolidation** (sleep-like processes that summarize and reorganize memories) rather than relying solely on agent-initiated operations.

---

