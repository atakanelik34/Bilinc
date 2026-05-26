"""Evaluation capture, replay, and read-only probe utilities for Bilinc."""

from bilinc.eval.capture import EvalCaptureRow, capture_enabled, row_from_jsonl, row_to_jsonl, scrub_query
from bilinc.eval.receipts import EvalReceipt, EvalReceiptError, create_eval_receipt, receipt_to_json
from bilinc.eval.contradictions import (
    ContradictionFinding,
    ContradictionPair,
    ContradictionReport,
    detect_claim_contradictions,
    find_contradiction_pairs,
    probe_claim_contradictions_for_queries,
    wilson_ci,
)

__all__ = [
    "ContradictionFinding",
    "ContradictionPair",
    "ContradictionReport",
    "EvalCaptureRow",
    "EvalReceipt",
    "EvalReceiptError",
    "capture_enabled",
    "create_eval_receipt",
    "detect_claim_contradictions",
    "find_contradiction_pairs",
    "probe_claim_contradictions_for_queries",
    "row_from_jsonl",
    "row_to_jsonl",
    "scrub_query",
    "receipt_to_json",
    "wilson_ci",
]
