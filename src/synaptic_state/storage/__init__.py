"""Storage backends: in-memory, PostgreSQL/pgvector, SQLite."""
from synaptic_state.storage.memory import MemoryBackend
from synaptic_state.storage.postgres import PostgresBackend
__all__ = ["MemoryBackend", "PostgresBackend"]

try:
    from synaptic_state.storage.sqlite import SQLiteBackend
    __all__.append("SQLiteBackend")
except ImportError:
    pass
