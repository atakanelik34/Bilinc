"""Abstract storage backend interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from bilinc.core.models import MemoryEntry
import asyncio
class StorageBackend(ABC):
    @abstractmethod
    async def init(self) -> None: ...
    @abstractmethod
    async def save(self, entry: MemoryEntry) -> bool: ...
    @abstractmethod
    async def load(self, key: str) -> Optional[MemoryEntry]: ...
    @abstractmethod
    async def delete(self, key: str) -> bool: ...
    @abstractmethod
    async def list_all(self) -> List[MemoryEntry]: ...
