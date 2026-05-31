import asyncio
import json
import os
import subprocess
import sys

import pytest

from bilinc.core.models import Claim, ClaimKind
from bilinc.storage.sqlite import SQLiteBackend
from bilinc.eval.contradictions import (
    ContradictionReport,
    detect_claim_contradictions,
    find_contradiction_pairs,
    probe_claim_contradictions_for_queries,
    wilson_ci,
)


def make_claim(subject, claim, *, holder="atakan", kind=ClaimKind.FACT, metadata=None, valid_at=None, invalid_at=None):
    return Claim(
        memory_key=f"mem:{subject}:{claim}",
        holder=holder,
        subject=subject,
        claim=claim,
        kind=kind,
        valid_at=valid_at,
        invalid_at=invalid_at,
        metadata=metadata or {},
    )


def test_no_contradiction_when_validity_windows_do_not_overlap():
    left = make_claim("ReARC", "status active", metadata={"predicate": "status", "object": "active"}, valid_at=1, invalid_at=10)
    right = make_claim("ReARC", "status inactive", metadata={"predicate": "status", "object": "inactive"}, valid_at=20, invalid_at=30)

    findings = detect_claim_contradictions([left, right])

    assert findings == []


def test_expired_claims_are_not_current_contradictions():
    expired = make_claim("ReARC", "status inactive", metadata={"predicate": "status", "object": "inactive"}, invalid_at=1)
    current = make_claim("ReARC", "status active", metadata={"predicate": "status", "object": "active"})

    findings = detect_claim_contradictions([expired, current])

    assert findings == []


def test_contradiction_when_same_predicate_has_different_active_scalar_values():
    left = make_claim("ReARC", "status active", metadata={"predicate": "status", "object": "active"})
    right = make_claim("ReARC", "status inactive", metadata={"predicate": "status", "object": "inactive"})

    findings = detect_claim_contradictions([left, right])

    assert len(findings) == 1
    assert findings[0].subject == "ReARC"
    assert findings[0].predicate == "status"
    assert findings[0].severity >= 0.8
    assert findings[0].suggested_action


def test_opinion_claims_are_lower_severity_than_facts():
    fact_left = make_claim("Bilinc", "tier paid", kind=ClaimKind.FACT, metadata={"predicate": "tier", "object": "paid"})
    fact_right = make_claim("Bilinc", "tier free", kind=ClaimKind.FACT, metadata={"predicate": "tier", "object": "free"})
    hunch_left = make_claim("Bilinc", "tier paid", kind=ClaimKind.HUNCH, metadata={"predicate": "tier", "object": "paid"})
    hunch_right = make_claim("Bilinc", "tier free", kind=ClaimKind.HUNCH, metadata={"predicate": "tier", "object": "free"})

    fact = detect_claim_contradictions([fact_left, fact_right])[0]
    hunch = detect_claim_contradictions([hunch_left, hunch_right])[0]

    assert hunch.severity < fact.severity


def test_find_contradiction_pairs_same_holder_subject_predicate_only():
    pairable_a = make_claim("ReARC", "status active", metadata={"predicate": "status", "object": "active"})
    pairable_b = make_claim("ReARC", "status inactive", metadata={"predicate": "status", "object": "inactive"})
    other_subject = make_claim("Bilinc", "status inactive", metadata={"predicate": "status", "object": "inactive"})

    pairs = find_contradiction_pairs([pairable_a, pairable_b, other_subject])

    assert len(pairs) == 1
    assert pairs[0].left.id == pairable_a.id
    assert pairs[0].right.id == pairable_b.id


def test_wilson_interval_known_values():
    low, high = wilson_ci(successes=50, n=100)

    assert low == pytest.approx(0.4038, abs=0.001)
    assert high == pytest.approx(0.5962, abs=0.001)


def test_report_small_sample_and_hot_subjects():
    left = make_claim("ReARC", "status active", metadata={"predicate": "status", "object": "active"})
    right = make_claim("ReARC", "status inactive", metadata={"predicate": "status", "object": "inactive"})
    findings = detect_claim_contradictions([left, right])

    report = ContradictionReport.from_findings(findings, queries_evaluated=2, queries_with_contradiction=1)
    payload = report.to_dict()

    assert payload["small_sample_note"]
    assert payload["wilson_ci_95_low"] is None
    assert payload["hot_subjects"][0]["subject"] == "ReARC"
    assert payload["hot_keys"][0]["memory_key"] in {"mem:ReARC:status active", "mem:ReARC:status inactive"}
    assert payload["total_findings"] == 1
    assert payload["contradiction_rate"] == 0.5
    assert payload["suggested_actions"]


def test_report_wilson_interval_when_sample_size_is_sufficient():
    findings = []

    report = ContradictionReport.from_findings(findings, queries_evaluated=100, queries_with_contradiction=25)
    payload = report.to_dict()

    assert payload["small_sample_note"] is None
    assert payload["wilson_ci_95_low"] == pytest.approx(0.1755, abs=0.001)
    assert payload["wilson_ci_95_high"] == pytest.approx(0.3430, abs=0.001)


def test_detect_claim_contradictions_can_disable_optional_judge_seam():
    left = make_claim("ReARC", "status active", metadata={"predicate": "status", "object": "active"})
    right = make_claim("ReARC", "status inactive", metadata={"predicate": "status", "object": "inactive"})

    findings = detect_claim_contradictions([left, right], judge=None)

    assert len(findings) == 1


@pytest.mark.asyncio
async def test_probe_claim_contradictions_for_queries_uses_recall_linked_claims(tmp_path):
    from bilinc.core.stateplane import StatePlane
    from bilinc.core.models import MemoryType

    backend = SQLiteBackend(str(tmp_path / "probe.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    await plane.commit(
        "mem:paid",
        "Bilinc tier paid",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [{
                "holder": "atakan",
                "subject": "Bilinc",
                "claim": "Bilinc tier paid",
                "kind": "fact",
                "metadata": {"predicate": "tier", "object": "paid"},
            }]
        },
    )
    await plane.commit(
        "mem:free",
        "Bilinc tier free",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [{
                "holder": "atakan",
                "subject": "Bilinc",
                "claim": "Bilinc tier free",
                "kind": "fact",
                "metadata": {"predicate": "tier", "object": "free"},
            }]
        },
    )

    report = await probe_claim_contradictions_for_queries(plane, ["Bilinc tier"], top_k=2)
    payload = report.to_dict()

    assert payload["queries_evaluated"] == 1
    assert payload["queries_with_contradiction"] == 1
    assert payload["count"] == 1


def cli_env():
    src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    env = os.environ.copy()
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_eval_contradictions_cli_prints_json_report(tmp_path):
    db_path = tmp_path / "claims.db"

    async def seed():
        backend = SQLiteBackend(str(db_path))
        await backend.init()
        await backend.save_claim(make_claim("Bilinc", "tier paid", metadata={"predicate": "tier", "object": "paid"}))
        await backend.save_claim(make_claim("Bilinc", "tier free", metadata={"predicate": "tier", "object": "free"}))
        await backend.close()

    asyncio.run(seed())

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bilinc.cli.main",
            "--db",
            str(db_path),
            "eval",
            "contradictions",
            "--subject",
            "Bilinc",
            "--json",
        ],
        check=True,
        text=True,
        capture_output=True,
        env=cli_env(),
    )

    payload = json.loads(result.stdout)
    assert payload["tool"] == "eval_contradictions"
    assert payload["read_only"] is True
    assert payload["count"] == 1
    assert payload["findings"][0]["predicate"] == "tier"
