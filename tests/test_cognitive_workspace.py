import pytest

from bilinc.core import CognitiveWorkspace as LazyCognitiveWorkspace
from bilinc.core import ContextBundle, MemoryType, StatePlane
from bilinc.core.cognitive_workspace import CognitiveWorkspace, TurnFrame
from bilinc.storage.memory import MemoryBackend
from bilinc.storage.sqlite import SQLiteBackend


@pytest.mark.asyncio
async def test_workspace_is_available_from_core_lazy_imports():
    assert LazyCognitiveWorkspace is CognitiveWorkspace


async def _memory_workspace(agent_id="agentA"):
    backend = MemoryBackend()
    await backend.init()
    plane = StatePlane(backend=backend)
    await plane.init()
    return CognitiveWorkspace(state_plane=plane, agent_id=agent_id), plane


@pytest.mark.asyncio
async def test_prepare_context_recalls_and_returns_prompt_block_without_tool_names():
    workspace, plane = await _memory_workspace()
    await plane.commit(
        "pricing:decision",
        "Decision: Bilinc Cloud pricing uses Pro and Team tiers.",
        memory_type=MemoryType.SEMANTIC,
        importance=0.9,
    )

    bundle = await workspace.prepare_context(
        session_id="thread-1",
        user_input="What did we decide about pricing?",
        budget_tokens=800,
    )

    assert isinstance(bundle, ContextBundle)
    assert "Bilinc Context Packet" in bundle.prompt_block
    assert "pricing:decision" in bundle.selected_memory_keys
    assert "recall_smart" not in bundle.prompt_block
    assert "mcp_bilinc" not in bundle.prompt_block
    assert workspace.current_frame("thread-1").retrieved_keys == ["pricing:decision"]


@pytest.mark.asyncio
async def test_observe_user_turn_records_current_turn_frame_as_working_memory():
    workspace, plane = await _memory_workspace()

    entry = await workspace.observe_user_turn(
        session_id="thread-2",
        user_input="For now, use the temp pricing assumptions in this session.",
        metadata={"source": "test"},
    )

    assert entry.memory_type is MemoryType.WORKING
    assert entry.key.startswith("thread-2:turn:")
    recalled = await plane.recall(entry.key)
    assert recalled and recalled[0].value["user_input"].startswith("For now")
    frame = workspace.current_frame("thread-2")
    assert frame.observed_user_key == entry.key


@pytest.mark.asyncio
async def test_assimilate_response_writes_only_salience_approved_memories():
    workspace, plane = await _memory_workspace(agent_id="agentA")

    decision = await workspace.assimilate_response(
        session_id="thread-3",
        user_input="Remember that I prefer terse release summaries.",
        assistant_output="Noted.",
    )

    assert decision.should_store is True
    frame = workspace.current_frame("thread-3")
    assert frame.written_keys
    persisted = await plane.recall(frame.written_keys[0])
    assert persisted
    assert persisted[0].memory_type is MemoryType.SEMANTIC

    ignored = await workspace.assimilate_response(
        session_id="thread-3b",
        user_input="thanks haha",
        assistant_output="ok",
    )
    assert ignored.should_store is False
    assert workspace.current_frame("thread-3b").written_keys == []


@pytest.mark.asyncio
async def test_finalize_turn_returns_retrieved_written_keys_and_warnings():
    workspace, plane = await _memory_workspace()
    await plane.commit("stable:fact", "Bilinc is the memory substrate.", MemoryType.SEMANTIC, importance=0.9)

    await workspace.prepare_context("thread-4", "What is Bilinc?", budget_tokens=500)
    await workspace.observe_user_turn("thread-4", "Decision: Workspace MVP should remain SDK only.")
    await workspace.assimilate_response("thread-4", "Decision: Workspace MVP should remain SDK only.", "Agreed.")
    result = await workspace.finalize_turn("thread-4")

    assert result.session_id == "thread-4"
    assert "stable:fact" in result.retrieved_keys
    assert result.observed_user_key is not None
    assert result.written_keys
    assert isinstance(result.warnings, list)
    assert result.to_dict()["context"]["read_only"] is True


@pytest.mark.asyncio
async def test_end_session_calls_consolidation_on_temp_sqlite_backend(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "workspace.db"))
    await backend.init()
    plane = StatePlane(backend=backend)
    await plane.init()
    workspace = CognitiveWorkspace(state_plane=plane, agent_id="agentA")

    await workspace.observe_user_turn("thread-5", "For now, remember this session-only detail.")
    result = await workspace.end_session("thread-5")

    assert result["session_id"] == "thread-5"
    assert result["consolidated_count"] >= 0
    assert "workspace.db" not in str(result)


@pytest.mark.asyncio
async def test_workspace_does_not_hardcode_live_db_paths(tmp_path):
    backend = SQLiteBackend(str(tmp_path / "custom.db"))
    await backend.init()
    plane = StatePlane(backend=backend)
    await plane.init()
    workspace = CognitiveWorkspace(state_plane=plane)

    await workspace.observe_user_turn("thread-6", "For now, keep this only here.")

    assert "/Users/busecimen/bilinc.db" not in str(workspace.current_frame("thread-6").to_dict())


@pytest.mark.asyncio
async def test_finalize_turn_can_run_whole_lifecycle_idempotently():
    workspace, plane = await _memory_workspace()
    await plane.commit("workflow:fact", "Always verify before claiming completion.", MemoryType.PROCEDURAL, importance=0.8)

    result = await workspace.finalize_turn(
        "thread-7",
        user_input="When closing a sprint, always verify, then push with owner-specific tokens.",
        assistant_output="I will follow that workflow.",
        budget_tokens=600,
    )
    second = await workspace.finalize_turn("thread-7")

    assert result.retrieved_keys == second.retrieved_keys
    assert result.observed_user_key == second.observed_user_key
    assert result.written_keys == second.written_keys
    assert len(result.written_keys) == 1
    assert isinstance(result, TurnFrame)
