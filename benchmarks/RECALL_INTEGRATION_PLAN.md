# Bilinc Real Recall Integration Plan

**Date:** 2026-04-13
**Goal:** Push ConvoMem to 85%+ and LoCoMo to 90%+ using real Bilinc recall

---

## CRITICAL FINDING

**sqlite-vec is already installed and schema exists, but `sqlite_vec.load(conn)` is never called.**

- `schemas/vec0.sql` defines `vec_bilinc` table with float[768]
- `sqlite_vec` Python package installed
- Ollama `nomic-embed-text:latest` running (768-dim)
- **Missing:** `sqlite_vec.load(conn)` call when opening DB

This means Bilinc ALREADY HAS the infrastructure for semantic search but it's not activated.

---

## THREE-LEVEL RECALL ARCHITECTURE

```
Query
  |
  v
Level 1: FTS5 Keyword Search (fast, exact matches)
  |
  v
Level 2: Vector Similarity Search (semantic matches)
  |
  v
Level 3: Knowledge Graph Traversal (multi-hop reasoning)
  |
  v
RRF Fusion -> Decay-Aware Reranking -> Final Results
```

---

## PHASE 1: ACTIVATE EXISTING INFRASTRUCTURE (2 hours)

### 1.1 Enable sqlite-vec
```python
# In bilinc/storage/sqlite.py, add after conn creation:
import sqlite_vec
sqlite_vec.load(conn)
```

### 1.2 Backfill Embeddings
```python
# For each existing entry in bilinc.db:
embedding = ollama_embed(entry.key + " " + str(entry.value))
conn.execute("INSERT INTO vec_bilinc (rowid, embedding) VALUES (?, ?)",
             (entry.rowid, serialize_float32(embedding)))
```

### 1.3 Vector Search Function
```python
def vector_search(query_embedding, top_k=10):
    results = conn.execute("""
        SELECT rowid, distance
        FROM vec_bilinc
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?
    """, (serialize_float32(query_embedding), top_k)).fetchall()
    return results
```

**Expected improvement:** +15-25% on both benchmarks

---

## PHASE 2: FTS5 FULL-TEXT SEARCH (1 day)

### 2.1 Create FTS5 Table
```sql
CREATE VIRTUAL TABLE mem_fts USING fts5(
    key, value_text, tokenize='porter unicode61'
);
```

### 2.2 Sync Triggers
```sql
CREATE TRIGGER mem_ai AFTER INSERT ON memories BEGIN
    INSERT INTO mem_fts(rowid, key, value_text)
    VALUES (new.rowid, new.key, new.value_text);
END;
```

### 2.3 Keyword Search Function
```python
def keyword_search(query, top_k=10):
    return conn.execute("""
        SELECT rowid, rank FROM mem_fts
        WHERE mem_fts MATCH ?
        ORDER BY rank LIMIT ?
    """, (query, top_k)).fetchall()
```

**Expected improvement:** +5-10% on fact_recall category

---

## PHASE 3: HYBRID SEARCH WITH RRF (1 day)

### 3.1 Reciprocal Rank Fusion
```python
def hybrid_search(query, top_k=10):
    # Get results from both
    keyword_results = keyword_search(query, top_k * 2)
    query_embedding = ollama_embed(query)
    vector_results = vector_search(query_embedding, top_k * 2)

    # RRF fusion (k=60 is standard)
    fused = {}
    for rank, (rowid, _) in enumerate(keyword_results):
        fused[rowid] = fused.get(rowid, 0) + 1.0 / (60 + rank + 1)
    for rank, (rowid, _) in enumerate(vector_results):
        fused[rowid] = fused.get(rowid, 0) + 1.0 / (60 + rank + 1)

    # Sort by fused score
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]
```

**Expected improvement:** +10-15% overall

---

## PHASE 4: KG-AWARE RETRIEVAL (2 days)

Inspired by HippoRAG's Personalized PageRank spreading activation.

### 4.1 Entity Extraction from Query
```python
def extract_entities(query):
    # Use Ollama to extract entities from question
    # Returns: ["ARES", "Bilinc", "Seed Round"]
    ...
```

### 4.2 KG Node Matching
```python
def find_kg_nodes(entities):
    # Match entities to Knowledge Graph nodes
    # Uses vector similarity for fuzzy matching
    nodes = []
    for entity in entities:
        best_match = vector_search(ollama_embed(entity), top_k=1)
        if best_match:
            nodes.append(best_match[0])
    return nodes
```

### 4.3 Spreading Activation (Personalized PageRank)
```python
def spreading_activation(seed_nodes, max_hops=2):
    # Start from seed nodes
    # Spread activation through relations
    # Decay factor per hop
    activated = {node: 1.0 for node in seed_nodes}
    for hop in range(max_hops):
        decay = 0.5 ** (hop + 1)
        new_activation = {}
        for node, score in activated.items():
            neighbors = kg.get_neighbors(node)
            for neighbor, rel_strength in neighbors:
                new_activation[neighbor] = new_activation.get(neighbor, 0) + score * decay * rel_strength
        activated.update(new_activation)
    return sorted(activated.items(), key=lambda x: x[1], reverse=True)
```

### 4.4 Multi-Hop Context Assembly
```python
def multi_hop_recall(query):
    entities = extract_entities(query)
    seed_nodes = find_kg_nodes(entities)
    activated_nodes = spreading_activation(seed_nodes)
    # Retrieve memories associated with activated nodes
    context = []
    for node, score in activated_nodes[:10]:
        memories = get_memories_for_node(node)
        context.extend([(m, score) for m in memories])
    return context
```

**Expected improvement:** +10-20% on multi_hop and causal categories

---

## PHASE 5: DECAY-AWARE RERANKING (1 day)

### 5.1 Apply Hybrid Decay to Ranking
```python
def decay_aware_rerank(results, query):
    reranked = []
    for entry, base_score in results:
        # Apply decay
        decayed_strength = decay_for_entry(entry)
        # Apply importance boost
        importance_boost = entry.importance * 0.3
        # Apply access frequency boost
        access_boost = min(1.0, 0.8 + entry.access_count * 0.01)
        # Combined score
        final_score = base_score * decayed_strength * (1 + importance_boost) * access_boost
        reranked.append((entry, final_score))
    return sorted(reranked, key=lambda x: x[1], reverse=True)
```

**Expected improvement:** +5-10% overall

---

## PHASE 6: TEMPORAL REASONING (1 day)

### 6.1 Temporal Boost
```python
def temporal_boost(entry, query_temporal_hint):
    # If query asks "when" or "first" or "before/after"
    # Boost entries with valid_at/invalid_at timestamps
    if query_temporal_hint and entry.valid_at:
        return 1.3
    return 1.0
```

### 6.2 Chronological Ordering
```python
def temporal_ordering(query, results):
    # If query asks about order, sort by timestamp
    if "order" in query.lower() or "first" in query.lower() or "before" in query.lower():
        return sorted(results, key=lambda x: x.valid_at or x.created_at)
    return results
```

**Expected improvement:** +10-15% on temporal categories

---

## EXPECTED FINAL SCORES

| Benchmark | Current | After Phase 1-3 | After Phase 4-6 |
|-----------|---------|-----------------|-----------------|
| ConvoMem | 72% | 82-85% | 88-92% |
| LoCoMo | 70.5% | 78-82% | 85-92% |
| LongMemEval | 98% | 98%+ | 98%+ |

---

## EXECUTION ORDER

1. Phase 1: Enable sqlite-vec (2h) ← DO FIRST, BIGGEST BANG
2. Phase 2: FTS5 (1 day)
3. Phase 3: RRF fusion (1 day)
4. Phase 5: Decay-aware rerank (1 day) ← easy win
5. Phase 4: KG spreading activation (2 days)
6. Phase 6: Temporal reasoning (1 day)

**Total: 6-7 days**

---

## REFERENCES

- HippoRAG: arxiv 2405.14831 (NeurIPS 2024)
- GraphRAG: arxiv 2404.16130 (Microsoft)
- RAPTOR: arxiv 2401.18059
- MemPalace: 44K stars, raw verbatim > LLM extraction
- 0GMem: 8-strategy RRF fusion, 88.67% LoCoMo
- LongMemEval: official benchmark repo
- sqlite-vec: https://github.com/asg017/sqlite-vec
