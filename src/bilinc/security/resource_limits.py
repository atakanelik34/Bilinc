"""
Resource Limits for Bilinc

Defines maximums for memory types, storage size, and graph complexity.
"""

from bilinc.core.models import MemoryType


class ResourceLimits:
    """Static helper class for resource limit enforcement."""

    # Default Limits (class attribute)
    LIMITS = {
        "max_entries": {
            MemoryType.EPISODIC: 50_000,
            MemoryType.PROCEDURAL: 10_000,
            MemoryType.SEMANTIC: 25_000,
            MemoryType.WORKING: 16,
            MemoryType.SPATIAL: 5_000,
        },
        "max_kg_nodes": 100_000,
        "max_kg_edges": 500_000,
        "max_entrenchment_keys": 50_000,
        "max_audit_log_size": 1_000_000,
    }

    @classmethod
    def get_max_entries(cls, memory_type: MemoryType) -> int:
        return cls.LIMITS["max_entries"].get(memory_type, 10_000)

    @classmethod
    def check_entry_capacity(cls, memory_type: MemoryType, current_count: int) -> bool:
        """Returns True if adding another entry would NOT exceed limits."""
        limit = cls.get_max_entries(memory_type)
        return current_count < limit

    @classmethod
    def check_kg_capacity(cls, current_nodes: int, current_edges: int, new_nodes: int = 0, new_edges: int = 0) -> bool:
        """Returns True if adding new nodes/edges is within limits."""
        return (
            (current_nodes + new_nodes) <= cls.LIMITS["max_kg_nodes"] and
            (current_edges + new_edges) <= cls.LIMITS["max_kg_edges"]
        )


# Module-level alias for backward compatibility
LIMITS = ResourceLimits.LIMITS
