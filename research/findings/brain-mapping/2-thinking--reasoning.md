# 2. THINKING & REASONING — Brain to AI Mapping
> Source: research/01-human-brain-cognitive-architecture.md
---


### 2.1 System 1 vs System 2 (Kahneman)

**Brain Mechanism:**
- **System 1**: Fast, automatic, associative, emotional, low effort
  - Basal ganglia, amygdala, default mode network
  - Pattern recognition, heuristics, intuition
- **System 2**: Slow, deliberate, logical, effortful, rule-based
  - Lateral PFC, anterior cingulate cortex (ACC)
  - Working memory intensive, serial processing
- **Conflict monitoring**: ACC detects System 1/System 2 conflict
- **Cognitive control**: dlPFC overrides System 1 when needed

**AI Agent Implementation:**
```
Dual-Process Architecture:

System 1 (Fast Path):
- Cached responses for common patterns
- Embedding similarity matching → direct action
- Heuristic rules (if-then for frequent scenarios)
- Pre-trained policy network (zero deliberation)
- Latency: <100ms

System 2 (Slow Path):
- Triggered when: low confidence, high stakes, novel situation, System 1 conflict
- Chain-of-thought reasoning
- Tree search / planning
- Multi-step verification
- Latency: seconds to minutes

Meta-controller (ACC analog):
- Confidence estimator decides which system to use
- Monitor for anomalies → escalate to System 2
- Learn when System 1 fails → update heuristics
```

### 2.2 Deductive Reasoning

**Brain Mechanism:**
- **Left PFC** for logical inference
- **Mental model theory**: Construct mental representations of premises
- **Belief bias**: Prior knowledge interferes with logical reasoning
- Neural substrates: Left inferior frontal gyrus, parietal cortex

**Computational Models:**
- **Theorem provers**: Resolution, tableaux, natural deduction
- **Neural theorem proving**: DeepProbLog, Logic Tensor Networks
- **Graph neural networks**: Reasoning over knowledge graphs

**AI Agent Implementation:**
```
- Integrate symbolic reasoner (Z3, Prolog) for guaranteed correctness
- Neural-symbolic hybrid: LLM generates premises, prover validates
- Constraint satisfaction: Frame problems as CSPs, use backtracking search
- Type checking: Use type systems to enforce logical constraints
```

### 2.3 Inductive Reasoning

**Brain Mechanism:**
- **Orbitofrontal cortex**: Pattern extraction from examples
- **Bayesian inference in the brain**: Prior beliefs updated by evidence
- **Hypothesis generation**: Ventromedial PFC proposes explanations

**AI Agent Implementation:**
```
- Bayesian updating: P(h|D) ∝ P(D|h) × P(h)
- Few-shot learning: Extract patterns from limited examples
- Program synthesis: Infer rules from input-output pairs
- Meta-learning: Learn to learn (MAML, Reptile)
- Causal discovery: PC algorithm, GES for structure learning
```

### 2.4 Abductive Reasoning

**Brain Mechanism:**
- **Default mode network**: Generating explanations
- **Hippocampal construction**: Combining elements into novel scenarios
- **Inference to best explanation**: Selecting most plausible hypothesis

**AI Agent Implementation:**
```
- Generate multiple hypotheses → score by:
  - Explanatory power (covers observed data)
  - Simplicity (minimum description length)
  - Prior probability (consistency with existing knowledge)
- LLM-based hypothesis generation with constraint checking
- Answer Set Programming for abductive logic programming
```

### 2.5 Analogical Reasoning

**Brain Mechanism:**
- **Rostrolateral PFC**: Relational integration
- **Structure mapping**: Aligning relational structures across domains
- **Hippocampal binding**: Binding relations independent of specific content

**Computational Models:**
- **Structure Mapping Engine (SME)**: Gentner's algorithm
- **Analogical Constraint Mapping Engine (ACME)**
- **Graph matching**: Maximum common subgraph

**AI Agent Implementation:**
```
- Represent problems as graphs (nodes=entities, edges=relations)
- Graph kernel / graph edit distance for similarity
- Transfer solutions from source domain to target domain
- LLM prompt: "This problem is structurally similar to X. How was X solved?"
- Implement DORA (Discovery Of Relations by Analogy) model
```

### 2.6 Causal Reasoning

**Brain Mechanism:**
- **Prefrontal-parietal network**: Causal model construction
- **Intervention representation**: Understanding do(X) vs observe(X)
- **Counterfactual simulation**: "What if" reasoning in hippocampus + PFC

**Computational Models:**
- **Pearl's causal calculus**: do-calculus, structural causal models
- **Bayesian networks**: Probabilistic causal models
- **Neural causal models**: Differentiable causal discovery

**AI Agent Implementation:**
```
- Build causal graphs from data (PC, FCI, NOTEARS algorithms)
- Intervention planning: Use do-calculus to predict action effects
- Counterfactual queries: "What would have happened if I did X instead?"
- Causal reinforcement learning: Separate correlation from causation
- Implement backdoor/frontdoor adjustment for confounding control
```

---

