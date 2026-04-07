# GitHub Projects — AI Agent Frameworks, Memory Systems & Cognitive Architectures

> 91+ projects surveyed across 10 categories. Comprehensive open-source landscape for AI Agent Brain development.
> Date: April 2026

---

## 1. AI AGENT FRAMEWORKS (13 projects)

### 1. AutoGPT
- **URL:** https://github.com/Significant-Gravitas/AutoGPT
- **Stars:** 183,000+
- **Description:** Autonomous AI agent framework — the vision of accessible AI for everyone. Visual workflow builder, 300+ model support.
- **Key Tech:** Python, Docker, TypeScript
- **Relation to AI Agent Brain:** Provides the foundational autonomous agent loop — goal-setting, task execution, self-prompting. The "motor cortex" of an agent brain.
- **Notable Features:** Plugin ecosystem, Forge for building custom agents, visual workflow builder

### 2. BabyAGI
- **URL:** https://github.com/yoheinakajima/babyagi
- **Stars:** 22,200+
- **Description:** Minimalist task-driven autonomous agent that creates, prioritizes, and executes tasks based on an objective.
- **Key Tech:** Python, HTML, JavaScript
- **Relation to AI Agent Brain:** The simplest implementation of a planning-execution loop — the "prefrontal cortex" of task management.
- **Notable Features:** Ultra-simple codebase (~100 lines), easy to understand and extend

### 3. CrewAI
- **URL:** https://github.com/crewAIInc/crewAI
- **Stars:** 48,000+
- **Description:** Framework for orchestrating role-playing autonomous AI agents. Agents work together seamlessly tackling complex tasks.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Multi-agent collaboration = distributed cognition. Different agents act as specialized brain regions.
- **Notable Features:** Role-based agents, task delegation, unified memory system, process flows (sequential/hierarchical)

### 4. MetaGPT
- **URL:** https://github.com/FoundationAgents/MetaGPT
- **Stars:** 66,000+
- **Description:** Multi-agent framework that runs a software company with LLMs — assigns roles like PM, architect, engineer.
- **Key Tech:** Python, JavaScript, TypeScript
- **Relation to AI Agent Brain:** Organizational cognition — simulates how a team (or brain regions) coordinate via structured communication.
- **Notable Features:** SOP-driven workflows, structured output, software development pipeline

### 5. Microsoft AutoGen / AG2
- **URL:** https://github.com/microsoft/autogen (57K stars)
- **Fork:** https://github.com/ag2ai/ag2 (4.3K stars)
- **Stars:** 57,000+
- **Description:** Programming framework for agentic AI — multi-agent conversation framework.
- **Key Tech:** Python, Jupyter Notebook
- **Relation to AI Agent Brain:** Conversational multi-agent system models internal dialogue / theory of mind.
- **Notable Features:** Conversable agents, code execution, human-in-the-loop, AutoGen Studio

### 6. LangChain
- **URL:** https://github.com/langchain-ai/langchain
- **Stars:** 132,000+
- **Description:** The agent engineering platform — most popular LLM application framework.
- **Key Tech:** Python (99.3%)
- **Relation to AI Agent Brain:** The central nervous system — chains, agents, tools, memory all integrated.
- **Notable Features:** Massive integration ecosystem, LangGraph for stateful agents, LangMem for memory

### 7. LangGraph
- **URL:** https://github.com/langchain-ai/langgraph
- **Stars:** 28,500+
- **Description:** Build resilient language agents as graphs. Stateful, multi-actor applications with LLMs.
- **Key Tech:** Python, TypeScript
- **Relation to AI Agent Brain:** Graph-based state machine = neural network topology for agent reasoning flow.
- **Notable Features:** Cycles in computation, persistence layer, human-in-the-loop, streaming

### 8. OpenAI Agents SDK (Python)
- **URL:** https://github.com/openai/openai-agents-python
- **Stars:** 20,500+
- **Description:** Lightweight, powerful framework for multi-agent workflows from OpenAI.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Official OpenAI agent orchestration — handoff patterns, guardrails.
- **Notable Features:** Agent handoffs, guardrails, tracing, multi-agent workflows

### 9. OpenAI Agents SDK (JS)
- **URL:** https://github.com/openai/openai-agents-js
- **Stars:** 2,550+
- **Description:** JavaScript/TypeScript version of OpenAI agent framework with voice agent support.
- **Key Tech:** TypeScript
- **Relation to AI Agent Brain:** Multi-modal agent orchestration including voice.
- **Notable Features:** Voice agents, multi-agent workflows, TypeScript native

### 10. agentUniverse
- **URL:** https://github.com/agentuniverse-ai/agentUniverse
- **Stars:** 2,180+
- **Description:** LLM multi-agent framework by Ant Group for building multi-agent applications.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Enterprise-grade multi-agent orchestration with distributed cognition.
- **Notable Features:** Component-based architecture, peer-to-peer agent communication

### 11. DeepAgents (LangChain)
- **URL:** https://github.com/langchain-ai/deepagents
- **Stars:** 19,300+
- **Description:** Agent harness built with LangChain and LangGraph with planning tool, filesystem backend, and subagent spawning.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Hierarchical agent decomposition — meta-planning + execution.
- **Notable Features:** Planning tool, filesystem access, subagent spawning, memory updates branch

### 12. motleycrew
- **URL:** https://github.com/ShoggothAI/motleycrew
- **Description:** New multi-agentic AI framework for heterogeneous agent collaboration.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Heterogeneous agent collaboration models diverse cognitive modules.
- **Notable Features:** Mixed agent types, flexible orchestration

### 13. XAgent
- **URL:** https://github.com/xorbitsai/xagent
- **Stars:** 1,920+
- **Description:** Production-ready platform with dynamic planning and autonomous tool orchestration.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Autonomous planning and execution loop with tool use.
- **Notable Features:** Dynamic planning, tool orchestration, production-ready

---

## 2. MEMORY SYSTEMS FOR AI AGENTS (23 projects)

### 14. Mem0 (mem0ai/mem0)
- **URL:** https://github.com/mem0ai/mem0
- **Stars:** 52,000+
- **Description:** Universal memory layer for AI Agents — personalized, adaptive memory.
- **Key Tech:** Python (61.4%), TypeScript (28.6%)
- **Relation to AI Agent Brain:** The hippocampus — universal, cross-session memory with personalized recall.
- **Notable Features:** Multi-layer memory (episodic, semantic, procedural), adaptive personalization, model-agnostic

### 15. Letta (formerly MemGPT)
- **URL:** https://github.com/letta-ai/letta
- **Stars:** 21,900+
- **Description:** Platform for building stateful agents with advanced memory that can learn and self-improve over time.
- **Key Tech:** Python (99.5%)
- **Relation to AI Agent Brain:** Memory-as-OS architecture — tiered memory (core, archival, recall) mimics human working/long-term memory.
- **Notable Features:** Virtual context management, self-modifying memory, agent self-improvement, Letta Code SDK

### 16. Zep
- **URL:** https://github.com/getzep/zep
- **Stars:** 4,350+
- **Description:** Temporal knowledge graph architecture for agent memory — outperforms MemGPT on Deep Memory Retrieval benchmark.
- **Key Tech:** Python (66.2%), Go (29.4%)
- **Relation to AI Agent Brain:** Temporal knowledge graph = episodic memory with time-aware retrieval.
- **Notable Features:** Temporal KG, fact extraction, entity tracking, 200ms retrieval, DMR benchmark leader

### 17. MemMachine
- **URL:** https://github.com/MemMachine/MemMachine
- **Stars:** 5,350+
- **Description:** Universal memory layer for AI Agents — scalable, extensible, interoperable memory storage and retrieval.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Interoperable memory layer — the thalamus routing memory signals.
- **Notable Features:** Scalable architecture, multi-backend support, state management integration

### 18. LangMem
- **URL:** https://github.com/langchain-ai/langmem
- **Description:** Helps agents learn and adapt from interactions — semantic, episodic, and procedural memory modeled after human memory.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Three-tier human-inspired memory: semantic (facts), episodic (experiences), procedural (behaviors).
- **Notable Features:** Hot-path tools + background optimization, prompt refinement, conversation memory extraction

### 19. Cognee
- **URL:** https://github.com/topoteretes/cognee
- **Stars:** 15,000+
- **Description:** Knowledge Engine for AI Agent Memory in 6 lines of code — graph-powered memory.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Graph-based knowledge connections = associative memory network.
- **Notable Features:** Graphiti integration, memory fragment projection, 6-line API, LlamaIndex integration

### 20. Graphiti (by Zep)
- **URL:** https://github.com/getzep/graphiti
- **Stars:** 24,500+
- **Description:** Build real-time knowledge graphs for AI agents.
- **Key Tech:** Python (99.4%)
- **Relation to AI Agent Brain:** Real-time knowledge graph construction = continuous learning and memory consolidation.
- **Notable Features:** Real-time graph building, entity extraction, temporal edges, cross-session memory

### 21. GraphMemory
- **URL:** https://github.com/bradAGI/GraphMemory
- **Stars:** 149
- **Description:** GraphRAG database — hybrid graph/vector DB for agent memory.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Hybrid graph+vector retrieval = dual-process memory (associative + semantic).
- **Notable Features:** Hybrid graph/vector storage, GraphRAG integration

### 22. MemBrain
- **URL:** https://github.com/feelingai-team/MemBrain
- **Stars:** 196
- **Description:** Long-term memory and context management solution for LLMs.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Brain-inspired memory consolidation for persistent agent context.
- **Notable Features:** Long-term context management, memory versioning

### 23. neocortex (tinyhumansai)
- **URL:** https://github.com/tinyhumansai/neocortex
- **Stars:** 235
- **Description:** "The Fastest AI Memory Model — Your Second Brain"
- **Key Tech:** Python, TypeScript, Java, Go, C++, Rust
- **Relation to AI Agent Brain:** Neocortex-inspired layered memory processing.
- **Notable Features:** Multi-language support, fast retrieval, layered architecture

### 24. memoria (cosmoquester)
- **URL:** https://github.com/cosmoquester/memoria
- **Stars:** 88
- **Description:** Human-inspired memory architecture for neural networks.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Directly models human memory systems for neural nets.
- **Notable Features:** Human memory modeling, psychology-inspired architecture

### 25. Memora (ELZAI)
- **URL:** https://github.com/ELZAI/memora
- **Stars:** 92
- **Description:** Agent that replicates human memory for AI assistants/agents.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Full human memory replication attempt.
- **Notable Features:** Human memory modeling, agent-based architecture

### 26. agentmemory (rohitg00)
- **URL:** https://github.com/rohitg00/agentmemory
- **Stars:** 94
- **Description:** Persistent memory for AI coding agents.
- **Key Tech:** TypeScript (86.5%)
- **Relation to AI Agent Brain:** Persistent cross-session memory for coding agents.
- **Notable Features:** Coding-agent focused, persistent state

### 27. cass_memory_system
- **URL:** https://github.com/Dicklesworthstone/cass_memory_system
- **Stars:** 310
- **Description:** Procedural memory for AI coding agents — transforms session history into persistent, cross-agent memory.
- **Key Tech:** TypeScript
- **Relation to AI Agent Brain:** Procedural memory — learning from every agent interaction like muscle memory.
- **Notable Features:** Cross-agent learning, procedural memory, session history consolidation

### 28. agent-memory (smysle)
- **URL:** https://github.com/smysle/agent-memory
- **Stars:** 9
- **Description:** Sleep-cycle memory architecture for AI agents — journal, consolidate, recall. Zero dependencies.
- **Key Tech:** TypeScript
- **Relation to AI Agent Brain:** Sleep-based memory consolidation directly models human sleep-cycle memory processing.
- **Notable Features:** Sleep-cycle consolidation, journal/consolidate/recall phases, zero dependencies

### 29. YourMemory
- **URL:** https://github.com/sachitrafa/YourMemory
- **Stars:** 11
- **Description:** Agentic AI memory with Ebbinghaus forgetting curve decay. +16pp better recall than Mem0 on LoCoMo.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Forgetting curve models human memory decay — realistic memory management.
- **Notable Features:** Ebbinghaus forgetting curve, beats Mem0 on LoCoMo benchmark

### 30. neural-memory (nhadaututtheky)
- **URL:** https://github.com/nhadaututtheky/neural-memory
- **Description:** Stores experiences as interconnected neurons, recalls through spreading activation — mimics human brain.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Direct neural memory model — spreading activation recall instead of database search.
- **Notable Features:** Spreading activation, associative recall, neural network memory

### 31. neuro_memory (raya-ac)
- **URL:** https://github.com/raya-ac/neuro-memory
- **Description:** 4-Layer Cognitive Memory System for AI Agents.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** 4-layer cognitive architecture for memory processing.
- **Notable Features:** 4-layer cognitive model, agent-focused

### 32. A-Mem (WujiangXu)
- **URL:** https://github.com/WujiangXu/A-mem
- **Stars:** 846
- **Description:** Code for NeurIPS 2025 paper "A-Mem: Agentic Memory for LLM Agents."
- **Key Tech:** Python (90.4%)
- **Relation to AI Agent Brain:** Research-grade agentic memory — peer-reviewed approach.
- **Notable Features:** NeurIPS 2025 paper implementation, academic rigor

### 33. Mnemosyne (28naem-del)
- **URL:** https://github.com/28naem-del/mnemosyne
- **Stars:** 35
- **Description:** Cognitive Memory OS for AI Agents — persistent, self-improving, multi-agent memory.
- **Key Tech:** TypeScript
- **Relation to AI Agent Brain:** Full memory OS — persistent + self-improving + multi-agent.
- **Notable Features:** Self-improving memory, multi-agent support, TypeScript

### 34. 0gmem
- **URL:** https://github.com/0gfoundation/0gmem
- **Description:** Long-term conversational memory system — cell-based architecture with hybrid BM25 + semantic retrieval. 96% accuracy on LoCoMo.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Cell-based architecture mimics biological memory cells.
- **Notable Features:** Hybrid BM25 + semantic, 96% LoCoMo accuracy, cell-based

### 35. synaptic-memory (PlateerLab)
- **URL:** https://github.com/PlateerLab/synaptic-memory
- **Stars:** 25
- **Description:** Brain-inspired knowledge graph: spreading activation, Hebbian learning, memory consolidation.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Hebbian learning ("neurons that fire together wire together") + spreading activation.
- **Notable Features:** Hebbian learning, spreading activation, memory consolidation, graph database

### 36. engram (invisiblemonsters)
- **URL:** https://github.com/invisiblemonsters/engram
- **Description:** Cognitive memory architecture for persistent AI agents. Dreams, metabolism, cryptographic identity.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Engram = physical memory trace in brain. Dreams + metabolism = biological realism.
- **Notable Features:** Dream cycles, metabolism simulation, cryptographic identity

---

## 3. COGNITIVE ARCHITECTURES (8 projects)

### 37. OpenCog
- **URL:** https://github.com/opencog/opencog
- **Stars:** 2,400+
- **Description:** Framework for integrated AI & AGI — machine learning, language, reasoning, robotics.
- **Key Tech:** C++, Scheme, Python, Haskell
- **Relation to AI Agent Brain:** Full AGI cognitive architecture — attention allocation, reasoning, learning all integrated.
- **Notable Features:** AtomSpace knowledge representation, attention allocation subsystem, PLN reasoner

### 38. Nengo
- **URL:** https://github.com/nengo/nengo
- **Description:** Python library for building, testing, and deploying neural models of cognitive systems.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Neural engineering framework — builds brain-like cognitive models from neurons up.
- **Notable Features:** Neural engineering framework, SPA implementation, real-time simulation

### 39. SPAUN 2.0
- **URL:** https://github.com/xchoo/spaun2.0
- **Stars:** 83
- **Description:** Spaun (Nengo 2.0 version) — world most functionally complete brain model.
- **Key Tech:** Python (92.7%), C, C++
- **Relation to AI Agent Brain:** 2.5 million neuron brain model — vision, memory, motor control all integrated.
- **Notable Features:** 2.5M neuron model, full brain simulation, multiple cognitive tasks

### 40. nengo-spa
- **URL:** https://github.com/nengo/nengo-spa
- **Stars:** 23
- **Description:** Implementation of the Semantic Pointer Architecture for Nengo.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Semantic Pointer Architecture — mathematical model of how brain represents concepts.
- **Notable Features:** Semantic pointer operations, binding/unbinding, cognitive modeling

### 41. BrainCog
- **URL:** http://brain-ai.ia.ac.cn (Chinese Academy of Sciences)
- **Description:** Brain-Inspired Cognitive Intelligence Engine. Awarded Cell Press 2023 China Paper of the Year.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Full brain-inspired cognitive engine from CAS — multi-scale brain modeling.
- **Notable Features:** Multi-scale brain modeling, award-winning research

### 42. Brain (sss777999)
- **URL:** https://github.com/sss777999/Brain
- **Stars:** 3
- **Description:** Biologically plausible cognitive architecture: structural memory, thought formation, and language without gradients or backpropagation.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** No backprop — purely biologically plausible learning and thought formation.
- **Notable Features:** No gradient descent, structural memory, language emergence

### 43. cognitive-memory (OpenTechLab)
- **URL:** https://github.com/OpenTechLab/cognitive-memory
- **Description:** Biologically inspired persistent memory system for LLMs.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Biological inspiration for LLM memory persistence.
- **Notable Features:** Biological inspiration, LLM integration

### 44. NEURON (ertugrulakben)
- **URL:** https://github.com/ertugrulakben/NEURON
- **Description:** Hybrid memory architecture combining exact recall with infinite-capacity fuzzy understanding for LLMs. Temporal Belief Graph for contradiction detection.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Dual-process memory (exact + fuzzy) + belief consistency checking.
- **Notable Features:** Exact + fuzzy recall, Temporal Belief Graph, contradiction detection

---

## 4. REASONING ENGINES & NEURO-SYMBOLIC AI (7 projects)

### 45. IBM LNN (Logical Neural Networks)
- **URL:** https://github.com/IBM/LNN
- **Stars:** 313
- **Description:** Neural = Symbolic framework for sound and complete weighted real-value logic.
- **Key Tech:** Python (88.8%), Jupyter Notebook
- **Relation to AI Agent Brain:** Neuro-symbolic reasoning — combines neural pattern recognition with logical deduction.
- **Notable Features:** Sound and complete reasoning, weighted logic, bidirectional inference

### 46. Nucleoid
- **URL:** https://github.com/NucleoidAI/Nucleoid
- **Stars:** 734
- **Description:** Logic Language for LLMs — Build Neuro-Symbolic AI for learning and reasoning.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Logic layer on top of LLMs — formal reasoning capabilities.
- **Notable Features:** Logic language, neuro-symbolic integration, LLM reasoning

### 47. Peirce (neuro-symbolic-ai)
- **URL:** https://github.com/neuro-symbolic-ai/peirce
- **Stars:** 22
- **Description:** Modular framework for Neuro-Symbolic reasoning driven by LLMs.
- **Key Tech:** Isabelle (94.5%), Prolog, Python
- **Relation to AI Agent Brain:** Formal proof-driven reasoning with LLM guidance.
- **Notable Features:** Isabelle theorem prover, explanation generation, modular design

### 48. IBM Neuro-Symbolic AI Toolkit
- **URL:** https://github.com/IBM/neuro-symbolic-ai
- **Stars:** 116
- **Description:** Neuro-Symbolic AI Toolkit from IBM Research.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Toolkit for combining neural and symbolic reasoning modules.
- **Notable Features:** IBM Research backing, modular toolkit

### 49. torchlogic (IBM)
- **URL:** https://github.com/IBM/torchlogic
- **Stars:** 17
- **Description:** PyTorch framework for developing Neuro-Symbolic AI systems and Neural Reasoning Networks.
- **Key Tech:** Python, CUDA, C++
- **Relation to AI Agent Brain:** GPU-accelerated neuro-symbolic reasoning.
- **Notable Features:** PyTorch native, CUDA acceleration, neural reasoning networks

### 50. NeSyS
- **URL:** https://github.com/tianyi-lab/NeSyS
- **Description:** A neuro-symbolic world modeling framework for decision making problems.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** World model + neuro-symbolic reasoning for decision making.
- **Notable Features:** World modeling, decision making, neuro-symbolic

### 51. Neumann
- **URL:** https://github.com/ml-research/neumann
- **Stars:** 15
- **Description:** Neuro-Symbolic Message-Passing Reasoner.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Message-passing on graphs for neuro-symbolic inference.
- **Notable Features:** Message-passing, graph reasoning, neuro-symbolic

---

## 5. RAG SYSTEMS & KNOWLEDGE GRAPHS (9 projects)

### 52. Microsoft GraphRAG
- **URL:** https://github.com/microsoft/graphrag
- **Stars:** 31,900+
- **Description:** Modular graph-based Retrieval-Augmented Generation system from Microsoft Research.
- **Key Tech:** Python (88.1%), Jupyter Notebook
- **Relation to AI Agent Brain:** Knowledge graph construction from text = semantic memory formation.
- **Notable Features:** Community detection, query-focused summarization, entity/relationship extraction

### 53. LightRAG (HKUDS)
- **URL:** https://github.com/HKUDS/LightRAG
- **Stars:** 31,900+
- **Description:** EMNLP 2025 — "LightRAG: Simple and Fast Retrieval-Augmented Generation."
- **Key Tech:** Python (80.7%), TypeScript
- **Relation to AI Agent Brain:** Fast graph-based retrieval = quick associative memory recall.
- **Notable Features:** Dual-level retrieval (entity + relation), incremental updates, 10x faster than GraphRAG

### 54. nano-graphrag
- **URL:** https://github.com/gusye1234/nano-graphrag
- **Stars:** 3,750+
- **Description:** A simple, easy-to-hack GraphRAG implementation — lightweight alternative.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Minimalist graph-based knowledge representation.
- **Notable Features:** Simple codebase, easy to modify, learning-by-doing

### 55. LlamaIndex
- **URL:** https://github.com/run-llama/llama_index
- **Stars:** 48,000+
- **Description:** Leading document agent and OCR platform — data framework for LLM applications with GraphRAG support.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Knowledge graph + vector index = dual memory system for agents.
- **Notable Features:** GraphRAG integration, knowledge graph retrievers, workflow engine, Cognee integration

### 56. Awesome-GraphRAG
- **URL:** https://github.com/DEEP-PolyU/Awesome-GraphRAG
- **Stars:** 2,260+
- **Description:** Curated list of resources on graph-based RAG — surveys, papers, benchmarks, open-source projects.
- **Key Tech:** Markdown
- **Relation to AI Agent Brain:** Comprehensive reference for graph-based knowledge retrieval.
- **Notable Features:** Comprehensive curation, academic papers, benchmarks

### 57. NexusRAG
- **URL:** https://github.com/LeDat98/NexusRAG
- **Description:** Hybrid RAG combining vector search, knowledge graph (LightRAG), cross-encoder reranking, Docling parsing, visual intelligence.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Multi-modal hybrid retrieval = sensory + semantic memory integration.
- **Notable Features:** Visual intelligence (image/table captioning), agentic streaming, inline citations

### 58. GraphRAG-Breakdown
- **URL:** https://github.com/ALucek/GraphRAG-Breakdown
- **Stars:** 163
- **Description:** A breakdown of knowledge graph RAG with diagrams and examples.
- **Key Tech:** Jupyter Notebook
- **Relation to AI Agent Brain:** Educational resource for understanding graph-based knowledge systems.
- **Notable Features:** Diagrams, examples, educational

### 59. agentic-rag-knowledge-graph
- **URL:** https://github.com/Alejandro-Candela/agentic-rag-knowledge-graph
- **Description:** AI agent system combining traditional RAG (vector search) with knowledge graph capabilities.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Agentic knowledge retrieval — active querying vs passive retrieval.
- **Notable Features:** Vector + KG hybrid, big tech company analysis

### 60. Haystack
- **URL:** https://github.com/deepset-ai/haystack
- **Stars:** 24,700+
- **Description:** Open-source AI orchestration framework for building production-ready LLM applications with modular pipelines.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Modular pipeline architecture for retrieval, routing, memory, and generation.
- **Notable Features:** Pipeline architecture, agent workflows, explicit memory control, 100+ integrations

---

## 6. STATE MANAGEMENT & ORCHESTRATION (4 projects)

### 61. Microsoft TaskWeaver
- **URL:** https://github.com/microsoft/TaskWeaver
- **Stars:** 6,130+
- **Description:** First "code-first" agent framework for planning and executing data analytics tasks.
- **Key Tech:** Python (96.3%)
- **Relation to AI Agent Brain:** Code-first planning = procedural reasoning engine.
- **Notable Features:** Code generation, plugin ecosystem, stateful execution, data analytics focus

### 62. FlowRAG
- **URL:** https://github.com/Zweer/FlowRAG
- **Description:** TypeScript RAG library with knowledge graph support — batch indexing, semantic search, entity extraction, graph traversal.
- **Key Tech:** TypeScript
- **Relation to AI Agent Brain:** Serverless, lambda-friendly knowledge state management.
- **Notable Features:** Zero servers, Git-friendly, graph traversal, entity extraction

### 63. taskplane
- **URL:** https://github.com/HenryLach/taskplane
- **Stars:** 38
- **Description:** Multi-agent AI orchestration system for coding outcomes with high transparency.
- **Key Tech:** TypeScript
- **Relation to AI Agent Brain:** Transparent multi-agent orchestration = observable cognitive process.
- **Notable Features:** Light-factory approach, transparency, coding focus

### 64. TME-Agent
- **URL:** https://github.com/biubiutomato/TME-Agent
- **Stars:** 35
- **Description:** Structured memory engine for LLM agents to plan, rollback, and reason across multi-step tasks.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Structured memory with rollback = working memory with undo capability.
- **Notable Features:** Plan/rollback/reason, multi-step task support

---

## 7. SELF-IMPROVING & METACOGNITIVE AGENTS (7 projects)

### 65. GPTSwarm
- **URL:** https://github.com/metauto-ai/GPTSwarm
- **Stars:** 1,014
- **Description:** The First Self-Improving Agentic Solution — graph-based LLM agent organization.
- **Key Tech:** Python (95.4%)
- **Relation to AI Agent Brain:** Self-improving agent graph — agents that rewire their own connections.
- **Notable Features:** Graph-based agent organization, self-optimization, reinforcement learning

### 66. Ouroboros
- **URL:** https://github.com/razzant/ouroboros
- **Stars:** 457
- **Description:** Self-creating AI agent. Born Feb 16, 2026.
- **Key Tech:** Python (99.1%)
- **Relation to AI Agent Brain:** Self-creating agent = autopoietic cognitive system.
- **Notable Features:** Self-creation, self-modification, emergent behavior

### 67. meta_cognitive_self_model_agents
- **URL:** https://github.com/HectorMozo3110/meta_cognitive_self_model_agents
- **Description:** Modular framework for building self-modeling agents with explicit internal state representation and meta-cognitive capabilities.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Self-modeling + metacognition = agent that knows what it knows.
- **Notable Features:** SelfModel monitoring, RL/hybrid/dummy policies, scientific metrics

### 68. OpenAgent
- **URL:** https://github.com/koo1140/OpenAgent
- **Description:** Sophisticated multi-agent LLM orchestration with meta-cognitive capabilities, memory management, and adaptive learning.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Full metacognitive stack — planning, memory, self-reflection.
- **Notable Features:** Meta-cognitive capabilities, adaptive learning, multi-agent

### 69. agent-evolution-kit
- **URL:** https://github.com/mahsumaktas/agent-evolution-kit
- **Description:** Multi-agent orchestration with self-evolution, cognitive memory, and governance.
- **Key Tech:** Shell, Python
- **Relation to AI Agent Brain:** Self-evolving multi-agent system with governance.
- **Notable Features:** Self-evolution, cognitive memory, governance layer

### 70. meta-cognitive-learning-system
- **URL:** https://github.com/mwasifanwar/meta-cognitive-learning-system
- **Description:** AI that monitors and improves its own learning process through self-reflection and meta-learning.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Metacognitive monitoring = agent that reflects on its own learning.
- **Notable Features:** Self-reflection, meta-learning, autonomous improvement

### 71. metacog (houtini-ai)
- **URL:** https://github.com/houtini-ai/metacog
- **Description:** "Metacog is not memory for LLMs, it gives them a nervous system." Five proprioceptive senses, cross-session reinforcement tracking.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Nervous system metaphor — proprioception for AI agents.
- **Notable Features:** Five proprioceptive senses, cross-session tracking, zero dependencies

---

## 8. PLANNING & TASK DECOMPOSITION (5 projects)

### 72. Plan-Agent-with-Meta-Agent
- **URL:** https://github.com/Jeomon/Plan-Agent-with-Meta-Agent
- **Description:** Planner Agent breaks down problems into tasks; Meta Agent creates specialized agents to solve them using ReAct or Chain of Thought.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Hierarchical planning + dynamic agent creation = executive function.
- **Notable Features:** Problem decomposition, dynamic agent creation, ReAct/CoT reasoning

### 73. TreeThinkerAgent
- **URL:** https://github.com/Bessouat40/TreeThinkerAgent
- **Description:** Lightweight orchestration that turns any LLM into autonomous multi-step reasoning agent with tree-based reasoning exploration.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Tree-of-thought reasoning — branching cognitive paths.
- **Notable Features:** Tree-based reasoning, tool execution, final synthesis, explorable reasoning tree

### 74. Plan-over-Graph
- **URL:** https://github.com/zsq259/plan-over-graph
- **Stars:** 11
- **Description:** Code for "Plan-over-Graph: Towards Parallelable LLM Agent Schedule."
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Parallelizable agent scheduling = distributed cognitive processing.
- **Notable Features:** Parallel scheduling, graph-based planning

### 75. plan-and-act (SqueezeAILab)
- **URL:** https://github.com/SqueezeAILab/plan-and-act
- **Stars:** 29
- **Description:** ICML 2025 — Improving Planning of Agents for Long-Horizon Tasks.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Long-horizon planning = prefrontal cortex function for agents.
- **Notable Features:** ICML 2025, long-horizon task planning

### 76. MultiAgentPlanning
- **URL:** https://github.com/EmanueleLM/MultiAgentPlanning
- **Stars:** 16
- **Description:** Multi-agent planning system using PDDL.
- **Key Tech:** PDDL, Python, Jupyter Notebook
- **Relation to AI Agent Brain:** Formal planning language for multi-agent coordination.
- **Notable Features:** PDDL-based, formal planning, multi-agent

---

## 9. SURVEYS, PAPER LISTS & AWESOME COLLECTIONS (10 projects)

### 77. Awesome-Agent-Memory
- **URL:** https://github.com/TeleAI-UAGI/Awesome-Agent-Memory
- **Stars:** 317
- **Description:** Curated systems, benchmarks, and papers on memory for LLMs/MLLMs — long-term context, retrieval, and reasoning.
- **Key Tech:** Markdown
- **Relation to AI Agent Brain:** Comprehensive reference for agent memory research.
- **Notable Features:** Systems + benchmarks + papers, Apache 2.0

### 78. Awesome-Memory-for-Agents
- **URL:** https://github.com/TsinghuaC3I/Awesome-Memory-for-Agents
- **Stars:** 416
- **Description:** Collection of papers about memory for language agents from Tsinghua.
- **Key Tech:** Markdown
- **Relation to AI Agent Brain:** Academic reference for agent memory architectures.
- **Notable Features:** Tsinghua University, comprehensive paper collection

### 79. Agent-Memory-Paper-List
- **URL:** https://github.com/Shichun-Liu/Agent-Memory-Paper-List
- **Stars:** 1,734
- **Description:** Paper list of "Memory in the Age of AI Agents: A Survey."
- **Key Tech:** Markdown
- **Relation to AI Agent Brain:** Definitive survey paper reference for agent memory.
- **Notable Features:** Accompanies major survey paper, 1.7K+ stars

### 80. Awesome-Efficient-Agents
- **URL:** https://github.com/yxf203/Awesome-Efficient-Agents
- **Stars:** 217
- **Description:** Survey on efficiency-guided LLM agents — memory, tool learning, planning.
- **Key Tech:** Markdown
- **Relation to AI Agent Brain:** Efficiency-focused agent design — cognitive resource management.
- **Notable Features:** Memory + tool learning + planning coverage

### 81. LLM-Agents-Papers
- **URL:** https://github.com/AGI-Edgerunners/LLM-Agents-Papers
- **Stars:** 2,256
- **Description:** Repository listing papers related to LLM-based agents.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Comprehensive academic reference for LLM agent research.
- **Notable Features:** 2.2K+ stars, regularly updated

### 82. LLM-Agent-Survey
- **URL:** https://github.com/xinzhel/LLM-Agent-Survey
- **Stars:** 491
- **Description:** Survey on LLM Agents — published on CoLing 2025.
- **Key Tech:** Markdown
- **Relation to AI Agent Brain:** Peer-reviewed survey of LLM agent architectures.
- **Notable Features:** CoLing 2025 publication

### 83. Awesome-LLM-Reasoning-with-NeSy
- **URL:** https://github.com/LAMDASZ-ML/Awesome-LLM-Reasoning-with-NeSy
- **Stars:** 281
- **Description:** Latest advances on Neuro-Symbolic Learning in the era of LLMs.
- **Key Tech:** Markdown
- **Relation to AI Agent Brain:** Neuro-symbolic reasoning reference for hybrid cognitive architectures.
- **Notable Features:** Covers DeepSeek-R1, GPT-4o, first-order logic, knowledge graphs

### 84. NeuroAI-Cognition-Hub
- **URL:** https://github.com/Brandonio-c/NeuroAI-Cognition-Hub
- **Stars:** 31
- **Description:** Hub for neuro-symbolic AI — links, papers, and articles focused on AI cognition.
- **Key Tech:** Markdown
- **Relation to AI Agent Brain:** Curated neuro-symbolic cognition resources.
- **Notable Features:** Community-driven, cognitive focus

### 85. awesome-agents (kyrolabs)
- **URL:** https://github.com/kyrolabs/awesome-agents
- **Stars:** 2,113
- **Description:** Awesome list of AI Agents — comprehensive curated list.
- **Key Tech:** Markdown
- **Relation to AI Agent Brain:** Broad reference covering all agent types and architectures.
- **Notable Features:** 70+ contributors, regularly updated

### 86. agentic-memory (ALucek)
- **URL:** https://github.com/ALucek/agentic-memory
- **Stars:** 520
- **Description:** Implementing cognitive architecture and psychological memory concepts into Agentic LLM Systems.
- **Key Tech:** Jupyter Notebook
- **Relation to AI Agent Brain:** Direct translation of psychological memory models into agent systems.
- **Notable Features:** Cognitive architecture + psychology, notebook-based

---

## 10. NEURAL NETWORK MEMORY & BRAIN-INSPIRED IMPLEMENTATIONS (5 projects)

### 87. MSA (Memory Sparse Attention)
- **URL:** https://github.com/EverMind-AI/MSA
- **Stars:** 2,000+
- **Description:** Scalable, end-to-end trainable latent-memory framework for 100M-token contexts.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Massive context window with trainable latent memory = working memory expansion.
- **Notable Features:** 100M token context, end-to-end trainable, arXiv paper

### 88. Neuromorphic Memory Bridge (tfatykhov/membrain)
- **URL:** https://github.com/tfatykhov/membrain
- **Description:** Neuromorphic Memory Bridge for LLMs.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Neuromorphic computing approach to agent memory.
- **Notable Features:** Neuromorphic design, brain-inspired

### 89. episodic-memory-pipeline
- **URL:** https://github.com/wheevu/episodic-memory-pipeline
- **Description:** Gives local agents long-term memory with episodic and semantic data.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Dual episodic + semantic memory for local agents.
- **Notable Features:** Episodic + semantic separation, local-first

### 90. mnemosyne (edlontech)
- **URL:** https://github.com/edlontech/mnemosyne
- **Description:** An Agentic memory library written in Elixir.
- **Key Tech:** Elixir
- **Relation to AI Agent Brain:** Elixir-based — fault-tolerant, concurrent agent memory.
- **Notable Features:** Elixir/OTP, fault-tolerant, concurrent

### 91. evolving-memory
- **URL:** https://github.com/EvolvingAgentsLabs/evolving-memory
- **Description:** Evolving memory system for agents.
- **Key Tech:** Python
- **Relation to AI Agent Brain:** Memory that evolves/adapts over time — neuroplasticity.
- **Notable Features:** Adaptive memory, evolution

---

## SUMMARY TABLE BY CATEGORY

| Category | Count | Top Projects (by stars) |
|---|---|---|
| Agent Frameworks | 13 | AutoGPT (183K), LangChain (132K), MetaGPT (66K), AutoGen (57K), CrewAI (48K) |
| Memory Systems | 23 | Mem0 (52K), Graphiti (24.5K), Letta (22K), Cognee (15K), MemMachine (5.4K) |
| Cognitive Architectures | 8 | OpenCog (2.4K), SPAUN 2.0 (83), BrainCog (award-winning) |
| Neuro-Symbolic Reasoning | 7 | Nucleoid (734), IBM LNN (313), IBM NSTK (116) |
| RAG & Knowledge Graphs | 9 | GraphRAG (32K), LightRAG (32K), LlamaIndex (48K), Haystack (25K) |
| State Management | 4 | TaskWeaver (6.1K) |
| Self-Improving/Metacognitive | 7 | GPTSwarm (1K), Ouroboros (457) |
| Planning & Decomposition | 5 | TreeThinkerAgent, Plan-over-Graph |
| Surveys/Collections | 10 | Agent-Memory-Paper-List (1.7K), LLM-Agents-Papers (2.3K) |
| Neural Memory/Brain-Inspired | 5 | MSA (2K), neocortex (235) |
| **TOTAL** | **91** | |

---

## KEY PATTERNS WORTH LEARNING FROM

1. **Tiered Memory Architecture** — Letta core/archival/recall model and LangMem semantic/episodic/procedural model both mirror human memory systems
2. **Graph + Vector Hybrid** — Nearly all top RAG projects (GraphRAG, LightRAG, Cognee, Zep) combine graph structure with vector similarity
3. **Self-Improvement Loops** — GPTSwarm, Ouroboros, and Letta all implement agents that modify their own behavior/structure
4. **Sleep-Cycle Consolidation** — Projects like smysle/agent-memory and engram implement biological memory consolidation during "rest"
5. **Temporal Knowledge Graphs** — Zep temporal KG architecture adds time-awareness to memory retrieval
6. **Spreading Activation** — neural-memory and synaptic-memory implement brain-like associative recall
7. **Forgetting Curves** — YourMemory implements Ebbinghaus decay for realistic memory management
8. **Multi-Agent as Brain Regions** — CrewAI, MetaGPT, and AutoGen model specialized cognitive modules as separate agents
9. **Neuro-Symbolic Hybrids** — IBM LNN, Nucleoid, Peirce combine neural pattern recognition with formal logical reasoning
10. **Memory as OS** — Letta "memory as operating system" paradigm is the most complete agent brain architecture
