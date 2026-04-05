"""In-memory storage backend."""
from __future__ import annotations
import asyncio
from typing import Dict, List, Optional
from synaptic_state.core.models import MemoryEntry
from synaptic_state.storage.backend import StorageBackend
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
