#!/usr/bin/env python3
"""Bilinc LongMemEval Benchmark v3."""
import json
import re
import argparse
from collections import defaultdict

from benchmarks.metrics import hit_at_k, ndcg_at_k

STOP = {"what","when","where","who","how","which","did","do","was","were","have","has","had",
        "is","are","the","a","an","my","me","i","you","your","their","it","its","in","on",
        "at","to","for","of","with","by","from","ago","last","that","this","there","about",
        "get","got","give","gave","buy","bought","made","make","been","being","could","would",
        "should","will","can","may","might","shall","must","need","dare","ought","used","like",
        "just","also","then","than","more","very","much","many","some","any","every","each",
        "both","few","other","another","such","even","still","already","yet","ever","never",
        "always","often","sometimes","usually","here","there","now","today","yesterday",
        "tomorrow","really","actually","probably","perhaps","maybe","sure","yes","no","not"}

def evaluate(rankings, correct_ids, corpus_ids, k):
    retrieved = [corpus_ids[index] for index in rankings]
    return hit_at_k(retrieved, correct_ids, k), ndcg_at_k(retrieved, correct_ids, k)

def kws(text):
    return [w for w in re.findall(r"[a-zA-Z]{3,}", text.lower()) if w not in STOP]

def build_corpus(sessions, session_ids, dates):
    corpus, ids, ts = [], [], []
    seen = set()
    for session, sid, date in zip(sessions, session_ids, dates):
        if sid in seen:
            continue
        seen.add(sid)
        if isinstance(session, list):
            user_turns = [t.get("content","") for t in session if isinstance(t,dict) and t.get("role")=="user"]
            if user_turns:
                corpus.append("\n".join(user_turns))
                ids.append(sid)
                ts.append(date)
    return corpus, ids, ts

def hybrid_retrieve(col, question, corpus_ids, top_k=5, sem_n=50):
    n = min(sem_n, col.count())
    if n == 0:
        return corpus_ids[:top_k]
    res = col.query(query_texts=[question], n_results=n,
                    include=["documents","metadatas","distances"])
    if not res["documents"][0]:
        return corpus_ids[:top_k]
    docs, metas, dists = res["documents"][0], res["metadatas"][0], res["distances"][0]
    qkws = kws(question)
    scored = []
    seen = set()
    for doc,meta,dist in zip(docs,metas,dists):
        cid = meta.get("cid", "")
        if cid in seen:
            continue
        seen.add(cid)
        dkws = kws(doc)
        overlap = len(set(qkws)&set(dkws))/len(qkws) if qkws else 0
        fused = dist * (1 - 0.30*overlap)
        scored.append((fused, cid))
    scored.sort(key=lambda x: x[0])
    return [s[1] for s in scored[:top_k]]

def run(data_path, mode="hybrid", top_k=5, limit=None):
    try:
        import chromadb
    except ImportError as exc:
        raise RuntimeError("LongMemEval requires the optional chromadb dependency.") from exc

    with open(data_path) as f:
        data = json.load(f)
    if limit:
        data = data[:limit]
    print(f"Running {len(data)} questions, mode={mode}", flush=True)
    by_type = defaultdict(list)
    all_res = []
    for qi, q in enumerate(data):
        question = q["question"]
        qtype = q["question_type"]
        correct = set(q["answer_session_ids"])
        h_ids = q["haystack_session_ids"]
        h_sessions = q.get("haystack_sessions", [])
        h_dates = q.get("haystack_dates", [])
        corpus, corpus_ids, corpus_dates = build_corpus(h_sessions, h_ids, h_dates)
        if not corpus:
            by_type[qtype].append(0.0)
            all_res.append({"hit_at_k":0.0,"ndcg":0.0})
            continue
        client = chromadb.EphemeralClient()
        col = client.create_collection("quest"+str(qi).zfill(4), metadata={"hnsw:space":"cosine"})
        for j,(doc,sid) in enumerate(zip(corpus,corpus_ids)):
            col.add(documents=[doc], ids=[sid], metadatas=[{"cid":sid}])
        if mode == "raw":
            res = col.query(query_texts=[question], n_results=top_k, include=["documents"])
            ids = res["ids"][0][:top_k] if res["ids"] else []
        else:
            ids = hybrid_retrieve(col, question, corpus_ids, top_k)
        rankings = list(range(len(ids)))
        hit_at_k, ndcg = evaluate(rankings, correct, ids, top_k)
        by_type[qtype].append(hit_at_k)
        all_res.append({"hit_at_k":hit_at_k,"ndcg":ndcg})
        if (qi+1) % 25 == 0:
            cr = sum(r["hit_at_k"] for r in all_res)/len(all_res)
            print(f"  [{qi+1}/{len(data)}] Hit@{top_k}: {cr:.1%}", flush=True)
    overall = sum(r["hit_at_k"] for r in all_res)/len(all_res)
    ondcg = sum(r["ndcg"] for r in all_res)/len(all_res)
    print(f"\n{'='*50}", flush=True)
    print(f"BILINC LongMemEval: Hit@{top_k}={overall:.1%} NDCG@{top_k}={ondcg:.3f} n={len(all_res)}", flush=True)
    for t,rs in sorted(by_type.items()):
        print(f"  {t:30s} {sum(rs)/len(rs):.1%} (n={len(rs)})", flush=True)
    return overall

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("data")
    p.add_argument("--mode", default="hybrid", choices=["raw","hybrid"])
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--limit", type=int)
    a = p.parse_args()
    run(a.data, a.mode, a.top_k, a.limit)
