#!/usr/bin/env python3
"""Clean LoCoMo retrieval-component runner over Bilinc's public StatePlane API.

This runner is intentionally a component lane, not the official end-to-end QA
evaluation. It ingests only the official conversation turns, isolates each
conversation in its own SQLite-backed StatePlane, retrieves with the public
``recall_intelligent`` path, and scores source-evidence identifiers with the
repository's normalized retrieval metrics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

# Permit direct execution from a clean checkout without requiring an editable
# install; the benchmark still imports the repository's public product code.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

from bilinc.core.models import MemoryType  # noqa: E402
from bilinc.core.stateplane import StatePlane  # noqa: E402
from bilinc.storage.sqlite import SQLiteBackend  # noqa: E402

from benchmarks.metrics import ndcg_at_k, recall_at_k, hit_at_k  # noqa: E402


CATEGORY_NAMES = {
    1: "single-hop",
    2: "multi-hop",
    3: "temporal",
    4: "open-domain",
    5: "adversarial",
}


def _session_keys(conversation: dict[str, Any]) -> list[str]:
    """Return raw session arrays in their numeric D1, D2, ... order."""
    raw = conversation.get("conversation", {})
    keys = [
        key
        for key, value in raw.items()
        if key.startswith("session_")
        and isinstance(value, list)
        and not key.endswith("_date_time")
    ]
    return sorted(keys, key=lambda key: int(key.split("_", 1)[1]))


def _turn_text(turn: Any) -> tuple[str, str]:
    if isinstance(turn, dict):
        return str(turn.get("speaker", "")), str(turn.get("text", "")).strip()
    return "", str(turn).strip()


def _conversation_id(conversation: dict[str, Any], index: int) -> str:
    return str(conversation.get("id") or conversation.get("sample_id") or f"conv-{index}")


async def _ingest_conversation(
    conversation: dict[str, Any],
    conversation_id: str,
    db_path: Path,
) -> tuple[StatePlane, dict[str, str], int]:
    backend = SQLiteBackend(str(db_path))
    plane = StatePlane(backend=backend)
    await plane.init()

    evidence_key_by_ref: dict[str, str] = {}
    absolute_index = 0
    for session_number, session_key in enumerate(_session_keys(conversation), start=1):
        turns = conversation["conversation"][session_key]
        for turn_position, turn in enumerate(turns, start=1):
            speaker, text = _turn_text(turn)
            if not text:
                continue
            memory_key = f"locomo:{conversation_id}:t{absolute_index:04d}"
            await plane.commit_with_agm_async(
                memory_key,
                f"{speaker}: {text}" if speaker else text,
                memory_type=MemoryType.EPISODIC.value,
                importance=0.5,
                source="official_locomo_turn",
                session_id=conversation_id,
                metadata={
                    "source_ref": f"D{session_number}:{turn_position}",
                    "session_number": session_number,
                    "turn_position": turn_position,
                },
            )
            evidence_key_by_ref[f"D{session_number}:{turn_position}"] = memory_key
            absolute_index += 1
    return plane, evidence_key_by_ref, absolute_index


def _evidence_keys(evidence: Any, key_by_ref: dict[str, str]) -> set[str]:
    keys: set[str] = set()
    if not isinstance(evidence, list):
        return keys
    for ref in evidence:
        ref_text = str(ref).strip()
        if ref_text in key_by_ref:
            keys.add(key_by_ref[ref_text])
    return keys


async def run_benchmark(
    dataset_path: Path,
    output_path: Path,
    top_k: int = 5,
    limit_conversations: int | None = None,
) -> dict[str, Any]:
    started = time.time()
    conversations = json.loads(dataset_path.read_text())
    if limit_conversations is not None:
        conversations = conversations[: max(0, int(limit_conversations))]

    totals = {
        "questions": 0,
        "hit_at_5": 0.0,
        "evidence_recall_at_5": 0.0,
        "ndcg_at_5": 0.0,
    }
    category_totals: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"n": 0, "hit_at_5": 0.0, "evidence_recall_at_5": 0.0, "ndcg_at_5": 0.0}
    )
    detail_rows: list[dict[str, Any]] = []
    total_memories = 0

    with TemporaryDirectory(prefix="bilinc-locomo-stateplane-") as temp_dir:
        for conversation_index, conversation in enumerate(conversations):
            conversation_id = _conversation_id(conversation, conversation_index)
            plane, key_by_ref, memory_count = await _ingest_conversation(
                conversation,
                conversation_id,
                Path(temp_dir) / f"{conversation_id}.sqlite",
            )
            total_memories += memory_count
            try:
                for question_index, question_item in enumerate(conversation.get("qa", [])):
                    question = str(question_item.get("question") or "").strip()
                    relevant = _evidence_keys(question_item.get("evidence"), key_by_ref)
                    if not question or not relevant:
                        continue

                    retrieved = await plane.recall_intelligent(question, limit=top_k)
                    retrieved_keys = [str(item["key"]) for item in retrieved if item.get("key")]
                    hit = hit_at_k(retrieved_keys, relevant, top_k)
                    evidence_recall = recall_at_k(retrieved_keys, relevant, top_k)
                    ndcg = ndcg_at_k(retrieved_keys, relevant, top_k)
                    category = CATEGORY_NAMES.get(int(question_item.get("category", 4)), "open-domain")

                    totals["questions"] += 1
                    totals["hit_at_5"] += hit
                    totals["evidence_recall_at_5"] += evidence_recall
                    totals["ndcg_at_5"] += ndcg
                    bucket = category_totals[category]
                    bucket["n"] += 1
                    bucket["hit_at_5"] += hit
                    bucket["evidence_recall_at_5"] += evidence_recall
                    bucket["ndcg_at_5"] += ndcg
                    detail_rows.append(
                        {
                            "conversation": conversation_id,
                            "question_index": question_index,
                            "category": category,
                            "retrieved_keys": retrieved_keys,
                            "evidence_keys": sorted(relevant),
                            "hit_at_5": hit,
                            "evidence_recall_at_5": evidence_recall,
                            "ndcg_at_5": ndcg,
                        }
                    )
            finally:
                await plane.backend.close()

    question_count = int(totals["questions"])

    def mean(field: str, bucket: dict[str, float | int]) -> float:
        count = int(bucket["n"])
        return float(bucket[field]) / count if count else 0.0

    result = {
        "schema_version": 1,
        "benchmark": "LoCoMo official retrieval component",
        "lane": "component",
        "dataset": {
            "path": str(dataset_path),
            "conversations": len(conversations),
            "qa_scored": question_count,
        },
        "protocol": {
            "top_k": top_k,
            "scope": "one isolated SQLite-backed StatePlane per conversation",
            "ingestion": "official raw conversation turns only",
            "retrieval": "StatePlane.recall_intelligent public API",
            "qa_or_observation_projection": False,
            "benchmark_specific_query_expansion": False,
            "metrics": "Hit@K, evidence recall@K, normalized binary NDCG@K",
        },
        "total_memories": total_memories,
        "totals": {
            "questions": question_count,
            "hit_at_5": totals["hit_at_5"] / question_count if question_count else 0.0,
            "evidence_recall_at_5": totals["evidence_recall_at_5"] / question_count if question_count else 0.0,
            "ndcg_at_5": totals["ndcg_at_5"] / question_count if question_count else 0.0,
        },
        "by_category": {
            category: {
                "n": int(bucket["n"]),
                "hit_at_5": mean("hit_at_5", bucket),
                "evidence_recall_at_5": mean("evidence_recall_at_5", bucket),
                "ndcg_at_5": mean("ndcg_at_5", bucket),
            }
            for category, bucket in sorted(category_totals.items())
        },
        "details": detail_rows,
        "elapsed_seconds": round(time.time() - started, 3),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--limit-conversations", type=int)
    args = parser.parse_args()
    result = asyncio.run(
        run_benchmark(
            args.dataset,
            args.output,
            top_k=args.top_k,
            limit_conversations=args.limit_conversations,
        )
    )
    print(json.dumps({key: result[key] for key in ("dataset", "total_memories", "totals", "by_category", "elapsed_seconds")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
