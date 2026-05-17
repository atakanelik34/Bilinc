"""Read-only contradiction probes over projected claim rows."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from math import sqrt
import time
from typing import Any

from bilinc.core.models import Claim, ClaimKind

SCALAR_TYPES = (str, int, float, bool)


@dataclass(frozen=True)
class ContradictionPair:
    """Two projected claims that disagree on one scalar predicate value."""

    left: Claim
    right: Claim
    predicate: str
    left_object: Any
    right_object: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "predicate": self.predicate,
            "left_object": self.left_object,
            "right_object": self.right_object,
        }


@dataclass(frozen=True)
class ContradictionFinding:
    """Human-readable contradiction finding derived from a claim pair."""

    subject: str
    holder: str
    predicate: str
    left_claim_id: str
    right_claim_id: str
    left_object: Any
    right_object: Any
    severity: float
    suggested_action: str
    claim_kinds: tuple[str, ...] = field(default_factory=tuple)
    memory_keys: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "holder": self.holder,
            "predicate": self.predicate,
            "left_claim_id": self.left_claim_id,
            "right_claim_id": self.right_claim_id,
            "left_object": self.left_object,
            "right_object": self.right_object,
            "severity": self.severity,
            "suggested_action": self.suggested_action,
            "claim_kinds": list(self.claim_kinds),
            "memory_keys": list(self.memory_keys),
        }


@dataclass(frozen=True)
class ContradictionReport:
    """Aggregate report for contradiction probes."""

    findings: list[ContradictionFinding]
    queries_evaluated: int = 0
    queries_with_contradiction: int = 0
    wilson_ci_95_low: float | None = None
    wilson_ci_95_high: float | None = None
    small_sample_note: str | None = None
    hot_subjects: list[dict[str, Any]] = field(default_factory=list)
    hot_keys: list[dict[str, Any]] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)

    @classmethod
    def from_findings(
        cls,
        findings: list[ContradictionFinding],
        *,
        queries_evaluated: int = 0,
        queries_with_contradiction: int = 0,
    ) -> "ContradictionReport":
        ci_low = None
        ci_high = None
        small_sample_note = None
        if queries_evaluated >= 30:
            ci_low, ci_high = wilson_ci(queries_with_contradiction, queries_evaluated)
        elif queries_evaluated > 0:
            small_sample_note = "Wilson interval suppressed: fewer than 30 evaluated queries."

        subject_counts = Counter(finding.subject for finding in findings)
        hot_subjects = [
            {"subject": subject, "count": count}
            for subject, count in subject_counts.most_common(10)
        ]
        key_counts: Counter[str] = Counter()
        for finding in findings:
            key_counts.update(finding.memory_keys)
        hot_keys = [
            {"memory_key": key, "count": count}
            for key, count in key_counts.most_common(10)
        ]
        suggested_actions = []
        for finding in findings:
            if finding.suggested_action not in suggested_actions:
                suggested_actions.append(finding.suggested_action)

        return cls(
            findings=findings,
            queries_evaluated=queries_evaluated,
            queries_with_contradiction=queries_with_contradiction,
            wilson_ci_95_low=ci_low,
            wilson_ci_95_high=ci_high,
            small_sample_note=small_sample_note,
            hot_subjects=hot_subjects,
            hot_keys=hot_keys,
            suggested_actions=suggested_actions,
        )

    def to_dict(self) -> dict[str, Any]:
        contradiction_rate = (
            self.queries_with_contradiction / self.queries_evaluated
            if self.queries_evaluated
            else 0.0
        )
        return {
            "count": len(self.findings),
            "total_findings": len(self.findings),
            "total_pairs": len(self.findings),
            "findings": [finding.to_dict() for finding in self.findings],
            "queries_evaluated": self.queries_evaluated,
            "queries_with_contradiction": self.queries_with_contradiction,
            "contradiction_rate": contradiction_rate,
            "wilson_ci_95_low": self.wilson_ci_95_low,
            "wilson_ci_95_high": self.wilson_ci_95_high,
            "small_sample_note": self.small_sample_note,
            "hot_subjects": self.hot_subjects,
            "hot_keys": self.hot_keys,
            "suggested_actions": self.suggested_actions,
        }


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Return the Wilson score interval for a binomial proportion."""
    if n <= 0:
        raise ValueError("n must be positive")
    successes = max(0, min(int(successes), int(n)))
    n = int(n)
    p_hat = successes / n
    denominator = 1 + (z * z) / n
    center = p_hat + (z * z) / (2 * n)
    margin = z * sqrt((p_hat * (1 - p_hat) + (z * z) / (4 * n)) / n)
    return ((center - margin) / denominator, (center + margin) / denominator)


def find_contradiction_pairs(claims: list[Claim]) -> list[ContradictionPair]:
    """Find active same-holder/subject/predicate claim pairs with different scalar objects."""
    pairs: list[ContradictionPair] = []
    normalized = [_claim_projection(claim) for claim in claims if _is_current_claim(claim)]
    for index, left in enumerate(normalized):
        if left is None:
            continue
        for right in normalized[index + 1:]:
            if right is None:
                continue
            if left["holder"] != right["holder"]:
                continue
            if left["subject"] != right["subject"]:
                continue
            if left["predicate"] != right["predicate"]:
                continue
            if not _validity_windows_overlap(left["claim"], right["claim"]):
                continue
            if left["object"] == right["object"]:
                continue
            pairs.append(ContradictionPair(left["claim"], right["claim"], left["predicate"], left["object"], right["object"]))
    return pairs


def detect_claim_contradictions(claims: list[Claim], judge: Any | None = None) -> list[ContradictionFinding]:
    """Convert contradiction pairs into sorted report findings.

    ``judge`` is a reserved seam for a future optional reviewer. It is disabled
    by default and not invoked in this deterministic sprint.
    """
    del judge
    findings = [_finding_from_pair(pair) for pair in find_contradiction_pairs(claims)]
    return sorted(findings, key=lambda item: (-item.severity, item.subject, item.predicate, item.left_claim_id))


async def probe_claim_contradictions_for_queries(plane, queries: list[str], top_k: int = 5) -> ContradictionReport:
    """Run a read-only contradiction probe over claims surfaced by recall queries."""
    if not getattr(plane, "backend", None) or not hasattr(plane.backend, "list_claims"):
        return ContradictionReport.from_findings([], queries_evaluated=len(queries), queries_with_contradiction=0)

    all_claims = await plane.backend.list_claims(active=True, limit=1000)
    by_memory_key: dict[str, list[Claim]] = {}
    by_subject: dict[str, list[Claim]] = {}
    for claim in all_claims:
        by_memory_key.setdefault(claim.memory_key, []).append(claim)
        by_subject.setdefault(claim.subject, []).append(claim)

    findings: list[ContradictionFinding] = []
    queries_with_contradiction = 0
    seen_finding_keys: set[tuple[str, str, str]] = set()
    for query in queries:
        results = await plane.recall_intelligent(query, limit=top_k)
        selected: list[Claim] = []
        for result in results:
            key = result.get("key") if isinstance(result, dict) else getattr(result, "key", None)
            if key is None:
                continue
            for claim in by_memory_key.get(str(key), []):
                selected.append(claim)
                selected.extend(by_subject.get(claim.subject, []))
        query_findings = detect_claim_contradictions(_dedupe_claims(selected))
        if query_findings:
            queries_with_contradiction += 1
        for finding in query_findings:
            finding_key = (finding.left_claim_id, finding.right_claim_id, finding.predicate)
            if finding_key in seen_finding_keys:
                continue
            seen_finding_keys.add(finding_key)
            findings.append(finding)

    return ContradictionReport.from_findings(
        findings,
        queries_evaluated=len(queries),
        queries_with_contradiction=queries_with_contradiction,
    )


def _dedupe_claims(claims: list[Claim]) -> list[Claim]:
    seen: set[str] = set()
    deduped: list[Claim] = []
    for claim in claims:
        if claim.id in seen:
            continue
        seen.add(claim.id)
        deduped.append(claim)
    return deduped


def _claim_projection(claim: Claim) -> dict[str, Any] | None:
    metadata = claim.metadata if isinstance(claim.metadata, dict) else {}
    predicate = metadata.get("predicate")
    obj = metadata.get("object")
    if not isinstance(predicate, str) or not predicate.strip():
        return None
    if not isinstance(obj, SCALAR_TYPES) or obj is None:
        return None
    return {
        "claim": claim,
        "holder": claim.holder,
        "subject": claim.subject,
        "predicate": predicate.strip(),
        "object": obj,
    }


def _validity_windows_overlap(left: Claim, right: Claim) -> bool:
    left_start = float("-inf") if left.valid_at is None else float(left.valid_at)
    left_end = float("inf") if left.invalid_at is None else float(left.invalid_at)
    right_start = float("-inf") if right.valid_at is None else float(right.valid_at)
    right_end = float("inf") if right.invalid_at is None else float(right.invalid_at)
    return max(left_start, right_start) <= min(left_end, right_end)


def _is_current_claim(claim: Claim, now: float | None = None) -> bool:
    if not getattr(claim, "active", True):
        return False
    now = time.time() if now is None else now
    if claim.valid_at is not None and float(claim.valid_at) > now:
        return False
    if claim.invalid_at is not None and float(claim.invalid_at) <= now:
        return False
    return True


def _finding_from_pair(pair: ContradictionPair) -> ContradictionFinding:
    severity = _severity(pair.left.kind, pair.right.kind)
    return ContradictionFinding(
        subject=pair.left.subject,
        holder=pair.left.holder,
        predicate=pair.predicate,
        left_claim_id=pair.left.id,
        right_claim_id=pair.right.id,
        left_object=pair.left_object,
        right_object=pair.right_object,
        severity=severity,
        suggested_action=(
            "Review source memories and either supersede the stale claim or narrow validity windows."
        ),
        claim_kinds=(pair.left.kind.value, pair.right.kind.value),
        memory_keys=(pair.left.memory_key, pair.right.memory_key),
    )


def _severity(left_kind: ClaimKind, right_kind: ClaimKind) -> float:
    weights = {
        ClaimKind.FACT: 0.9,
        ClaimKind.COMMITMENT: 0.85,
        ClaimKind.BELIEF: 0.7,
        ClaimKind.PREFERENCE: 0.55,
        ClaimKind.PREDICTION: 0.5,
        ClaimKind.HUNCH: 0.35,
    }
    return min(weights.get(left_kind, 0.5), weights.get(right_kind, 0.5))
