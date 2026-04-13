import time
import pytest
from bilinc.core.blind_spots import BlindSpotType, BlindSpot, BlindSpotReport, BlindSpotDetector

class TestReport:
    def test_empty(self):
        r = BlindSpotReport()
        assert r.orphan_count == 0 and r.health_score == 1.0
    def test_to_dict(self):
        r = BlindSpotReport(total_nodes=3, total_edges=1)
        r.blind_spots.append(BlindSpot(BlindSpotType.ORPHAN, "x", 0.9, "x", "x"))
        assert r.to_dict()["counts"]["orphan"] == 1
    def test_critical(self):
        r = BlindSpotReport()
        r.blind_spots.append(BlindSpot(BlindSpotType.ORPHAN, "a", 0.9, "", ""))
        r.blind_spots.append(BlindSpot(BlindSpotType.SHALLOW, "b", 0.3, "", ""))
        assert len(r.critical_spots) == 1

class TestDetector:
    def d(self):
        return BlindSpotDetector(stale_days=7.0, shallow_threshold=2)
    def test_no_nodes(self):
        assert self.d().analyze([], lambda k: [], lambda k: None).health_score == 0.0
    def test_orphan(self):
        edges = {"a": [("related_to", "b")], "b": [], "c": []}
        r = self.d().analyze(["a","b","c"], lambda k: edges.get(k,[]), lambda k: None)
        assert r.orphan_count == 2
    def test_shallow(self):
        edges = {"a": [("related_to","b")], "b": [("related_to","a")]}
        r = self.d().analyze(["a","b"], lambda k: edges.get(k,[]), lambda k: None)
        assert r.shallow_count == 2
    def test_stale(self):
        old = time.time() - 86400*30
        upd = {"a": old, "b": time.time()}
        edges = {"a": [("r","b")], "b": [("r","a")]}
        r = self.d().analyze(["a","b"], lambda k: edges.get(k,[]), lambda k: upd.get(k))
        assert r.stale_count == 1
    def test_island(self):
        edges = {"a":[("r","b")], "b":[("r","a")], "c":[("r","d")], "d":[("r","c")]}
        r = self.d().analyze(["a","b","c","d"], lambda k: edges.get(k,[]), lambda k: None)
        isolated = [s for s in r.blind_spots if s.spot_type == BlindSpotType.ISOLATED]
        assert len(isolated) == 2
    def test_health_broken_lt_healthy(self):
        d = self.d()
        h = d.analyze(["a","b"], lambda k: [("r","a"),("r","b")], lambda k: time.time())
        b = d.analyze(["a","b"], lambda k: [], lambda k: None)
        assert b.health_score < h.health_score
    def test_severity_sorted(self):
        edges = {"orphan":[], "shallow":[("r","healthy")], "healthy":[("r","shallow"),("r","orphan")]}
        r = self.d().analyze(["orphan","shallow","healthy"], lambda k: edges.get(k,[]), lambda k: None)
        sevs = [s.severity for s in r.blind_spots]
        assert sevs == sorted(sevs, reverse=True)