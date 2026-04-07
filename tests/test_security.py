"""
Tests for Security Layer and Validation
"""
import json
import pytest

from bilinc.security.validator import InputValidator
from bilinc.security.limits import ResourceLimits
from bilinc import StatePlane
from bilinc.core.models import MemoryType


class TestInputValidation:
    def test_valid_key(self):
        assert InputValidator.validate_key("test_key") == "test_key"
        assert InputValidator.validate_key("a:namespace:b.c") == "a:namespace:b.c"

    def test_empty_key_rejected(self):
        with pytest.raises(ValueError):
            InputValidator.validate_key("")

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError):
            InputValidator.validate_key("../../etc/passwd")
        with pytest.raises(ValueError):
            InputValidator.validate_key("key/with/slashes")

    def test_value_size_limit(self):
        # Valid value
        assert InputValidator.validate_value("hello") == "hello"
        # Large value
        big = "x" * (1024 * 1024 + 100)
        with pytest.raises(ValueError):
            InputValidator.validate_value(big)

    def test_sanitize_kg(self):
        dirty = "<script>alert('xss')</script>Hello"
        clean = InputValidator.sanitize_for_kg(dirty)
        assert "<script>" not in clean
        assert "alert" in clean


class TestResourceLimits:
    def test_working_memory_limit(self):
        plane = StatePlane(backend=None, enable_verification=False, enable_audit=False)
        limit = ResourceLimits.LIMITS["max_entries"][MemoryType.WORKING]
        
        # Fill up to limit - 1
        for i in range(limit - 1):
            plane.commit_sync(
                key=f"temp_{i}",
                value="val",
                memory_type=MemoryType.WORKING
            )

        assert plane.working_memory.count == limit - 1

        # Next one should succeed (limit - 1 < limit)
        plane.commit_sync(
            key=f"temp_last",
            value="val",
            memory_type=MemoryType.WORKING
        )
        assert plane.working_memory.count == limit

        # Next one should fail
        with pytest.raises(ValueError, match="full"):
            plane.commit_sync(
                key="overflow",
                value="val",
                memory_type=MemoryType.WORKING
            )
