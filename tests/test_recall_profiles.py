import json
import os
import subprocess
import sys

import pytest

from bilinc import StatePlane
from bilinc.core.models import ClaimKind, MemoryType
from bilinc.mcp_server.server_v2 import _handle_bilinc_recall_smart
from bilinc.storage.sqlite import SQLiteBackend


async def make_temp_plane(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "profiles.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


def cli_env():
    src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    env = os.environ.copy()
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
    return env


@pytest.mark.asyncio
async def test_resolve_recall_profiles_are_stable():
    plane = StatePlane(enable_verification=False, enable_audit=False)

    fast = plane.resolve_recall_profile("fast")
    balanced = plane.resolve_recall_profile(None)
    verified = plane.resolve_recall_profile("verified")
    deep = plane.resolve_recall_profile("deep")

    assert balanced["name"] == "balanced"
    assert fast["max_reflections"] == 0
    assert deep["max_reflections"] > balanced["max_reflections"]
    assert verified["include_claims"] is True
    assert verified["include_contradictions"] is True


@pytest.mark.asyncio
async def test_recall_profiled_fast_disables_reflection_loop(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:fast", "Bilinc recall profile fast path", MemoryType.SEMANTIC)

    payload = await plane.recall_profiled("Bilinc profile", profile="fast", limit=3)

    assert payload["profile"] == "fast"
    assert payload["recall_profile"]["max_reflections"] == 0
    assert payload["max_reflections"] == 0
    assert payload["reflections_used"] == 0
    assert payload["results"]


@pytest.mark.asyncio
async def test_recall_profiled_verified_adds_claim_and_contradiction_evidence(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:paid",
        "Bilinc tier paid",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [{
                "holder": "atakan",
                "subject": "Bilinc",
                "claim": "Bilinc tier paid",
                "kind": ClaimKind.FACT.value,
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
                "kind": ClaimKind.FACT.value,
                "metadata": {"predicate": "tier", "object": "free"},
            }]
        },
    )

    payload = await plane.recall_profiled("Bilinc tier", profile="verified", limit=5)

    assert payload["profile"] == "verified"
    assert payload["evidence"]["claims"]
    assert payload["evidence"]["contradictions"]["count"] == 1
    assert payload["read_only"] is True


@pytest.mark.asyncio
async def test_recall_profiled_verified_constrains_contradictions_to_recalled_keys(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:target",
        "Apollo public status open",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [{
                "holder": "atakan",
                "subject": "Apollo",
                "claim": "Apollo status open",
                "kind": ClaimKind.FACT.value,
                "metadata": {"predicate": "status", "object": "open"},
            }]
        },
    )
    await plane.commit(
        "mem:other",
        "Apollo private unrelated classified",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [{
                "holder": "atakan",
                "subject": "Apollo",
                "claim": "Apollo status classified",
                "kind": ClaimKind.FACT.value,
                "metadata": {"predicate": "status", "object": "classified"},
            }]
        },
    )

    payload = await plane.recall_profiled("public open", profile="verified", limit=1)
    evidence_dump = json.dumps(payload.get("evidence", {}))

    assert [result["key"] for result in payload["results"]] == ["mem:target"]
    assert "mem:other" not in evidence_dump
    assert "classified" not in evidence_dump
    assert payload["evidence"]["contradictions"]["count"] == 0


@pytest.mark.asyncio
async def test_mcp_smart_recall_accepts_profile(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:mcp", "Bilinc MCP profile", MemoryType.SEMANTIC)

    result = await _handle_bilinc_recall_smart(plane, {"query": "Bilinc", "profile": "fast", "limit": 3})
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert payload["profile"] == "fast"
    assert payload["recall_profile"]["max_reflections"] == 0


@pytest.mark.asyncio
async def test_mcp_profile_does_not_override_explicit_reflection_parameters(tmp_path):
    plane = await make_temp_plane(tmp_path)

    result = await _handle_bilinc_recall_smart(
        plane,
        {"query": "missing", "profile": "balanced", "max_reflections": 0, "adequacy_threshold": 0.99, "limit": 3},
    )
    payload = json.loads(result[0].text)

    assert payload["success"] is True
    assert payload["profile"] == "balanced"
    assert payload["max_reflections"] == 0
    assert payload["adequacy_threshold"] == 0.99
    assert len(payload["queries_tried"]) == 1


def test_cli_recall_profile_query_prints_json(tmp_path):
    db_path = tmp_path / "cli.db"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "bilinc.cli.main",
            "--db",
            str(db_path),
            "commit",
            "--key",
            "mem:cli",
            "--value",
            "Bilinc CLI profile",
            "--type",
            "semantic",
        ],
        check=True,
        text=True,
        capture_output=True,
        env=cli_env(),
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bilinc.cli.main",
            "--db",
            str(db_path),
            "recall",
            "--query",
            "Bilinc CLI",
            "--profile",
            "fast",
            "--json",
        ],
        check=True,
        text=True,
        capture_output=True,
        env=cli_env(),
    )
    payload = json.loads(result.stdout)

    assert payload["tool"] == "recall"
    assert payload["profile"] == "fast"
    assert payload["recall_profile"]["max_reflections"] == 0
    assert payload["results"]
