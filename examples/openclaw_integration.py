"""
Bilinc - OpenClaw / Hermes Integration Example

Shows how to integrate Bilinc as a persistent memory layer
for autonomous coding agents.
"""

from bilinc import StatePlane
from bilinc.core.models import MemoryType

# Initialize the state plane
plane = StatePlane(
    backend="memory",  # In-memory for dev, postgresql for prod
    default_budget_tokens=2048,
    verification_min_confidence=0.5,
)

# ─── Scenario: Debug Session Continuity ───────────────────────
print("=" * 60)
print("SCENARIO: Debug Session Continuity (Session 1)")
print("=" * 60)

# Session 1: Developer working on a bug
plane.commit(
    key="current_task",
    value={"repo": "hermes-agent", "file": "tools/mcp_tool.py", "issue": "Memory leak"},
    memory_type=MemoryType.EPISODIC,
    source="user_input",
    session_id="sess_001",
)

plane.commit(
    key="constraint_tabs=2",
    value="Project requires 2-space tabs for Python files",
    memory_type=MemoryType.SYMBOLIC,
    metadata={"enforcement": "strict"},
    session_id="sess_001",
)

plane.commit(
    key="discovery",
    value="Memory leak in mcp_tool.py line 42 - unclosed file handle",
    memory_type=MemoryType.EPISODIC,
    source="code_change",
    session_id="sess_001",
)

# Check stats
stats = plane.get_stats()
print(f"✅ Commits: {stats['total_commits']}")

# ─── Scenario: Session 2 - Continue next day ──────────────────
print()
print("=" * 60)
print("SCENARIO: Continue Next Day (Session 2)")
print("=" * 60)

# New session recalls previous state
result = plane.recall(
    intent="continue debugging memory leak",
    budget_tokens=1024,
)

print(f"📦 Recalled {len(result.memories)} memories")
print(f"💰 Budget: {result.total_tokens_estimated} / {result.budget_requested} tokens")
print(f"⚠️  Stale filtered: {result.stale_count}")
print(f"⚠️  Conflicts filtered: {result.conflict_count}")

for mem in result.memories:
    print(f"  - {mem.memory_type.value:12s}: {mem.key} → {mem.value}")

# ─── Scenario: Constraint Drift Prevention ────────────────────
print()
print("=" * 60)
print("SCENARIO: Constraint Drift (Symbolic vs New Info)")
print("=" * 60)

# Someone says "use 4-space tabs" - this conflicts with existing constraint
result = plane.commit(
    key="constraint_tabs",
    value="Project requires 4-space tabs",
    memory_type=MemoryType.SYMBOLIC,
    metadata={"enforcement": "strict"},
)
print(f"Result: {result['status']}")
print(f"  → Audit: {result.get('agm', 'N/A')}")

# ─── Scenario: Explainable Forgetting ─────────────────────────
print()
print("=" * 60)
print("SCENARIO: Explainable Forgetting")
print("=" * 60)

plane.forget("current_task", reason="task_completed")
explanation = plane.explain_forgetting("current_task")
print(f"Explanation: {explanation}")

# ─── Scenario: Drift Report ──────────────────────────────────
print()
print("=" * 60)
print("SCENARIO: System Health")
print("=" * 60)

drift = plane.get_drift_report()
print(f"📊 Total entries: {drift['total_entries']}")
print(f"📊 Stale: {drift['stale_count']}")
print(f"📊 Unverified: {drift['unverified_count']}")
print(f"📊 Conflict groups: {len(drift['conflict_groups'])}")
print(f"📊 Drift score: {drift['drift_score']:.3f}")
print(f"📊 Quality score: {drift['quality_score']:.3f}")

print("\n✅ Bilinc operational")
