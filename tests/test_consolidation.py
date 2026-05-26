import time
import pytest
from bilinc.core.consolidation import ConsolidationStage, ConsolidationResult, ConsolidationReport, ConsolidationPipeline

class TestResult:
    def test_to_dict(self):
        r = ConsolidationResult(stage=ConsolidationStage.FACT_DISTILLATION, entries_processed=10)
        assert r.to_dict()["stage"] == "fact_distillation"

class TestReport:
    def test_add_stage(self):
        r = ConsolidationReport()
        r.add_stage(ConsolidationResult(stage=ConsolidationStage.DECAY_APPLICATION, entries_processed=5, entries_pruned=2))
        assert r.total_processed == 5 and r.total_pruned == 2

class TestPipeline:
    def entries(self, n=5):
        now = time.time()
        return [{"key": f"k{i}", "memory_type": "semantic", "importance": 0.5,
                 "current_strength": 0.8, "access_count": i,
                 "last_accessed": now - 86400*i, "created_at": now - 86400*i}
                for i in range(n)]
    def test_empty(self):
        r = ConsolidationPipeline().run([])
        assert r.total_processed == 0 and len(r.stages) == 3
    def test_basic(self):
        r = ConsolidationPipeline().run(self.entries(10))
        assert r.total_processed > 0 and r.health_score >= 0
    def test_stage_order(self):
        r = ConsolidationPipeline().run(self.entries())
        assert r.stages[0].stage == ConsolidationStage.FACT_DISTILLATION
        assert r.stages[1].stage == ConsolidationStage.DECAY_APPLICATION
        assert r.stages[2].stage == ConsolidationStage.GRAPH_STRENGTHENING
    def test_report_dict(self):
        d = ConsolidationPipeline().run(self.entries()).to_dict()
        assert "health_score" in d and len(d["stages"]) == 3