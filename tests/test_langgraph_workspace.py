import inspect

import pytest

from bilinc.core import MemoryType, StatePlane
from bilinc.integrations.agent_runtime import BilincAgentRuntime
from bilinc.integrations.langgraph_workspace import LangGraphWorkspace, LangGraphTurnResult
from bilinc.storage.memory import MemoryBackend


async def _workspace(agent_id="graph-agent"):
    backend = MemoryBackend()
    await backend.init()
    plane = StatePlane(backend=backend)
    await plane.init()
    runtime = BilincAgentRuntime.from_state_plane(plane, agent_id=agent_id)
    return LangGraphWorkspace(runtime=runtime), plane


@pytest.mark.asyncio
async def test_pre_node_injects_context_into_langgraph_state_without_tool_names():
    workspace, plane = await _workspace()
    await plane.commit(
        "graph:fact",
        "LangGraph nodes should receive Bilinc context before execution.",
        memory_type=MemoryType.SEMANTIC,
        importance=0.9,
    )
    state = {"messages": [{"role": "user", "content": "What should LangGraph nodes receive?"}], "step": 1}

    prepared = await workspace.pre_node(
        state,
        config={"configurable": {"thread_id": "lg-thread-1"}},
        budget_tokens=700,
    )

    assert prepared.state is not state
    assert prepared.state["step"] == 1
    assert prepared.state["messages"][0]["role"] == "system"
    assert "Bilinc Context Packet" in prepared.state["messages"][0]["content"]
    assert "graph:fact" in prepared.context.selected_memory_keys
    assert "mcp_bilinc" not in prepared.state["messages"][0]["content"]
    assert "recall_smart" not in prepared.state["messages"][0]["content"]
    assert state["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_post_node_assimilates_assistant_message_and_writes_memory():
    workspace, plane = await _workspace(agent_id="GraphAgent")

    result = await workspace.post_node(
        state={"messages": [{"role": "assistant", "content": "Noted."}]},
        prior_state={"messages": [{"role": "user", "content": "Remember that I prefer LangGraph context nodes."}]},
        config={"configurable": {"thread_id": "lg-thread-2"}},
    )

    assert isinstance(result, LangGraphTurnResult)
    assert result.runtime_result.salience.should_store is True
    assert result.runtime_result.frame.written_keys
    persisted = await plane.recall(result.runtime_result.frame.written_keys[0])
    assert persisted
    assert persisted[0].memory_type is MemoryType.SEMANTIC
    assert result.session_id == "lg-thread-2"


@pytest.mark.asyncio
async def test_tool_events_are_forwarded_to_runtime_as_evidence():
    workspace, plane = await _workspace()

    result = await workspace.post_node(
        state={
            "messages": [{"role": "assistant", "content": "Agreed."}],
            "bilinc_tool_events": [
                {"name": "search", "input": {"token": "secret-token"}, "output": {"answer": "evidence"}},
            ],
        },
        prior_state={"messages": [{"role": "user", "content": "Decision: keep LangGraph adapter thin."}]},
        config={"configurable": {"thread_id": "lg-thread-3"}},
    )

    assert result.runtime_result.tool_evidence_keys
    recalled = await plane.recall(result.runtime_result.tool_evidence_keys[0])
    assert recalled
    assert recalled[0].metadata["runtime_event"] == "tool_event_evidence"
    assert "secret-token" not in str(recalled[0].value)


@pytest.mark.asyncio
async def test_wrap_node_runs_pre_and_post_hooks_around_async_node():
    workspace, plane = await _workspace()
    await plane.commit("wrap:lg", "Wrapped LangGraph nodes receive automatic Bilinc context.", MemoryType.SEMANTIC, importance=0.9)

    async def node(state, config=None):
        assert state["messages"][0]["role"] == "system"
        assert "Wrapped LangGraph nodes receive automatic Bilinc context" in state["messages"][0]["content"]
        return {"messages": state["messages"] + [{"role": "assistant", "content": "Noted."}]}

    wrapped = workspace.wrap_node(node)
    output = await wrapped(
        {"messages": [{"role": "user", "content": "Remember that I prefer wrapped LangGraph nodes."}]},
        config={"configurable": {"thread_id": "lg-thread-4"}},
    )

    assert output["messages"][-1]["role"] == "assistant"
    frame = workspace.runtime.workspace.current_frame("lg-thread-4")
    assert frame.retrieved_keys == ["wrap:lg"]
    assert frame.written_keys


def test_langgraph_workspace_uses_runtime_not_private_stateplane_storage():
    import bilinc.integrations.langgraph_workspace as langgraph_workspace
    import bilinc.integrations.langgraph as legacy_langgraph

    workspace_source = inspect.getsource(langgraph_workspace)
    legacy_source = inspect.getsource(legacy_langgraph)
    assert "._storage" not in workspace_source
    assert "._storage" not in legacy_source
