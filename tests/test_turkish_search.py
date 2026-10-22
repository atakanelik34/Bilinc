"""Turkish-aware search: the shared fold, the SQLite v2 full-text index and local recall."""

import json
import sqlite3

import pytest

from bilinc.core.models import MemoryEntry, MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.core.text_fold import fold_text, has_turkish_letters, search_terms
from bilinc.core.vector_search import HybridSearch, VectorStore
from bilinc.observability.health import HealthCheck
from bilinc.storage.sqlite import FTS_V2_TABLE, SQLiteBackend


def test_fold_maps_every_turkish_i_and_drops_diacritics():
    assert fold_text("İstanbul") == "istanbul"
    assert fold_text("ISTANBUL") == "istanbul"
    assert fold_text("IŞIK") == fold_text("ışık") == "isik"
    assert fold_text("Girişimci Üçüncü Ğ") == "girisimci ucuncu g"
    assert fold_text("naïve Café") == "naive cafe"
    assert fold_text("Plain ASCII") == "plain ascii"
    assert fold_text(None) == ""


def test_search_terms_keep_turkish_words_whole_and_split_underscores():
    assert search_terms("girişimci İstanbul'da üçüncü") == ["girisimci", "istanbul", "da", "ucuncu"]
    assert search_terms("session_alpha_beta:2026") == ["session", "alpha", "beta", "2026"]
    assert has_turkish_letters("başvuru") and not has_turkish_letters("application")


async def _backend(path) -> SQLiteBackend:
    backend = SQLiteBackend(str(path))
    await backend.init()
    return backend


def _match(backend: SQLiteBackend, term: str) -> set[str]:
    rows = backend._conn.execute(
        f"SELECT m.key FROM {FTS_V2_TABLE} f JOIN memories m ON m.rowid = f.rowid WHERE {FTS_V2_TABLE} MATCH ?",
        (term,),
    ).fetchall()
    return {row[0] for row in rows}


@pytest.mark.asyncio
async def test_v2_index_finds_turkish_words_stored_as_escaped_json(tmp_path):
    backend = await _backend(tmp_path / "tr.sqlite")
    await backend.save(MemoryEntry(key="tr:text", value="Ayşe girişimci, İstanbul'da IŞIK başvurusu"))
    await backend.save(MemoryEntry(key="tr:dict", value={"user": "Yatırımcılarla görüştü", "n": 3}))
    raw = backend._conn.execute("SELECT value FROM memories WHERE key = 'tr:text'").fetchone()[0]
    assert "\\u015f" in raw  # stored escaped, as json.dumps writes it

    assert _match(backend, '"girisimci"') == {"tr:text"}
    assert _match(backend, '"istanbul"') == {"tr:text"}
    assert _match(backend, '"isik"') == {"tr:text"}
    assert _match(backend, '"basvuru"*') == {"tr:text"}
    assert _match(backend, '"yatirimci"*') == {"tr:dict"}
    await backend.close()


@pytest.mark.asyncio
async def test_v2_index_covers_rows_written_without_bilinc(tmp_path):
    """Older code and tools that write the table directly get the same index."""
    backend = await _backend(tmp_path / "direct.sqlite")
    columns = "id, key, memory_type, value, created_at, updated_at"
    backend._conn.execute(
        f"INSERT INTO memories ({columns}) VALUES ('1', 'raw:json', 'semantic', ?, 1, 1)",
        (json.dumps("Çin merkezli ajan hafızası"),),
    )
    backend._conn.execute(
        f"INSERT INTO memories ({columns}) VALUES ('2', 'raw:text', 'semantic', 'not json ışık', 1, 1)"
    )
    backend._conn.execute(f"INSERT INTO memories ({columns}) VALUES ('3', 'raw:null', 'semantic', NULL, 1, 1)")
    backend._conn.commit()

    assert _match(backend, '"cin"') == {"raw:json"}
    assert _match(backend, '"isik"') == {"raw:text"}
    assert _match(backend, '"null"') == {"raw:null"}  # the key is indexed even without a value
    await backend.close()


@pytest.mark.asyncio
async def test_v2_index_follows_value_changes_and_deletes(tmp_path):
    backend = await _backend(tmp_path / "update.sqlite")
    await backend.save(MemoryEntry(key="note", value="eski değer"))
    await backend.save(MemoryEntry(key="note", value="yeni değer"))
    assert _match(backend, '"eski"') == set()
    assert _match(backend, '"yeni"') == {"note"}

    # Decay passes rewrite strength only; the row stays indexed exactly once.
    backend._conn.execute("UPDATE memories SET current_strength = 0.5 WHERE key = 'note'")
    backend._conn.commit()
    assert backend._conn.execute(f"SELECT count(*) FROM {FTS_V2_TABLE}").fetchone()[0] == 1

    await backend.delete("note")
    assert _match(backend, '"yeni"') == set()
    await backend.close()


@pytest.mark.asyncio
async def test_v2_index_is_built_once_for_an_existing_database(tmp_path):
    path = tmp_path / "existing.sqlite"
    backend = await _backend(path)
    await backend.save(MemoryEntry(key="before", value="Dizin lisans puanı"))
    # Simulate a database created before schema v2.
    for name in ("insert", "update", "delete"):
        backend._conn.execute(f"DROP TRIGGER {FTS_V2_TABLE}_{name}")
    backend._conn.execute(f"DROP TABLE {FTS_V2_TABLE}")
    backend._conn.commit()
    await backend.close()

    first, second = SQLiteBackend(str(path)), SQLiteBackend(str(path))
    await first.init()
    await second.init()  # a second process finds the table and does not refill it
    assert _match(first, '"lisans"') == {"before"}
    assert first._conn.execute(f"SELECT count(*) FROM {FTS_V2_TABLE}").fetchone()[0] == 1
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_keyword_search_uses_prefixes_for_turkish_and_stems_for_english(tmp_path):
    backend = await _backend(tmp_path / "keyword.sqlite")
    await backend.save(MemoryEntry(key="tr", value="Burs başvurusu tamamlandı"))
    await backend.save(MemoryEntry(key="en", value="The deployments were running overnight"))
    await backend.save(MemoryEntry(key="agent", value="ajan kayıt defteri"))
    conn = backend._get_conn()
    search = HybridSearch(conn, VectorStore(conn))
    key_by_rowid = {row[0]: row[1] for row in conn.execute("SELECT rowid, key FROM memories")}

    def keys(query: str) -> list[str]:
        return [key_by_rowid[rowid] for rowid, _ in search.keyword_search(query, top_k=5)]

    assert keys("başvuru durumu") == ["tr"]  # suffixed form found through a prefix term
    assert keys("deployment run") == ["en"]  # English inflections through Porter
    assert "agent" not in keys("ai")  # short terms stay exact
    await backend.close()


@pytest.mark.asyncio
async def test_turkish_recall_ranks_the_turkish_memory_first(tmp_path):
    backend = await _backend(tmp_path / "recall.sqlite")
    plane = StatePlane(backend=backend, enable_verification=False, enable_audit=False)
    await plane.init()
    await plane.commit_with_agm_async(
        key="program:contest", value="2026 girişimci yarışması başvurusu gönderildi", importance=0.8
    )
    await plane.commit_with_agm_async(key="infra:laptop", value="Laptop security cleanup removed two agents", importance=0.8)
    await plane.commit_with_agm_async(key="misc", value="Random notes about many things m r", importance=0.8)

    payload = await plane.recall_profiled(query="GİRİŞİMCİ başvuru", profile="balanced", limit=3)

    assert payload["results"][0]["key"] == "program:contest"
    assert payload["adequacy"] == 1.0  # every query term is covered, so no reflection pass is needed
    assert payload["reflections_used"] == 0


def test_health_gauges_refresh_at_most_once_per_interval(monkeypatch):
    check = HealthCheck(state_plane=None)
    calls = []
    monkeypatch.setattr(check, "update_gauges", lambda metrics: calls.append(metrics))
    clock = iter([100.0, 110.0, 131.0])
    monkeypatch.setattr("bilinc.observability.health.time.monotonic", lambda: next(clock))

    check.update_gauge_on_metrics("m1")
    check.update_gauge_on_metrics("m2")  # 10 s later: skipped
    check.update_gauge_on_metrics("m3")  # 31 s after the first: refreshed

    assert calls == ["m1", "m3"]
