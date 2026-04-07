# 10. Reflexion — Self-Reflection in Agents
> Deep dive | research/05-ai-agent-architectures-analysis.md
---


### Architecture Overview
Reflexion reinforces agents through **verbal feedback** rather than weight updates. Three components:
1. **Actor** — LLM that generates actions/outputs
2. **Evaluator** — Scores the Actor outputs (binary, scalar, or LLM-based)
3. **Self-Reflection** — LLM that generates verbal feedback from evaluation signals, stored in episodic memory

### Memory Model
- **Short-term memory** — Current trajectory/history
- **Long-term memory** — Episodic buffer of self-reflections (bounded, typically 1-3 experiences)
- **Verbal reinforcement** — Natural language summaries of what went wrong and how to improve

### Reasoning Approach
Trial -> Evaluate -> Reflect -> Retry. After each attempt, the agent evaluates its performance, generates a self-reflection ("I should have done X instead of Y"), stores it in memory, and uses it to improve the next attempt.

### State Management
State is the current task context plus accumulated self-reflections. Memory is bounded by a sliding window to fit context limits.

### Strengths
- 91% Pass@1 on HumanEval (vs 80% GPT-4 baseline)
- +22% improvement on AlfWorld decision-making
- +20% improvement on HotpotQA reasoning
- Lightweight — no fine-tuning required
- Interpretable — reflections are human-readable
- Works across decision-making, reasoning, and coding

### Weaknesses
- Memory is limited to sliding window (loses older lessons)
- Requires multiple trials (not single-shot learning)
- Depends on LLM self-evaluation capability
- No mechanism for generalizing reflections across tasks
- Can get stuck in local minima

### Key Insight for AI Agent Brain
Verbal self-reflection is powerful but the memory model is too limited. Our system needs: (1) **persistent reflection memory** with generalization across tasks, (2) automatic pattern extraction from multiple reflections, (3) proactive reflection (not just after failure), and (4) reflection-driven skill creation.

---
