# CUTTING-EDGE AI AGENT MEMORY RESEARCH
# Dec 2025 - April 2026 | Non-Productized Papers
# Search date: 2026-04-05
# Sources: arXiv API (37 queries, 765+ papers scanned)
# Excluded (already known): ACC/CCS (2601.11653), D-MEM (2603.14597),
#   GDWM (2601.12906), S3-Attention (2601.17702), ContextBudget (2604.01664),
#   ElephantBroker (2603.25097)
# Total unique papers scanned: 765+
# Papers curated below: 40

===============================================================================

TOP TIER HIGHEST IMPACT - April 2026 (Latest)

PAPER #1 | arXiv:2604.01560 | 2026-04-02
TITLE: DeltaMem: Towards Agentic Memory Management via Reinforcement Learning
AUTHORS: Qi Zhang, Shen Huang, Chu Liu
CATEGORY: RL-based Memory Management
KEY FINDING: Uses reinforcement learning to dynamically decide what memories to keep, consolidate, or forget
NOVELTY: First to apply RL directly to memory management decisions rather than heuristic rules
WHY IT MATTERS: Moves beyond static memory policies (TTL, frequency-based) to learned adaptive memory control that optimizes for downstream task performance
PRODUCTIZATION STATUS: Pre-product, academic prototype

PAPER #2 | arXiv:2604.01707 | 2026-04-02
TITLE: Memory in the LLM Era: Modular Architectures and Strategies in a Unified Framework
AUTHORS: Yanchen Wu, Tenghui Lin, Yingli Zhou
CATEGORY: Survey / Unified Framework
KEY FINDING: Comprehensive unified framework categorizing all modular memory architectures
NOVELTY: First modular unification of the fragmented memory research landscape with standardized evaluation
WHY IT MATTERS: Essential reference for comparing approaches and identifying gaps
PRODUCTIZATION STATUS: Survey/reference paper

PAPER #3 | arXiv:2604.00067 | 2026-03-31
TITLE: Temporal Memory for Resource-Constrained Agents: Continual Learning via Stochastic Compress-Add-Smooth
AUTHORS: Michael Chertkov
CATEGORY: Temporal Memory / Continual Learning
KEY FINDING: Novel stochastic Compress-Add-Smooth (CAS) operator for temporal memory under tight compute budgets
NOVELTY: CAS operator enables continual learning with bounded memory, mathematically proven convergence properties
WHY IT MATTERS: Critical for edge deployment and real-time streaming where memory cannot grow unbounded
PRODUCTIZATION STATUS: Theoretical, no product reference

PAPER #4 | arXiv:2603.29493 | 2026-03-31
TITLE: MemFactory: Unified Inference & Training Framework for Agent Memory
AUTHORS: Ziliang Guo, Ziheng Li, Bo Tang
CATEGORY: Memory Framework / Infrastructure
KEY FINDING: Unified framework treating memory as a trainable component from training through inference
NOVELTY: Bridges the training/inference gap - memory is optimized end-to-end, not bolted on post-training
WHY IT MATTERS: First framework enabling memory components to be trained alongside model weights
PRODUCTIZATION STATUS: Framework, not productized

PAPER #5 | arXiv:2604.00131 | 2026-03-31
TITLE: Oblivion: Self-Adaptive Agentic Memory Control through Decay-Driven Activation
AUTHORS: Ashish Rana, Chia-Chien Hung, Qumeng Sun
CATEGORY: Memory Decay / Forgetting
KEY FINDING: Learnable decay mechanisms that model biological forgetting for adaptive memory control
NOVELTY: Treats forgetting as an optimizable feature with learnable decay rates
WHY IT MATTERS: Enables agents to automatically prune irrelevant memories, reducing noise and retrieval cost
PRODUCTIZATION STATUS: Not productized

PAPER #6 | arXiv:2604.00224 | 2026-03-31
TITLE: APEX-EM: Non-Parametric Online Learning via Structured Procedural-Episodic Experience Replay
AUTHORS: Pratyay Banerjee, Masud Moshtaghi, Ankit Chadha
CATEGORY: Episodic Memory / Experience Replay
KEY FINDING: Separates procedural (how-to) from episodic (what-happened) memory in experience replay
NOVELTY: Mimics human dual-process memory system for more sample-efficient agent learning
WHY IT MATTERS: Dual-process architecture enables agents to generalize skills while remembering specific experiences
PRODUCTIZATION STATUS: Not productized

PAPER #7 | arXiv:2603.27910 | 2026-03-29
TITLE: GAAMA: Graph Augmented Associative Memory for Agents
AUTHORS: Swarna Kamal Paul, Shubhendu Sharma, Nitin Sareen
CATEGORY: Graph Memory / Associative Memory
KEY FINDING: Combines graph-structured organization with associative (content-addressable) memory retrieval
NOVELTY: Merges structured graph storage + Hopfield-like associative recall
WHY IT MATTERS: Best of both worlds - organized storage AND fast content-addressable retrieval
PRODUCTIZATION STATUS: Not productized

PAPER #8 | arXiv:2603.26177 | 2026-03-28
TITLE: Beyond Completion: Probing Cumulative State Tracking to Predict LLM Agent Performance
AUTHORS: Multiple authors
CATEGORY: State Tracking
KEY FINDING: Probes cumulative agent state representations to predict performance before task completion
NOVELTY: Early performance prediction from internal state tracking, enabling mid-course correction
WHY IT MATTERS: Could enable self-monitoring agents that self-correct before failing
PRODUCTIZATION STATUS: Not productized

PAPER #9 | arXiv:2603.13644 | 2026-03-13
TITLE: StatePlane: A Cognitive State Plane for Long-Horizon AI Systems Under Bounded Context
AUTHORS: Sasank Annapureddy, John Mulcahy, Anjaneya Prasad Thamatani
CATEGORY: Cognitive State Representation
KEY FINDING: Explicit cognitive state representation decoupled from context window constraints
NOVELTY: Maintains coherent decision state entirely outside the context window
WHY IT MATTERS: Fundamentally different from all context-window-centric approaches
PRODUCTIZATION STATUS: Not productized

PAPER #10 | arXiv:2603.22096 | 2026-03-23
TITLE: GSEM: Graph-based Self-Evolving Memory for Experience Augmented Clinical Reasoning
AUTHORS: Multiple authors
CATEGORY: Self-Evolving Graph Memory
KEY FINDING: Memory graphs that self-evolve through experience accumulation
NOVELTY: Memory structure evolves organically with usage, not manually designed
WHY IT MATTERS: Demonstrates self-improving agents through memory-driven experience
PRODUCTIZATION STATUS: Not productized

PAPER #11 | arXiv:2603.21564 | 2026-03-23
TITLE: Toward a Theory of Hierarchical Memory for Language Agents
AUTHORS: Multiple authors
CATEGORY: Hierarchical Memory Theory
KEY FINDING: First formal theoretical framework for hierarchical memory in language agents
NOVELTY: Mathematical grounding for why/when multi-tier memory (working/episodic/semantic) works
WHY IT MATTERS: Provides design principles for multi-tier memory architectures
PRODUCTIZATION STATUS: Theoretical/academic

PAPER #12 | arXiv:2603.17244 | 2026-03-18
TITLE: Graph-Native Cognitive Memory: Formal Belief Revision Semantics for Versioned Memory (Kumiho)
AUTHORS: Young Bin Park
CATEGORY: Cognitive Memory / Belief Revision
KEY FINDING: Kumiho integrates immutable revisions with mutable tag pointers backed by AGM belief revision theory
NOVELTY: First to apply formal AGM belief revision theory to agent memory
WHY IT MATTERS: Mathematical guarantees for memory consistency and safe belief updates
PRODUCTIZATION STATUS: Not productized

PAPER #13 | arXiv:2603.15280 | 2026-03-16
TITLE: Advancing Multimodal Agent Reasoning with Long-Term Neuro-Symbolic Memory
AUTHORS: Rongjie Jiang, Jianwei Wang, Gengda Zhao
CATEGORY: Neuro-Symbolic Memory
KEY FINDING: Combines neural (intuitive) and symbolic (deductive) memory for multimodal reasoning
NOVELTY: Bridges System 1 (neural pattern matching) and System 2 (symbolic logic) in memory
WHY IT MATTERS: Agents can both recognize patterns AND perform deductive reasoning over memories
PRODUCTIZATION STATUS: Not productized

PAPER #14 | arXiv:2603.29193 | 2026-03-31
TITLE: Developing Adaptive Context Compression Techniques for LLMs in Long-Running Interactions
AUTHORS: Payal Fofadiya, Sunil Tiwari
CATEGORY: Adaptive Context Compression
KEY FINDING: Dynamically adjusts compression ratio based on real-time interaction complexity
NOVELTY: Complexity-aware compression that adapts per-turn, not a fixed ratio
WHY IT MATTERS: Practical solution for maintaining quality in long-running agent sessions
PRODUCTIZATION STATUS: Not productized

PAPER #15 | arXiv:2603.18718 | 2026-03-19
TITLE: MemMA: Coordinating the Memory Cycle through Multi-Agent Reasoning and In-Situ Self-Evolution
AUTHORS: Multiple authors
CATEGORY: Multi-Agent Memory Coordination
KEY FINDING: Multi-agent debate coordinates the full memory lifecycle (encode, store, retrieve, forget)
NOVELTY: Uses multi-agent reasoning to manage memory holistically
WHY IT MATTERS: More robust memory decisions through consensus-based management
PRODUCTIZATION STATUS: Not productized

PAPER #16 | arXiv:2602.18493 | 2026-02-13
TITLE: Learning to Remember: End-to-End Training of Memory Agents for Long-Context Reasoning
AUTHORS: Kehao Zhang, Shangtong Gui, Sheng Yang
CATEGORY: End-to-End Memory Training
KEY FINDING: Unified Memory Agent (UMA) trained end-to-end for active remembering, state tracking, contradiction resolution
NOVELTY: Memory is actively trained rather than passively retrieved (RAG paradigm)
WHY IT MATTERS: Moves from passive retrieval to active memory management
PRODUCTIZATION STATUS: Not productized

PAPER #17 | arXiv:2602.13933 | 2026-02-15
TITLE: HyMem: Hybrid Memory Architecture with Dynamic Retrieval Scheduling
AUTHORS: Xiaochen Zhao, Kaikai Wang, Xiaowen Zhang
CATEGORY: Hybrid Memory
KEY FINDING: Dynamic scheduler chooses between compressed (efficient) and raw (precise) representations per query
NOVELTY: Intelligent routing based on query complexity, not single representation
WHY IT MATTERS: Optimal efficiency-accuracy tradeoff on a per-query basis
PRODUCTIZATION STATUS: Not productized

PAPER #18 | arXiv:2602.13530 | 2026-02-13
TITLE: REMem: Reasoning with Episodic Memory in Language Agent
AUTHORS: Yiheng Shu, Saisri Padmaja Jonnalagedda, Xiang Gao
CATEGORY: Episodic Reasoning
KEY FINDING: Formalizes episodic recollection with spatiotemporal grounding for language agents
NOVELTY: First to formalize episodicity (when/where) in language agent memory
WHY IT MATTERS: Enables agents to reason about events in their proper temporal/spatial context
PRODUCTIZATION STATUS: Not productized

PAPER #19 | arXiv:2602.09712 | 2026-02-10
TITLE: TraceMem: Weaving Narrative Memory Schemata from User Conversational Traces
AUTHORS: Yiming Shu, Pei Liu, Tiange Zhang
CATEGORY: Narrative Memory
KEY FINDING: Three-stage pipeline constructs narrative schemata preserving dialogue coherence
NOVELTY: Captures story-like narrative structure instead of isolated memory snippets
WHY IT MATTERS: Maintains coherence for long-term personalized interactions
PRODUCTIZATION STATUS: Not productized

PAPER #20 | arXiv:2602.08369 | 2026-02-09
TITLE: MemAdapter: Fast Alignment across Agent Memory Paradigms via Generative Subgraph Retrieval
AUTHORS: Xin Zhang, Kailai Yang, Chenyue Li
CATEGORY: Memory Paradigm Unification
KEY FINDING: Unifies explicit, parametric, and latent memory paradigms in single architecture
NOVELTY: First cross-paradigm memory fusion system
WHY IT MATTERS: Enables agents to leverage different memory types flexibly
PRODUCTIZATION STATUS: Not productized

PAPER #21 | arXiv:2602.08382 | 2026-02-09
TITLE: Dynamic Long Context Reasoning over Compressed Memory via End-to-End RL
AUTHORS: Zhuoen Chen, Dongfang Li, Meishan Zhang
CATEGORY: RL-based Memory Compression
KEY FINDING: RL learns optimal chunk-wise compression and selective recall tradeoffs end-to-end
NOVELTY: RL-optimized compression-recall balance, no manual thresholds
WHY IT MATTERS: Automatic optimal compression for any context length
PRODUCTIZATION STATUS: Not productized

PAPER #22 | arXiv:2602.15895 | 2026-02-11
TITLE: Understand Then Memory: A Cognitive Gist-Driven RAG Framework
AUTHORS: Pengcheng Zhou, Haochen Li, Zhiqiang Nie
CATEGORY: Cognitive Gist Memory
KEY FINDING: CogitoRAG extracts semantic gist before storage, inspired by human episodic memory
NOVELTY: Models gist extraction (human memory abstraction) rather than raw text retrieval
WHY IT MATTERS: More robust retrieval through semantic understanding first
PRODUCTIZATION STATUS: Not productized

PAPER #23 | arXiv:2602.12204 | 2026-02-12
TITLE: Learning to Forget Attention: Memory Consolidation for Adaptive Compute Reduction
AUTHORS: Ibne Farabi Shihab, Sanjeda Akter, Anuj Sharma
CATEGORY: Attention Consolidation
KEY FINDING: 88% of attention operations retrieve info already predictable from hidden state
NOVELTY: Attention demand should decay as patterns consolidate into model state
WHY IT MATTERS: Massive compute savings from learned attention sparsification
PRODUCTIZATION STATUS: Not productized

PAPER #24 | arXiv:2602.03784 | 2026-02-03
TITLE: Context Compression via Explicit Information Transmission
AUTHORS: Jiangnan Ye, Hanqi Yan, Zhenyi Shen
CATEGORY: Explicit Information Compression
KEY FINDING: Dedicated compressor architecture outperforms re-using LLM self-attention for compression
NOVELTY: Decouples compression from generation, avoiding structural limitations of self-attention
WHY IT MATTERS: More efficient and effective than training LLMs to compress themselves
PRODUCTIZATION STATUS: Not productized

PAPER #25 | arXiv:2602.01719 | 2026-02-02
TITLE: COMI: Coarse-to-fine Context Compression via Marginal Information Gain
AUTHORS: Jiwei Tang, Shilei Liu, Zhicheng Zhang
CATEGORY: Information-Theoretic Compression
KEY FINDING: Coarse-to-fine compression guided by marginal information gain metrics
NOVELTY: Information-theoretic grounding for what to compress versus keep
WHY IT MATTERS: Principled compression based on information value, not heuristics
PRODUCTIZATION STATUS: Not productized

PAPER #26 | arXiv:2601.06411 | 2026-01-10
TITLE: Structured Episodic Event Memory
AUTHORS: Zhengxuan Lu, Dongfang Li, Yukun Shi
CATEGORY: Structured Episodic Memory
KEY FINDING: Events stored with relational structure enabling multi-hop reasoning over experiences
NOVELTY: Replaces flat event embeddings with structured event graphs
WHY IT MATTERS: Enables complex reasoning over past experiences, not just retrieval
PRODUCTIZATION STATUS: Not productized

PAPER #27 | arXiv:2601.06282 | 2026-01-09
TITLE: Amory: Building Coherent Narrative-Driven Agent Memory through Agentic Reasoning
AUTHORS: Yue Zhou, Xiaobo Guo, Belhassen Bayar
CATEGORY: Narrative-Driven Memory
KEY FINDING: Agent actively constructs narrative coherence during memory formation using reasoning
NOVELTY: Proactive narrative memory construction vs. passive embedding storage
WHY IT MATTERS: Preserves story-like structure for better long-term recall
PRODUCTIZATION STATUS: Not productized

PAPER #28 | arXiv:2601.03236 | 2026-01-06
TITLE: MAGMA: A Multi-Graph based Agentic Memory Architecture for AI Agents
AUTHORS: Dongming Jiang, Yi Li, Guanpeng Li
CATEGORY: Multi-Graph Memory
KEY FINDING: Separates temporal, causal, and entity information into distinct graph structures
NOVELTY: Dimension-wise separation avoids entanglement in monolithic memory stores
WHY IT MATTERS: Clean architecture for interpretable, queryable multi-aspect memory
PRODUCTIZATION STATUS: Not productized

PAPER #29 | arXiv:2603.23234 | 2026-03-24
TITLE: MemCollab: Cross-Agent Memory Collaboration via Contrastive Trajectory Distillation
AUTHORS: Multiple authors
CATEGORY: Multi-Agent Memory
KEY FINDING: Agents learn from each other memory trajectories without shared memory stores
NOVELTY: Contrastive distillation enables memory knowledge transfer with privacy guarantees
WHY IT MATTERS: Enables collective intelligence across agent populations
PRODUCTIZATION STATUS: Not productized

PAPER #30 | arXiv:2603.23013 | 2026-03-24
TITLE: Knowledge Access Beats Model Size: Memory Augmented Routing for Persistent AI Agents
AUTHORS: Multiple authors
CATEGORY: Memory-Augmented Routing
KEY FINDING: Memory-augmented small models consistently outperform larger models with poor memory
NOVELTY: Empirical demonstration that memory infrastructure > model scaling for persistent agents
WHY IT MATTERS: Paradigm shift argument for investing in memory systems over model scaling
PRODUCTIZATION STATUS: Not productized

PAPER #31 | arXiv:2603.29035 | 2026-03-30
TITLE: Non-Hermitian Causal Memory Generates Observable Temporal Correlations
AUTHORS: Mario J. Pinheiro
CATEGORY: Causal Memory / Theoretical
KEY FINDING: Physics-grounded non-Hermitian framework for causal memory with observable temporal correlations
NOVELTY: First theoretical framework grounding causal memory in non-Hermitian physics
WHY IT MATTERS: Could inspire fundamentally new memory architectures based on physical principles
PRODUCTIZATION STATUS: Theoretical physics paper

PAPER #32 | arXiv:2603.11768 | 2026-03-12
TITLE: Governing Evolving Memory in LLM Agents: Risks, Mechanisms, and the SSGM Framework
AUTHORS: Chingkwun Lam, Jiaxin Li, Lingfei Zhang
CATEGORY: Memory Safety / Governance
KEY FINDING: SSGM framework addresses semantic drift and privacy in dynamic memory systems
NOVELTY: First governance framework for evolving (self-modifying) memory, not static retrieval
WHY IT MATTERS: Essential for safe deployment of agents with self-modifying memory
PRODUCTIZATION STATUS: Framework, not productized

PAPER #33 | arXiv:2603.19595 | 2026-03-20
TITLE: All-Mem: Agentic Lifelong Memory via Dynamic Topology Evolution
AUTHORS: Multiple authors
CATEGORY: Dynamic Topology Memory
KEY FINDING: Memory graph topology evolves based on lifetime usage patterns and access frequency
NOVELTY: Memory structure is not fixed - nodes/edges added/removed based on utility signals
WHY IT MATTERS: Self-organizing memory that reflects actual agent behavior patterns
PRODUCTIZATION STATUS: Not productized

PAPER #34 | arXiv:2603.04910 | 2026-03-05
TITLE: VPWEM: Non-Markovian Visuomotor Policy with Working and Episodic Memory
AUTHORS: Yuheng Lei, Zhixuan Liang, Hongyuan Zhang
CATEGORY: Working + Episodic Memory (Robotics)
KEY FINDING: Dual-process memory (working + episodic) for non-Markovian continuous control
NOVELTY: Biologically-inspired dual memory for visuomotor policies
WHY IT MATTERS: Bridges cognitive psychology with practical robotic control
PRODUCTIZATION STATUS: Not productized

PAPER #35 | arXiv:2602.13980 | 2026-02-15
TITLE: Cognitive Chunking for Soft Prompts: Accelerating Compressor Learning via Block-wise Causal Masking
AUTHORS: Guojie Liu, Yiqi Wang, Yanfeng Yang
CATEGORY: Cognitive Chunking
KEY FINDING: Block-wise causal masking accelerates soft prompt compressor training
NOVELTY: Applies cognitive psychology chunking principles to compressor architecture design
WHY IT MATTERS: Faster, more effective context compression training
PRODUCTIZATION STATUS: Not productized

PAPER #36 | arXiv:2603.28088 | 2026-03-30
TITLE: GEMS: Agent-Native Multimodal Generation with Memory and Skills
AUTHORS: Zefeng He, Siyuan Huang, Xiaoye Qu
CATEGORY: Multimodal Agent Memory
KEY FINDING: Agent-native architecture unifying memory persistence with skill acquisition and reuse
NOVELTY: Memory and skills co-evolve within the agent rather than separate modules
WHY IT MATTERS: Enables agents to build persistent multimodal knowledge
PRODUCTIZATION STATUS: Not productized

PAPER #37 | arXiv:2603.21520 | 2026-03-23
TITLE: Generalizable Self-Evolving Memory for Automatic Prompt Optimization
AUTHORS: Multiple authors
CATEGORY: Self-Evolving Memory
KEY FINDING: Memory system generalizes learned strategies across tasks to auto-optimize prompts
NOVELTY: Memory evolves general skills not just stores facts
WHY IT MATTERS: Eliminates manual prompt engineering through memory-based adaptation
PRODUCTIZATION STATUS: Not productized

PAPER #38 | arXiv:2511.07587 | 2025-11-10
TITLE: Beyond Fact Retrieval: Episodic Memory for RAG with Generative Semantic Workspaces
AUTHORS: Shreyas Rajesh, Pavan Holur, Chenda Duan, David Chong, Vwani Roychowdhury
CATEGORY: Episodic Memory / Semantic Workspaces
KEY FINDING: Generative semantic workspaces provide episodic context beyond fact-based RAG retrieval
NOVELTY: Episodic (experience-based) memory layer on top of semantic retrieval
WHY IT MATTERS: Addresses RAG fundamental inability to reason about experiences
PRODUCTIZATION STATUS: Not productized

PAPER #39 | arXiv:2512.09238 | 2025-12-10
TITLE: Training-free Context-adaptive Attention for Efficient Long Context Modeling
AUTHORS: Zeng You, Yaofo Chen, Shuhai Zhang
CATEGORY: Context-adaptive Attention
KEY FINDING: Training-free approach to dynamically adapt attention for efficient long-context modeling
NOVELTY: No training needed - adapts attention patterns at inference time
WHY IT MATTERS: Deployable on any existing LLM without fine-tuning
PRODUCTIZATION STATUS: Not productized

PAPER #40 | arXiv:2511.12960 | 2025-11-17
TITLE: ENGRAM: Effective, Lightweight Memory Orchestration for Conversational Agents
AUTHORS: Daivik Patel, Shrenik Patel
CATEGORY: Lightweight Memory Orchestration
KEY FINDING: Achieves long-horizon consistency without complex graph architectures
NOVELTY: Minimal-overhead memory orchestration matching complex systems
WHY IT MATTERS: Production-practical alternative to heavy graph-based memory
PRODUCTIZATION STATUS: Not productized

===============================================================================
SUMMARY STATISTICS
===============================================================================
Total papers scanned via arXiv API: 765+
Queries performed: 37
Date range: December 2025 - April 2026
Curated non-productized papers: 40
Excluded known papers: 6 (ACC/CCS, D-MEM, GDWM, S3-Attention, ContextBudget, ElephantBroker)

Top research themes identified:
1. RL-based Memory Management (DeltaMem, RL-compression)
2. Episodic + Procedural Memory Separation (APEX-EM, VPWEM, REMem)
3. Narrative/Coherent Memory Construction (Amory, TraceMem)
4. Graph-based Memory with Formal Semantics (Kumiho, MAGMA, GSEM)
5. Cognitive Gist / Compression (CogitoRAG, COMI, Density-aware)
6. Multi-Agent Memory Collaboration (MemCollab, MemMA)
7. Self-Evolving/Adaptive Memory (All-Mem, MemFactory, generalizable)
8. State Decoupling from Context (StatePlane, cognitive state plane)
9. Memory Forgetting/Decay as Feature (Oblivion, Learning to Forget)
10. Neuro-Symbolic Memory Integration
