"""Integration tests: cross-tool translation, full pipeline."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from bilinc import StatePlane
from bilinc.core.models import MemoryType
from bilinc.integrations.cross_tool import CrossToolTranslator, ToolFormat
from bilinc.adaptive.policy import ContextBudgetPolicy, BudgetState, BudgetAction


class TestCrossTool:
    def test_import_claude_md(self):
        plane = StatePlane(backend=None, enable_verification=False, enable_audit=False)
        translator = CrossToolTranslator(plane)
        
        content = """# CLAUDE.md\n## Rules\n- Use 2-space tabs\n\n## Instructions\nRun tests before commit\n"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(content)
            path = f.name
        
        keys = translator.import_from_tool(path, ToolFormat.CLAUDE_CODE, session_id="test")
        assert len(keys) > 0
        os.unlink(path)
    
    def test_export_to_mcp(self):
        plane = StatePlane(backend=None, enable_verification=False, enable_audit=False)
        plane.commit_sync(key="pref_theme", value="dark", memory_type=MemoryType.WORKING)
        plane.commit_sync(key="rule_tabs", value="2-space tabs", memory_type=MemoryType.WORKING)
        
        translator = CrossToolTranslator(plane)
        output = translator.export_to_tool("", ToolFormat.MCP)
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) >= 2
    
    def test_import_export_roundtrip(self):
        plane = StatePlane(backend=None, enable_verification=False, enable_audit=False)
        translator = CrossToolTranslator(plane)
        
        # Write Claude file
        claude_content = "# CLAUDE.md\n## Rules\nNo trailing whitespace\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write(claude_content)
            path = f.name
        
        keys = translator.import_from_tool(path, ToolFormat.CLAUDE_CODE)
        assert len(keys) > 0
        
        # Verify entries are in working memory
        assert plane.working_memory.count > 0
        
        # Export to MCP
        mcp_output = translator.export_to_tool("", ToolFormat.MCP)
        data = json.loads(mcp_output)
        assert len(data) > 0
        
        os.unlink(path)


class TestRLPolicy:
    def test_select_action(self):
        policy = ContextBudgetPolicy(epsilon=0.0)
        state = BudgetState(
            budget_ratios=[0.3, 0.3, 0.25, 0.15],
            importance_dist=[0.8] * 4,
            confidence_dist=[0.9] * 4,
            staleness_ratios=[0.0] * 4,
        )
        idx, alloc = policy.select_action(state, training=False)
        assert isinstance(alloc, dict)
        assert len(alloc) == 4
        assert abs(sum(alloc.values()) - 1.0) < 0.001
    
    def test_update(self):
        policy = ContextBudgetPolicy()
        state = BudgetState()
        action_idx, _ = policy.select_action(state, training=False)
        policy.update(state, action_idx, 0.8, done=True)
        assert len(policy._recent_rewards) == 1
    
    def test_save_load(self):
        policy = ContextBudgetPolicy()
        state = BudgetState()
        idx, alloc = policy.select_action(state)
        policy.update(state, idx, 0.9, done=True)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            path = f.name
        
        policy.save(path)
        
        policy2 = ContextBudgetPolicy()
        policy2.load(path)
        assert len(policy2._q_table) == len(policy._q_table)
        
        os.unlink(path)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
