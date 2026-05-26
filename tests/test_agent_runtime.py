import json

import pytest

from bilinc.core import MemoryType, StatePlane
from bilinc.storage.memory import MemoryBackend
from bilinc.integrations.agent_runtime import BilincAgentRuntime, ToolEvent, RuntimeModelInput


async def _runtime(agent_id="agentA"):
    backend = MemoryBackend()
    await backend.init()
    plane = StatePlane(backend=backend)
    await plane.init()
    runtime = BilincAgentRuntime.from_state_plane(plane, agent_id=agent_id)
    return runtime, plane


@pytest.mark.asyncio
async def test_before_model_call_injects_memory_context_without_tool_names():
    runtime, plane = await _runtime()
    await plane.commit(
        "release:policy",
        "Release summaries must be terse and evidence-backed.",
        memory_type=MemoryType.SEMANTIC,
        importance=0.9,
    )
    original_messages = [{"role": "user", "content": "How should I write the release summary?"}]

    prepared = await runtime.before_model_call(
        session_id="thread-1",
        messages=original_messages,
        user_input="How should I write the release summary?",
        budget_tokens=800,
    )

    assert isinstance(prepared, RuntimeModelInput)
    assert prepared.messages is not original_messages
    assert prepared.messages[0]["role"] == "system"
    assert "Bilinc Context Packet" in prepared.messages[0]["content"]
    assert "release:policy" in prepared.context.selected_memory_keys
    assert prepared.original_messages == original_messages
    assert "mcp_bilinc" not in prepared.messages[0]["content"]
    assert "recall_smart" not in prepared.messages[0]["content"]


@pytest.mark.asyncio
async def test_before_model_call_can_inject_into_framework_state_dict():
    runtime, plane = await _runtime()
    await plane.commit("state:fact", "State adapters receive Bilinc context.", MemoryType.SEMANTIC, importance=0.9)
    state = {"messages": [{"role": "user", "content": "What do state adapters receive?"}], "other": 1}

    prepared = await runtime.before_model_call(
        session_id="thread-2",
        state=state,
        user_input="What do state adapters receive?",
        budget_tokens=700,
    )

    assert prepared.state is not state
    assert prepared.state["other"] == 1
    assert prepared.state["messages"][0]["role"] == "system"
    assert "State adapters receive Bilinc context" in prepared.state["messages"][0]["content"]
    assert state["messages"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_after_model_call_writes_salience_approved_memory():
    runtime, plane = await _runtime(agent_id="RuntimeAgent")

    result = await runtime.after_model_call(
        session_id="thread-3",
        user_input="Remember that I prefer terse runtime adapter reports.",
        assistant_output="Noted.",
    )

    assert result.salience.should_store is True
    assert result.frame.written_keys
    persisted = await plane.recall(result.frame.written_keys[0])
    assert persisted
    assert persisted[0].memory_type is MemoryType.SEMANTIC
    assert result.frame.metadata["agent_id"] == "RuntimeAgent"


@pytest.mark.asyncio
async def test_tool_events_are_observed_as_redacted_episodic_evidence():
    runtime, plane = await _runtime()

    event = await runtime.observe_tool_event(
        session_id="thread-4",
        name="search_docs",
        input={"query": "pricing", "api_token": "should-not-leak"},
        output={"result": "Decision evidence found"},
        status="success",
    )
    result = await runtime.after_model_call(
        session_id="thread-4",
        user_input="Decision: keep the runtime adapter framework agnostic.",
        assistant_output="Agreed.",
    )

    assert isinstance(event, ToolEvent)
    assert result.tool_events[0].name == "search_docs"
    assert result.tool_events[0].input["api_token"] == "[REDACTED]"
    recalled = await plane.recall(result.tool_evidence_keys[0])
    assert recalled
    assert recalled[0].memory_type is MemoryType.EPISODIC
    dumped = json.dumps(recalled[0].value)
    assert "should-not-leak" not in dumped
    assert recalled[0].metadata["runtime_event"] == "tool_event_evidence"


@pytest.mark.asyncio
async def test_low_salience_turn_does_not_write_memory():
    runtime, _plane = await _runtime()

    result = await runtime.after_model_call(
        session_id="thread-5",
        user_input="thanks haha",
        assistant_output="ok",
    )

    assert result.salience.should_store is False
    assert result.frame.written_keys == []


@pytest.mark.asyncio
async def test_wrap_agent_runs_before_and_after_hooks_for_async_callable():
    runtime, plane = await _runtime()
    await plane.commit("wrap:fact", "Wrapped agents receive automatic context.", MemoryType.SEMANTIC, importance=0.9)

    async def fake_agent(messages):
        assert messages[0]["role"] == "system"
        assert "Wrapped agents receive automatic context" in messages[0]["content"]
        return "Remembered: prefer automatic Bilinc adapters."

    wrapped = runtime.wrap_agent(fake_agent)
    output = await wrapped(
        session_id="thread-6",
        user_input="Remember that I prefer automatic adapters without exposed tool names.",
        messages=[{"role": "user", "content": "Remember that I prefer automatic adapters without exposed tool names."}],
    )

    assert output == "Remembered: prefer automatic Bilinc adapters."
    frame = runtime.workspace.current_frame("thread-6")
    assert frame.retrieved_keys == ["wrap:fact"]
    assert frame.written_keys


@pytest.mark.asyncio
async def test_runtime_exported_from_integrations_package():
    from bilinc.integrations import BilincAgentRuntime as ExportedRuntime

    assert ExportedRuntime is BilincAgentRuntime
