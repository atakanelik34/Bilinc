"""Abstract storage backend interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from bilinc.core.models import MemoryEntry
class StorageBackend(ABC):
    """Abstract base class for all Bilinc storage backends.

    Implementations must provide async CRUD operations for MemoryEntry
    objects along with type-scoped queries and statistics.
    """

    @abstractmethod
    async def init(self) -> None:
        """Initialize the backend (create tables, connection pools, etc.)."""
        ...

    @abstractmethod
    async def save(self, entry: MemoryEntry) -> bool:
        """Persist a MemoryEntry. Returns True on success."""
        ...

    @abstractmethod
    async def load(self, key: str) -> Optional[MemoryEntry]:
        """Load a single entry by key, or None if not found."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete an entry by key. Returns True if it existed."""
        ...

    @abstractmethod
    async def list_all(self) -> List[MemoryEntry]:
        """Return every stored entry."""
        ...

    @abstractmethod
    async def load_by_type(self, memory_type: Any, limit: int = 50) -> List[MemoryEntry]:
        """Return entries of a given memory_type, up to *limit*."""
        ...

    @abstractmethod
    async def stats(self) -> Dict[str, Any]:
        """Return backend statistics as a dict."""
        ...
