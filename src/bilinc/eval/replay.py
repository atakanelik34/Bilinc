"""Replay captured Bilinc retrieval rows and report stability metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable
import time

from bilinc.eval.capture import EvalCaptureRow


@dataclass
class ReplayReport:
    schema_version: int = 1
    summary: dict[str, Any] = field(default_factory=dict)
    regressions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "summary": self.summary,
            "regressions": self.regressions,
        }


def jaccard(a: list[str], b: list[str]) -> float:
    left = set(a)
    right = set(b)
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def top1_same(a: list[str], b: list[str]) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    return a[0] == b[0]


def _keys_from_results(results: Iterable[Any]) -> list[str]:
    keys = []
    for result in results:
        key = result.get("key") if isinstance(result, dict) else getattr(result, "key", None)
        if key is not None:
            keys.append(str(key))
    return keys


async def replay_rows(plane, rows: list[EvalCaptureRow], limit: int | None = None) -> ReplayReport:
    replayed = rows[:limit] if limit is not None else rows
    jaccards: list[float] = []
    top1_results: list[bool] = []
    latency_deltas: list[int] = []
    regressions: list[dict[str, Any]] = []

    previous_suppression = getattr(plane, "_suppress_eval_capture", False)
    setattr(plane, "_suppress_eval_capture", True)
    try:
        for row in replayed:
            started = time.perf_counter()
            if row.tool_name == "bilinc_recall_smart":
                payload = await plane.recall_reflective(row.query, limit=len(row.retrieved_keys) or 10)
                current_keys = _keys_from_results(payload.get("results", []))
            elif row.tool_name in {"recall", "recall_intelligent"}:
                if row.tool_name == "recall_intelligent":
                    results = await plane.recall_intelligent(row.query, limit=len(row.retrieved_keys) or 10)
                else:
                    detail = row.detail or {}
                    memory_type = detail.get("memory_type")
                    if detail.get("key") is not None:
                        results = await plane.recall(key=str(detail["key"]), limit=len(row.retrieved_keys) or 50)
                    elif memory_type:
                        from bilinc.core.models import MemoryType

                        results = await plane.recall(memory_type=MemoryType(str(memory_type)), limit=len(row.retrieved_keys) or 50)
                    elif row.query:
                        results = await plane.recall(key=row.query, limit=len(row.retrieved_keys) or 50)
                    else:
                        results = await plane.recall(limit=len(row.retrieved_keys) or 50)
                current_keys = _keys_from_results(results)
            else:
                current_keys = []
            latency_ms = int((time.perf_counter() - started) * 1000)
            jac = jaccard(row.retrieved_keys, current_keys)
            top1 = top1_same(row.retrieved_keys, current_keys)
            jaccards.append(jac)
            top1_results.append(top1)
            latency_deltas.append(latency_ms - row.latency_ms)
            if jac < 1.0 or not top1:
                regressions.append({
                    "query": row.query,
                    "tool_name": row.tool_name,
                    "expected_keys": row.retrieved_keys,
                    "actual_keys": current_keys,
                    "jaccard": jac,
                    "top1_same": top1,
                    "latency_delta_ms": latency_ms - row.latency_ms,
                })
    finally:
        setattr(plane, "_suppress_eval_capture", previous_suppression)

    count = len(replayed)
    summary = {
        "rows_total": len(rows),
        "rows_replayed": count,
        "mean_jaccard": sum(jaccards) / count if count else 1.0,
        "top1_stability_rate": sum(1 for value in top1_results if value) / count if count else 1.0,
        "mean_latency_delta_ms": int(sum(latency_deltas) / count) if count else 0,
    }
    return ReplayReport(summary=summary, regressions=regressions[:20])
