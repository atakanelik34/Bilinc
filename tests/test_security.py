"""
Tests for Security Layer and Validation
"""
import json
import pytest

from bilinc.security.validator import InputValidator
from bilinc.security.resource_limits import ResourceLimits
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
        # Working memory limit is 16 per ResourceLimits.
        # Create StatePlane with 16 slots to test the limit.
        plane = StatePlane(backend=None, enable_verification=False, enable_audit=False,
                          max_working_slots=16)
        
        for i in range(16):
            plane.commit_sync(
                key=f"slot_{i}",
                value=f"data_{i}",
                memory_type=MemoryType.WORKING,
            )
    
        assert plane.working_memory.count == 16
    
        # Next one should fail with resource limit error
        with pytest.raises(ValueError, match="full|limit"):
            plane.commit_sync(
                key="overflow",
                value="should_be_rejected",
                memory_type=MemoryType.WORKING,
            )
