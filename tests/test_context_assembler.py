import json

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.core import ContextAssembler as LazyContextAssembler
from bilinc.core.context_assembler import ContextAssembler
from bilinc.core.models import ClaimKind, MemoryType
from bilinc.storage.sqlite import SQLiteBackend


async def make_temp_plane(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "context.db"))
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    plane.init_agm()
    plane.init_knowledge_graph()
    return plane


def test_context_assembler_is_available_from_core_lazy_imports():
    assert LazyContextAssembler is ContextAssembler


@pytest.mark.asyncio
async def test_context_assembler_builds_budgeted_memory_sections(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit("work:pricing", "Bilinc pricing sprint active task", MemoryType.WORKING)
    await plane.commit("episode:pricing", "Yesterday we decided Bilinc pricing stays simple", MemoryType.EPISODIC)
    await plane.commit("semantic:pricing", "Bilinc pricing has Pro and Team plans", MemoryType.SEMANTIC)
    await plane.commit("procedure:pricing", "When pricing changes, run billing verification", MemoryType.PROCEDURAL)

    bundle = await ContextAssembler(plane).assemble(
        "Bilinc pricing verification",
        profile="balanced",
        limit=10,
        budget_tokens=160,
    )

    assert bundle.query == "Bilinc pricing verification"
    assert bundle.profile == "balanced"
    assert bundle.read_only is True
    assert bundle.token_estimate <= 160
    assert bundle.selected_memory_keys == [
        "semantic:pricing",
        "work:pricing",
        "episode:pricing",
        "procedure:pricing",
    ]
    assert bundle.section("stable_facts").items[0]["key"] == "semantic:pricing"
    assert bundle.section("active_context").items[0]["key"] == "work:pricing"
    assert bundle.section("recent_relevant_events").items[0]["key"] == "episode:pricing"
    assert bundle.section("preferences_and_procedures").items[0]["key"] == "procedure:pricing"
    assert "## Stable facts" in bundle.prompt_block
    assert "semantic:pricing" in bundle.prompt_block


@pytest.mark.asyncio
async def test_verified_context_includes_scoped_claims_and_contradiction_warnings(tmp_path):
    plane = await make_temp_plane(tmp_path)
    await plane.commit(
        "mem:apollo-open",
        "Apollo status open",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [{
                "holder": "agent",
                "subject": "Apollo",
                "claim": "Apollo status open",
                "kind": ClaimKind.FACT.value,
                "metadata": {"predicate": "status", "object": "open"},
            }]
        },
    )
    await plane.commit(
        "mem:apollo-closed",
        "Apollo status closed",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [{
                "holder": "agent",
                "subject": "Apollo",
                "claim": "Apollo status closed",
                "kind": ClaimKind.FACT.value,
                "metadata": {"predicate": "status", "object": "closed"},
            }]
        },
    )
    await plane.commit(
        "mem:zeus-private",
        "Zeus private classified",
        MemoryType.SEMANTIC,
        metadata={
            "claims": [{
                "holder": "agent",
                "subject": "Zeus",
                "claim": "Zeus status classified",
                "kind": ClaimKind.FACT.value,
                "metadata": {"predicate": "status", "object": "classified"},
            }]
        },
    )

    bundle = await ContextAssembler(plane).assemble("Apollo status", profile="verified", limit=2, budget_tokens=220)
    dumped = json.dumps(bundle.to_dict())

    assert set(bundle.selected_memory_keys) == {"mem:apollo-open", "mem:apollo-closed"}
    assert bundle.evidence["claims"]
    assert bundle.evidence["contradictions"]["count"] == 1
    assert any(warning["type"] == "contradiction" for warning in bundle.warnings)
    assert "mem:zeus-private" not in dumped
    assert "classified" not in dumped


@pytest.mark.asyncio
async def test_context_assembler_truncates_to_budget_and_reports_omissions(tmp_path):
    plane = await make_temp_plane(tmp_path)
    for idx in range(5):
        await plane.commit(
            f"mem:budget:{idx}",
            "Bilinc budget token pressure " + ("detail " * 25) + str(idx),
            MemoryType.SEMANTIC,
            importance=1.0 - (idx * 0.05),
        )

    bundle = await ContextAssembler(plane).assemble("Bilinc budget", profile="fast", limit=5, budget_tokens=45)

    assert bundle.token_estimate <= 45
    assert bundle.omitted_counts["items"] > 0
    assert bundle.evidence_refs
    assert bundle.prompt_block.count("mem:budget:") < 5


@pytest.mark.asyncio
async def test_context_assembler_drops_contradictions_when_budget_removes_supporting_memory(tmp_path):
    plane = await make_temp_plane(tmp_path)
    for key, status in [("mem:apollo-open", "open"), ("mem:apollo-closed", "closed")]:
        await plane.commit(
            key,
            f"Apollo status {status} " + ("detail " * 20),
            MemoryType.SEMANTIC,
            metadata={
                "claims": [{
                    "holder": "agent",
                    "subject": "Apollo",
                    "claim": f"Apollo status {status}",
                    "kind": ClaimKind.FACT.value,
                    "metadata": {"predicate": "status", "object": status},
                }]
            },
        )

    bundle = await ContextAssembler(plane).assemble("Apollo status", profile="verified", limit=2, budget_tokens=35)

    assert len(bundle.selected_memory_keys) == 1
    assert bundle.evidence["contradictions"]["count"] == 0
    assert not any(warning["type"] == "contradiction" for warning in bundle.warnings)


@pytest.mark.asyncio
async def test_context_assembler_is_read_only_and_does_not_capture_eval_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("BILINC_EVAL_CAPTURE", "1")
    plane = await make_temp_plane(tmp_path)
    await plane.commit("mem:readonly", "Bilinc readonly context assembly", MemoryType.SEMANTIC)
    before = len(await plane.backend.list_eval_candidates())

    bundle = await ContextAssembler(plane).assemble("Bilinc readonly", profile="balanced", limit=3)
    after = len(await plane.backend.list_eval_candidates())

    assert bundle.read_only is True
    assert before == after == 0
