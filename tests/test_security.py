"""
Tests for Security Layer and Validation
"""
import json
import pytest

from bilinc.security.validator import InputValidator
from bilinc.security.resource_limits import ResourceLimits
from bilinc import StatePlane
from bilinc.core.audit import AuditTrail, OpType
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


@pytest.mark.asyncio
async def test_audit_trail_handles_stale_multi_instance_root(tmp_path):
    """Separate AuditTrail instances must not fork the SQLite audit chain."""
    db_path = str(tmp_path / "audit.db")

    writer_a = AuditTrail(db_path)
    writer_b = AuditTrail(db_path)
    await writer_a.init()
    await writer_b.init()

    # writer_b initialized before writer_a writes, so its cached _root_hash is stale.
    writer_a.log(OpType.CREATE, "a", after_value={"value": 1})
    writer_b.log(OpType.CREATE, "b", after_value={"value": 2})
    writer_a.log(OpType.UPDATE, "a", before_value={"value": 1}, after_value={"value": 3})

    integrity = writer_a.verify_integrity()
    assert integrity["valid"] is True
    assert integrity["first_error"] is None

    await writer_a.close()
    await writer_b.close()
