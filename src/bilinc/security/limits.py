"""Resource Limits for Bilinc"""
from bilinc.core.models import MemoryType

class ResourceLimits:
    LIMITS = {
        "max_entries": {
            MemoryType.EPISODIC: 50_000,
            MemoryType.SEMANTIC: 25_000,
            MemoryType.WORKING: 8,
        },
    }

    @classmethod
    def check_entry_capacity(cls, memory_type: MemoryType, count: int) -> bool:
        limit = cls.LIMITS["max_entries"].get(memory_type, 10_000)
        return count < limit
