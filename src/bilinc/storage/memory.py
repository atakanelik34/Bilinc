"""In-memory storage backend."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from bilinc.core.models import MemoryEntry
from bilinc.storage.backend import StorageBackend


class MemoryBackend(StorageBackend):
    def __init__(self):
        self._store: Dict[str, MemoryEntry] = {}

    async def init(self) -> None:
        pass

    async def save(self, entry: MemoryEntry) -> bool:
        self._store[entry.key] = entry
        return True

    async def load(self, key: str) -> Optional[MemoryEntry]:
        return self._store.get(key)

    async def delete(self, key: str) -> bool:
        return self._store.pop(key, None) is not None

    async def list_all(self) -> List[MemoryEntry]:
        return list(self._store.values())

    async def load_by_type(self, memory_type: Any, limit: int = 50) -> List[MemoryEntry]:
        expected = memory_type.value if hasattr(memory_type, "value") else str(memory_type)
        matches = [
            entry for entry in self._store.values()
            if (entry.memory_type.value if hasattr(entry.memory_type, "value") else str(entry.memory_type)) == expected
        ]
        return matches[:limit]

    async def stats(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for entry in self._store.values():
            memory_type = entry.memory_type.value if hasattr(entry.memory_type, "value") else str(entry.memory_type)
            counts[memory_type] = counts.get(memory_type, 0) + 1
        return {"entries": len(self._store), "by_type": counts}
