"""IMP-004: the runtime modules nothing called are gone, and nothing still reaches them.

Removed: the two deprecated MCP server shims, the second hybrid retriever, the KG spreading-activation recall,
the System 1/System 2 arbiter with its confidence estimator, the RL context budget and the learnable forgetting
model. Git history keeps the code.
"""
from __future__ import annotations

import importlib

import pytest

from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend

REMOVED_MODULES = [
    "bilinc.mcp_server.server",
    "bilinc.mcp_server._deprecated_server",
    "bilinc.retrieval",
    "bilinc.retrieval.hybrid",
    "bilinc.core.kg_retrieval",
    "bilinc.core.dual_process",
    "bilinc.core.confidence",
    "bilinc.adaptive.budget",
    "bilinc.adaptive.forgetting",
]
REMOVED_CORE_NAMES = [
    "ConfidenceEstimator", "ConfidenceScore", "System1Engine", "System2Engine", "Arbiter",
    "KGSpreadingActivation", "ActivationResult", "kg_enhanced_recall",
]


@pytest.mark.parametrize("module", REMOVED_MODULES)
def test_removed_module_cannot_be_imported(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_core_no_longer_exports_the_removed_names():
    import bilinc.core as core

    for name in REMOVED_CORE_NAMES:
        assert name not in core.__all__
        assert not hasattr(core, name)
    assert hasattr(core, "StatePlane") and hasattr(core, "AuditTrail")       # the rest still resolves


def test_adaptive_exports_only_the_agm_engine():
    import bilinc.adaptive as adaptive

    assert sorted(adaptive.__all__) == ["AGMEngine", "AGMOperation", "AGMResult", "ConflictStrategy"]


@pytest.mark.asyncio
async def test_a_plane_has_no_arbiter_and_health_still_reads_its_stats(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "plane.sqlite"))
    await backend.init()
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=True)
    await plane.init()
    try:
        for name in ("arbiter", "s1", "s2", "estimator"):
            assert not hasattr(plane, name)
        assert not hasattr(plane, "route_query")
        for n in range(3):
            await plane.commit(f"k{n}", f"v{n}")
        stats = await plane.stats()
        assert "arbiter" not in stats
        report = await plane.health_metrics_report()
        assert report["backend_total_entries"] == 3
        assert report["ops_count"] == stats["ops_count"] and report["ops_count"] >= 3
        assert isinstance(report["working_memory_usage"], float)
    finally:
        await backend.close()
