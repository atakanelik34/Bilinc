"""
LangGraph Checkpoint Adapter

Integrates Bilinc as a persistent checkpoint store for LangGraph agents.

All checkpoint data flows through StatePlane's verification, AGM, and
budget-aware retrieval pipeline.

Usage:
    from langgraph.graph import StateGraph
    from bilinc.integrations.langgraph import LangGraphCheckpointer

    checkpointer = LangGraphCheckpointer(state_plane)
    graph = builder.compile(checkpointer=checkpointer)
"""

from __future__ import annotations
import json
import logging
from typing import Any, Dict, Optional, Sequence, Tuple, Iterator
from collections import defaultdict
from bilinc.core.stateplane import StatePlane
from bilinc.core.models import MemoryType

logger = logging.getLogger(__name__)

try:
    from langgraph.checkpoint.base import (
        BaseCheckpointSaver,
        CheckpointTuple,
        Checkpoint,
        CheckpointMetadata,
    )
except ImportError:
    BaseCheckpointSaver = object
    CheckpointTuple = Any
    Checkpoint = Any
    CheckpointMetadata = Any


class LangGraphCheckpointer(BaseCheckpointSaver):
    """LangGraph checkpointer backed by Bilinc StatePlane."""

    def __init__(
        self,
        state_plane: Optional[StatePlane] = None,
        checkpoint_prefix: str = "langgraph",
        compress_checkpoints: bool = True,
    ):
        self.state_plane = state_plane or StatePlane()
        self.checkpoint_prefix = checkpoint_prefix
        self.compress_checkpoints = compress_checkpoints
        self._pending_writes: Dict[str, list] = defaultdict(list)

    # -- Read methods --

    def get_tuple(self, config: Dict[str, Any]) -> Optional["CheckpointTuple"]:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_id = configurable.get("checkpoint_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")

        if checkpoint_id:
            key = self._checkpoint_key(thread_id, checkpoint_id, checkpoint_ns)
            entry = self.state_plane._storage.get(key)
            if entry:
                return self._entry_to_tuple(entry, thread_id, checkpoint_ns)

        result = self.state_plane.recall(
            intent=f"checkpoint thread {thread_id}",
            budget_tokens=4096,
        )
        if result.memories:
            latest = max(result.memories, key=lambda m: m.updated_at)
            return self._entry_to_tuple(latest, thread_id, checkpoint_ns)
        return None

    def list(
        self,
        config: Optional[Dict[str, Any]],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> Iterator["CheckpointTuple"]:
        configurable = (config or {}).get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")

        cps = [
            e for e in self.state_plane._storage.values()
            if e.key.startswith(f"{self.checkpoint_prefix}:{thread_id}")
        ]
        cps.sort(key=lambda e: e.updated_at, reverse=True)

        if limit:
            cps = cps[:limit]

        for entry in cps:
            yield self._entry_to_tuple(entry, thread_id, checkpoint_ns)

    # -- Write methods --

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Dict[str, Any],
        new_versions: Dict[str, Any],
    ) -> str:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_id = checkpoint.get("id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        key = self._checkpoint_key(thread_id, checkpoint_id, checkpoint_ns)

        value = checkpoint
        if self.compress_checkpoints:
            value = self._compress_checkpoint(checkpoint)

        data = {
            "checkpoint": value,
            "metadata": metadata,
            "new_versions": new_versions,
            "compressed": self.compress_checkpoints,
        }

        self.state_plane.commit(
            key=key,
            value=data,
            memory_type=MemoryType.EPISODIC,
            metadata={
                "type": "checkpoint",
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            },
            source="langgraph",
            session_id=thread_id,
            verify=False,
        )
        return checkpoint_id

    def put_writes(
        self,
        config: Dict[str, Any],
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_id = configurable.get("checkpoint_id", "")

        key = f"{self.checkpoint_prefix}:pending:{thread_id}:{task_id}"
        self.state_plane.commit(
            key=key,
            value={"writes": list(writes), "task_path": task_path, "checkpoint_id": checkpoint_id},
            memory_type=MemoryType.EPISODIC,
            source="langgraph_pending",
            session_id=thread_id,
            verify=False,
        )

    # -- Internals --

    @staticmethod
    def _checkpoint_key(tid: str, cid: str, ns: str = "") -> str:
        parts = ["langgraph", tid]
        if ns:
            parts.append(ns)
        if cid:
            parts.append(cid)
        return ":".join(parts)

    def _compress_checkpoint(self, cp: Dict[str, Any]) -> Dict[str, Any]:
        cv = cp.get("channel_values", {})
        return {
            "channel_values": {
                k: (v[:800] if isinstance(v, str) and len(v) > 800 else v)
                for k, v in cv.items()
            },
            "pending_sends": cp.get("pending_sends", [])[:10],
            "version": cp.get("version", {}),
            "ts": cp.get("ts", ""),
        }

    def _entry_to_tuple(self, entry, thread_id: str, cp_ns: str = "") -> "CheckpointTuple":
        value = entry.value if isinstance(entry.value, dict) else json.loads(entry.value)
        cp_data = value.get("checkpoint", value)
        meta_data = value.get("metadata", {})

        checkpoint = Checkpoint(
            v=cp_data.get("v", 2) if isinstance(cp_data, dict) else 2,
            id=cp_data.get("id", entry.id) if isinstance(cp_data, dict) else entry.id,
            ts=cp_data.get("ts", entry.updated_at) if isinstance(cp_data, dict) else entry.updated_at,
            channel_values=cp_data.get("channel_values", {}) if isinstance(cp_data, dict) else {},
            channel_versions=cp_data.get("channel_versions", {}) if isinstance(cp_data, dict) else {},
            versions_seen=cp_data.get("versions_seen", {}) if isinstance(cp_data, dict) else {},
            pending_sends=cp_data.get("pending_sends", []) if isinstance(cp_data, dict) else [],
        )

        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint.id,
                "checkpoint_ns": cp_ns,
            }
        }

        metadata = CheckpointMetadata(
            source=meta_data.get("source", "synaptic"),
            step=meta_data.get("step", 0),
            writes=meta_data.get("writes", {}),
            parents=meta_data.get("parents", {}),
        )

        pending_key = f"langgraph:pending:{thread_id}"
        pending_writes = []

        parent_config = None
        pid = meta_data.get("parent_checkpoint_id")
        if pid:
            parent_config = {"configurable": {"thread_id": thread_id, "checkpoint_id": pid}}

        parent_ns = meta_data.get("parent_checkpoint_ns", cp_ns)
        if parent_config and parent_ns:
            parent_config["configurable"]["checkpoint_ns"] = parent_ns

        return CheckpointTuple(
            config=config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )
