# 4. MetaGPT — Software Company Simulation
> Deep dive | research/05-ai-agent-architectures-analysis.md
---


### Architecture Overview
MetaGPT simulates a software company with specialized agents: Product Manager, Architect, Project Manager, Engineer, and QA Engineer. It uses **Standardized Operating Procedures (SOPs)** encoded into prompts to ensure structured outputs. Agents communicate through a **publish-subscribe message pool** with structured artifacts (PRDs, design docs, code).

### Memory Model
- **Shared message pool** — Global publish-subscribe system where agents publish structured outputs
- **Historical execution memory** — Engineer agents remember past code iterations and debugging results
- **Artifact-based memory** — All outputs are structured documents (PRDs, UML diagrams, interface definitions)

### Reasoning Approach
Assembly-line workflow. Each agent produces a standardized output that becomes the input for the next agent. SOPs ensure quality and reduce hallucination. Engineers use **iterative self-correction** — they write code, run tests, and debug based on feedback.

### State Management
State is managed through structured artifacts in the message pool. Each agent publishes its output, and downstream agents subscribe to relevant artifacts. The workflow is deterministic and reproducible.

### Strengths
- SOPs dramatically reduce hallucination and error cascades
- Structured outputs ensure quality handoffs
- Self-correcting through test-driven development
- 85.9% Pass@1 on HumanEval, 87.7% on MBPP
- 100% task completion in controlled evaluations

### Weaknesses
- Highly domain-specific (software development)
- Rigid assembly-line limits adaptability
- No long-term learning across projects
- SOP encoding is manual and brittle
- Free-form dialogue between agents is discouraged

### Key Insight for AI Agent Brain
SOPs are powerful for reliability, but our system needs **adaptive SOPs** — procedures that evolve based on what works, not just static templates. The publish-subscribe pattern is excellent for decoupled agent communication.

---
