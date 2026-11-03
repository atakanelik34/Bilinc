"""A5r: every TTL read point honours ``invalid_at`` the way the TTL write rule sets it.

A TTL write sets ``ttl`` and ``invalid_at = write time + ttl`` and keeps ``created_at``.
When ``invalid_at`` is set it alone decides; ``created_at + ttl`` only counts for legacy
rows that have a TTL but no ``invalid_at``.
"""
from __future__ import annotations

import time

import pytest

from bilinc.core.models import BeliefState, MemoryEntry, ttl_expired
from bilinc.core.stateplane import StatePlane
from bilinc.core.verification import VerificationGate, VerificationStatus
from bilinc.core import graph_doctor
from bilinc.storage.sqlite import SQLiteBackend

NOW = 1_800_000_000.0


def _entry(key="k", *, created_ago=3600.0, ttl=60.0, invalid_in="future", **extra) -> MemoryEntry:
    """A row first written ``created_ago`` seconds ago, re-committed with a fresh TTL."""
    now = time.time()
    invalid_at = {"future": now + 600.0, "past": now - 5.0, None: None}[invalid_in]
    return MemoryEntry(key=key, value="v", created_at=now - created_ago, updated_at=float(int(now)),
                       ttl=ttl, invalid_at=invalid_at, **extra)


# ---- the predicate -------------------------------------------------------------------------

def test_predicate_invalid_at_alone_decides_when_set():
    assert ttl_expired(NOW - 3600, 60.0, NOW + 10, NOW) is False
    assert ttl_expired(NOW - 3600, 60.0, NOW - 10, NOW) is False  # expiry comes from the invalid_at check


def test_predicate_counts_created_at_plus_ttl_when_invalid_at_is_absent():
    assert ttl_expired(NOW - 3600, 60.0, None, NOW) is True
    assert ttl_expired(NOW - 10, 60.0, None, NOW) is False


@pytest.mark.parametrize("created_at,ttl", [(None, 60.0), (NOW, None), (None, None)])
def test_predicate_needs_both_created_at_and_ttl(created_at, ttl):
    assert ttl_expired(created_at, ttl, None, NOW) is False


def test_predicate_boundary_and_zero_ttl():
    assert ttl_expired(NOW - 60, 60.0, None, NOW) is True
    assert ttl_expired(NOW - 60, 60.0, None, NOW, strict=True) is False
    assert ttl_expired(NOW - 60.5, 60.0, None, NOW, strict=True) is True
    assert ttl_expired(NOW, 0.0, None, NOW) is True


# ---- read point 4: MemoryEntry.is_stale ----------------------------------------------------

def test_is_stale_ignores_created_at_when_invalid_at_is_in_the_future():
    assert _entry().is_stale() is False


def test_is_stale_controls_stay_expired():
    assert _entry(invalid_in="past").is_stale() is True
    assert _entry(invalid_in=None).is_stale() is True  # legacy ttl-only row


def test_is_stale_boundary_and_zero_invalid_at_keep_todays_behaviour():
    now = time.time()
    # invalid_at == 0.0 is "not set" for is_stale today, so the legacy ttl clause still applies
    legacy_zero = MemoryEntry(key="z", value="v", created_at=now - 3600, ttl=60.0, invalid_at=0.0)
    assert legacy_zero.is_stale() is True
    # the ttl clause is strict ("> ttl"): a row exactly ttl old is not stale yet
    exact = MemoryEntry(key="e", value="v", created_at=now - 60.0, ttl=1e9)
    assert exact.is_stale() is False


def test_belief_state_active_beliefs_keep_a_recommitted_ttl_row():
    state = BeliefState()
    state.beliefs["live"] = _entry("live")
    state.beliefs["gone"] = _entry("gone", invalid_in="past")
    assert [e.key for e in state.get_all_beliefs()] == ["live"]


# ---- read point 5: verification ------------------------------------------------------------

def test_verification_check_staleness_ignores_created_at_when_invalid_at_is_in_the_future():
    gate = VerificationGate()
    assert gate._check_staleness(_entry()).status != VerificationStatus.STALE
    assert gate._check_staleness(_entry(invalid_in="past")).status == VerificationStatus.STALE
    assert gate._check_staleness(_entry(invalid_in=None)).status == VerificationStatus.STALE


def test_verify_recall_keeps_a_recommitted_ttl_row():
    gate = VerificationGate()
    assert gate.verify_recall(_entry()).status != VerificationStatus.STALE


# ---- read point 6: graph doctor ------------------------------------------------------------

def test_graph_doctor_entry_status():
    now = time.time()
    live = graph_doctor._entry_status(_entry(), now)
    assert live["active"] is True and "ttl_expired" not in live["reasons"]
    gone = graph_doctor._entry_status(_entry(invalid_in="past"), now)
    assert "expired" in gone["reasons"] and gone["active"] is False
    legacy = graph_doctor._entry_status(_entry(invalid_in=None), now)
    assert "ttl_expired" in legacy["reasons"]


# ---- read point 3: quality flags -----------------------------------------------------------

def test_risk_flags_do_not_call_a_live_recommitted_row_expired():
    plane = StatePlane()
    assert "expired" not in plane._recall_risk_flags(_entry())
    assert "expired" in plane._recall_risk_flags(_entry(invalid_in="past"))
    assert "expired" in plane._recall_risk_flags(_entry(invalid_in=None))


# ---- read point 1: as-of filter ------------------------------------------------------------

def test_as_of_recall_keeps_a_recommitted_row_before_its_real_expiry():
    plane = StatePlane()
    now = time.time()
    live = _entry("live")
    legacy = _entry("legacy", invalid_in=None)
    gone = _entry("gone", invalid_in="past")
    candidates = {e.key: e for e in (live, legacy, gone)}
    kept = plane._filter_candidates_as_of(candidates, str(now))
    assert sorted(kept) == ["live"]


# ---- read point 2: ranking penalty ---------------------------------------------------------

def _boost(plane, entries):
    fused = {e.key: 1.0 for e in entries}
    plane._apply_current_state_boost("what is the current editor", fused, {e.key: e for e in entries})
    return fused


def test_ranking_does_not_penalise_a_live_recommitted_row():
    plane = StatePlane()
    assert plane._is_singular_current_state_query("what is the current editor")
    control = _entry("control", ttl=None, invalid_in=None)
    live = _entry("live")
    scores = _boost(plane, [control, live])
    assert scores["live"] == pytest.approx(scores["control"])


def test_ranking_still_penalises_expired_rows():
    plane = StatePlane()
    control = _entry("control", ttl=None, invalid_in=None)
    for key, kwargs in (("past", {"invalid_in": "past"}), ("legacy", {"invalid_in": None})):
        scores = _boost(plane, [control, _entry(key, **kwargs)])
        assert scores[key] == pytest.approx(scores["control"] - 0.04)


def test_ranking_keeps_a_missing_created_at_as_expired_for_a_ttl_row():
    plane = StatePlane()
    control = _entry("control", ttl=None, invalid_in=None)
    odd = _entry("odd", invalid_in=None)
    odd.created_at = None
    scores = _boost(plane, [control, odd])
    assert scores["odd"] == pytest.approx(scores["control"] - 0.04)


# ---- end to end through the real commit path, local SQLite ----------------------------------

@pytest.mark.asyncio
async def test_recommit_with_a_fresh_ttl_keeps_the_row_live_at_every_read_point(tmp_path):
    plane = StatePlane(backend=SQLiteBackend(str(tmp_path / "a5r.sqlite")), enable_verification=False,
                       enable_audit=True)
    await plane.init()
    await plane.commit_with_agm_async("pref:editor", "uses vim", ttl=3600.0)
    original = await plane.backend.load("pref:editor")
    # make the first write old: its own TTL would long be over
    plane.backend._conn.execute("UPDATE memories SET created_at = ? WHERE key = ?",
                                (time.time() - 7200.0, "pref:editor"))
    plane.backend._conn.commit()
    await plane.commit_with_agm_async("pref:editor", "uses vim", ttl=3600.0)

    stored = await plane.backend.load("pref:editor")
    assert stored.id == original.id
    assert stored.created_at == pytest.approx(time.time() - 7200.0, abs=30)  # created_at stayed
    assert stored.invalid_at > time.time() + 3000.0                          # invalid_at moved
    assert stored.is_stale() is False
    assert "expired" not in plane._recall_risk_flags(stored)
    assert plane._is_recallable_entry(stored) is True
    assert plane._filter_candidates_as_of({stored.key: stored}, str(time.time())) == {stored.key: stored}
    assert graph_doctor._entry_status(stored, time.time())["active"] is True
    assert VerificationGate()._check_staleness(stored).status != VerificationStatus.STALE


@pytest.mark.asyncio
async def test_forgetting_engine_does_not_treat_a_recommitted_ttl_row_as_stale():
    from bilinc.adaptive.forgetting_engine import ForgettingEngine

    engine = ForgettingEngine()
    text = engine.explain_forgetting(_entry())
    assert "is stale" not in text
