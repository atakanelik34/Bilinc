from bilinc.core import SalienceEngine as LazySalienceEngine
from bilinc.core.models import MemoryType
from bilinc.core.salience import MemoryWriteProposal, SalienceDecision, SalienceEngine


def test_salience_engine_is_available_from_core_lazy_imports():
    assert LazySalienceEngine is SalienceEngine


def test_casual_chatter_is_not_persisted_by_default():
    decision = SalienceEngine().evaluate_turn(user_input="thanks haha", assistant_output="No problem")

    assert decision.should_store is False
    assert decision.proposals == []
    assert decision.reason == "casual_chatter"
    assert 0.0 <= decision.confidence <= 1.0
    assert 0.0 <= decision.importance <= 1.0


def test_explicit_preference_becomes_semantic_candidate_with_deterministic_key():
    engine = SalienceEngine(agent_id="agentA")
    kwargs = {
        "session_id": "thread-1",
        "user_input": "Remember that I prefer concise Turkish replies for investor DMs.",
        "assistant_output": "Noted.",
    }

    first = engine.evaluate_turn(**kwargs)
    second = engine.evaluate_turn(**kwargs)

    assert first.should_store is True
    assert first.primary_proposal is not None
    assert first.primary_proposal.memory_type is MemoryType.SEMANTIC
    assert first.primary_proposal.action == "commit"
    assert first.primary_proposal.key == second.primary_proposal.key
    assert first.primary_proposal.key.startswith("agentA:preference:")
    assert "concise Turkish replies" in first.primary_proposal.value
    assert 0.0 <= first.primary_proposal.importance <= 1.0


def test_workflow_language_creates_procedural_candidate():
    decision = SalienceEngine().evaluate_turn(
        user_input="When deploying Bilinc, always run tests, build, then verify origin and remote SHAs.",
        assistant_output="Understood.",
        session_id="deploy-thread",
    )

    proposal = decision.primary_proposal
    assert decision.should_store is True
    assert proposal is not None
    assert proposal.memory_type is MemoryType.PROCEDURAL
    assert proposal.key.startswith("procedure:")
    assert proposal.importance >= 0.7
    assert proposal.revision_strategy == "verification"


def test_task_decision_produces_episodic_and_semantic_candidates():
    decision = SalienceEngine().evaluate_turn(
        user_input="Decision: Sprint 2 will implement deterministic salience before workspace lifecycle.",
        assistant_output="Agreed, salience first.",
        session_id="bilinc-sprint-2",
    )

    types = [proposal.memory_type for proposal in decision.proposals]
    assert types == [MemoryType.EPISODIC, MemoryType.SEMANTIC]
    assert decision.proposals[0].key.startswith("bilinc-sprint-2:decision:")
    assert decision.proposals[1].key.startswith("decision:")
    assert all(proposal.action == "commit" for proposal in decision.proposals)


def test_temporary_state_becomes_working_memory_with_ttl():
    decision = SalienceEngine().evaluate_turn(
        user_input="For now, use /tmp/bilinc-probe.db during this debugging session only.",
        session_id="tmp-debug",
    )

    proposal = decision.primary_proposal
    assert decision.should_store is True
    assert proposal is not None
    assert proposal.memory_type is MemoryType.WORKING
    assert proposal.ttl is not None
    assert 0 < proposal.ttl <= 24 * 60 * 60
    assert proposal.key.startswith("tmp-debug:working:")


def test_sensitive_values_are_not_persisted_by_default_and_raise_warning():
    fake_bearer = "bearer " + "abcdefghijklmnopqrstuvwxyz" + "123456"
    decision = SalienceEngine().evaluate_turn(
        user_input=f"Remember my password is hunter2 and {fake_bearer}",
        session_id="security-thread",
    )

    assert decision.should_store is False
    assert decision.proposals == []
    assert any(warning["type"] == "sensitive_value" for warning in decision.warnings)
    assert "hunter2" not in decision.to_dict()["prompt_safe_summary"]
    assert "abcdefghijklmnopqrstuvwxyz" not in str(decision.to_dict())


def test_confidence_and_importance_are_bounded_for_large_inputs():
    huge = "Decision: " + ("important " * 10_000)

    decision = SalienceEngine().evaluate_turn(user_input=huge, session_id="huge")

    assert 0.0 <= decision.confidence <= 1.0
    assert 0.0 <= decision.importance <= 1.0
    assert all(0.0 <= proposal.importance <= 1.0 for proposal in decision.proposals)
    assert all(0.0 <= proposal.confidence <= 1.0 for proposal in decision.proposals)


def test_sensitive_metadata_is_redacted_recursively():
    decision = SalienceEngine().evaluate_turn(
        user_input="For now keep this only during this session.",
        session_id="redact",
        metadata={"nested": {"password": "hunter2", "safe": "ok"}},
    )

    dumped = str(decision.to_dict())
    assert "hunter2" not in dumped
    assert "[REDACTED]" in dumped


def test_memory_write_proposal_serializes_memory_type_values():
    proposal = MemoryWriteProposal(
        key="test:key",
        value="value",
        memory_type=MemoryType.SEMANTIC,
        importance=0.5,
        confidence=0.6,
    )

    assert proposal.to_dict()["memory_type"] == "semantic"


def test_salience_decision_primary_proposal_returns_first_candidate():
    proposal = MemoryWriteProposal("k", "v", MemoryType.EPISODIC, 0.4, 0.5)
    decision = SalienceDecision(True, [proposal], "reason", importance=0.4, confidence=0.5)

    assert decision.primary_proposal is proposal
