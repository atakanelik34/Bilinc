import asyncio

from bilinc.core.models import MemoryEntry
from bilinc.storage.sqlite import SQLiteBackend


async def _backend(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "b.db"))
    await backend.init()
    return backend


async def _seed(backend):
    rows = [
        ("a", "agent", {}, 10.0),
        ("b", "sample-chat-transcript", {}, 20.0),
        ("c", "", {}, 30.0),
        ("d", "agent", {}, 40.0),
        ("e", "", {"source": "sample-chat-transcript"}, 50.0),
        ("f", "agent", {}, 60.0),
    ]
    for key, source, meta, stamp in rows:
        await backend.restore(
            MemoryEntry(key=key, value=key, source=source, metadata=meta, created_at=stamp, updated_at=stamp)
        )
    backend._get_conn().execute("UPDATE memories SET source = NULL WHERE key = 'f'")
    backend._get_conn().commit()


def test_exclude_sources_newest_and_count(tmp_path):
    async def scenario():
        backend = await _backend(tmp_path)
        await _seed(backend)
        page = await backend.list_page(order="newest", exclude_sources=["sample-chat-transcript"], limit=10)
        # b (column source) and e (metadata source only) are excluded; NULL-source f is kept.
        assert [e.key for e in page] == ["f", "d", "c", "a"]
        assert await backend.count_filtered(exclude_sources=["sample-chat-transcript"]) == 4
        window = await backend.list_page(order="newest", updated_after=15.0, updated_before=40.0, limit=10)
        assert [e.key for e in window] == ["c", "b"]

    asyncio.run(scenario())


def test_empty_or_none_exclude_is_no_filter(tmp_path):
    async def scenario():
        backend = await _backend(tmp_path)
        await _seed(backend)
        for value in ([], None):
            assert len(await backend.list_page(exclude_sources=value, limit=10)) == 6
            assert await backend.count_filtered(exclude_sources=value) == 6

    asyncio.run(scenario())


def test_updated_at_index_exists(tmp_path):
    async def scenario():
        backend = await _backend(tmp_path)
        names = {r[1] for r in backend._get_conn().execute("PRAGMA index_list('memories')").fetchall()}
        assert "idx_updated_at" in names

    asyncio.run(scenario())


def test_iso_text_updated_at_is_not_in_numeric_window_known_gap(tmp_path):
    """Pinned gap: a text updated_at never satisfies the numeric window filter."""

    async def scenario():
        backend = await _backend(tmp_path)
        await backend.restore(MemoryEntry(key="t", value="t", created_at=1.0, updated_at=1.0))
        backend._get_conn().execute(
            "UPDATE memories SET updated_at = '1970-01-01T00:00:30+00:00' WHERE key = 't'"
        )
        backend._get_conn().commit()
        page = await backend.list_page(updated_after=10.0, updated_before=100.0, limit=10)
        assert page == []
        assert await backend.count_filtered(updated_after=10.0, updated_before=100.0) == 0

    asyncio.run(scenario())
