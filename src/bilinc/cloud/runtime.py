"""Project-isolated hosted runtime manager for Bilinc Cloud."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Awaitable, Callable
from uuid import UUID

from bilinc.core.audit import OpType
from bilinc.core.models import MemoryType
from bilinc.core.stateplane import StatePlane
from bilinc.storage.sqlite import SQLiteBackend
from bilinc.storage.postgres import PostgresBackend
from bilinc.storage.postgres_tenancy import project_schema

#: Hermes-contract fields that ride along in entry metadata rather than as
#: first-class MemoryEntry columns. Mirrors the local MCP server's behavior so
#: hosted and local entries stay shape-compatible.
_METADATA_PASSTHROUGH = ("source", "session_id", "canonical", "priority", "ttl")


def _serialized_project_mutation(
    method: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    """Serialize durable mutations per project without blocking other tenants."""

    @wraps(method)
    async def wrapped(
        self: ProjectRuntimeManager,
        project_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        lock = await self._project_mutation_lock(project_id)
        async with lock:
            return await method(self, project_id, *args, **kwargs)

    return wrapped


def build_entry_metadata(
    metadata: dict[str, Any] | None,
    **passthrough: Any,
) -> dict[str, Any]:
    """Merge caller metadata with the Hermes provenance fields that are set."""
    merged = dict(metadata) if isinstance(metadata, dict) else {}
    for name in _METADATA_PASSTHROUGH:
        value = passthrough.get(name)
        if value is not None:
            merged[name] = value
    return merged


def entry_version(entry_state: dict[str, Any]) -> str:
    """Return an opaque, content-derived version for one memory entry.

    Callers pass this back as ``expected_version`` to get optimistic
    concurrency. It is deliberately not a timestamp or a counter: it must not
    let a client infer write volume or ordering across a shared project.
    """
    payload = json.dumps(entry_state, sort_keys=True, default=str)
    return f"v1_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"


@lru_cache(maxsize=8)
def _supported_recall_kwargs(plane_type: type) -> frozenset[str]:
    """Return the keyword arguments this StatePlane's ``recall_profiled`` accepts.

    The hosted sidecar and the core runtime are deployed independently, and the
    core has grown optional recall arguments over time. Rather than hard-coupling
    to one signature — which turns a version skew into an opaque 503 — ask the
    plane what it supports and pass only that.
    """
    try:
        return frozenset(inspect.signature(plane_type.recall_profiled).parameters)
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensive
        return frozenset()


def _coerce_memory_types(names: list[str] | None) -> list[MemoryType] | None:
    """Map public memory-type names onto the enum, rejecting unknown names."""
    if not names:
        return None
    try:
        return [MemoryType(str(name)) for name in names]
    except ValueError as exc:
        raise ValueError("invalid_memory_type") from exc


def state_version(plane: StatePlane) -> str | None:
    """Return the audit-trail root hash identifying the project's whole state."""
    if not plane.enable_audit or not plane.audit:
        return None
    return plane.audit.get_root_hash()


#: Snapshot identifiers are used as filenames inside the project directory.
#: Anything outside this alphabet — notably ``/`` and ``..`` — is rejected
#: before touching the filesystem, so a public identifier can never escape the
#: normalized project boundary.
_SNAPSHOT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def new_snapshot_id() -> str:
    """Return a collision-resistant, time-ordered snapshot identifier.

    Snapshots used to be named by their float timestamp, so two snapshots taken
    in the same microsecond would overwrite each other. The millisecond prefix
    keeps filenames roughly ordered for humans; the random suffix makes
    collisions impossible in practice.
    """
    return f"snap_{int(time.time() * 1000):013d}_{secrets.token_hex(8)}"


def normalize_snapshot_id(snapshot_id: Any) -> str:
    """Validate a caller-supplied snapshot identifier before any file access."""
    value = str(snapshot_id or "")
    if not _SNAPSHOT_ID_PATTERN.match(value) or value in {".", ".."}:
        raise ValueError("snapshot_not_found")
    return value


#: Hard ceiling on a value-bearing diff. Past this the caller is asking for a
#: bulk export, which is a different product with different retention rules.
MAX_DIFF_RESPONSE_BYTES = 1_000_000


def _snapshot_entries(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("snapshot", {}).get("entries")
    return dict(entries) if isinstance(entries, dict) else {}


def _diff_record(
    key: str,
    before: Any,
    after: Any,
    include_values: bool,
) -> dict[str, Any]:
    """Describe one changed key, carrying values only when asked."""
    record: dict[str, Any] = {"key": key}
    if not include_values:
        return record
    if before is not None:
        record["before"] = before.get("value") if isinstance(before, dict) else before
    if after is not None:
        record["after"] = after.get("value") if isinstance(after, dict) else after
    return record


#: Value modes shared by history and list: full values, a short preview, or
#: none at all (keys and metadata only).
VALUE_MODES = frozenset({"full", "preview", "none"})
VALUE_PREVIEW_CHARS = 200

#: Same ceiling as a value-bearing diff, for the same reason.
MAX_HISTORY_RESPONSE_BYTES = MAX_DIFF_RESPONSE_BYTES
MAX_LIST_RESPONSE_BYTES = MAX_DIFF_RESPONSE_BYTES


def value_preview(value: Any) -> str:
    """Return a bounded, single-string rendering of a stored value."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= VALUE_PREVIEW_CHARS:
        return text
    return text[:VALUE_PREVIEW_CHARS] + "…"


def _render_value(value: Any, mode: str) -> Any:
    return value if mode == "full" else value_preview(value)


def encode_cursor(key: str) -> str:
    return base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii").rstrip("=")


_CURSOR_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def decode_cursor(cursor: str) -> str:
    """Decode a list cursor; anything malformed is a caller error, not a 500.

    The decoder silently skips characters outside the alphabet, which would
    turn junk into an empty key and restart the listing. Only cursors this
    module could have produced are accepted.
    """
    if not _CURSOR_PATTERN.match(cursor or ""):
        raise ValueError("invalid_cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        key = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid_cursor") from exc
    if not key or encode_cursor(key) != cursor:
        raise ValueError("invalid_cursor")
    return key


def _audit_json(raw: Any) -> Any:
    if raw is None or isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _state_value(state: Any) -> Any:
    return state.get("value") if isinstance(state, dict) else None


def history_records(rows: list[Any], *, values: str) -> list[dict[str, Any]]:
    """Turn newest-first audit rows for one key into public history records.

    Forgetting a memory removes its value from every read path: values recorded
    at or before the newest FORGET are never returned, only the fact that the
    change happened. The runtime writes two FORGET rows per forget (the core's,
    carrying the deleted state, and a value-free one carrying the reason); they
    are reported as one event.
    """
    records: list[dict[str, Any]] = []
    forgotten = False
    previous_was_reasoned_forget = False
    for row in rows:
        op = str(row.op_type)
        metadata = _audit_json(row.metadata) or {}
        if op == OpType.FORGET.value:
            forgotten = True
            if previous_was_reasoned_forget and not metadata.get("reason"):
                previous_was_reasoned_forget = False
                continue
            previous_was_reasoned_forget = bool(metadata.get("reason"))
        else:
            previous_was_reasoned_forget = False

        before = _audit_json(row.before_value)
        after = _audit_json(row.after_value)
        source = None
        if isinstance(after, dict):
            source = after.get("source") or (after.get("metadata") or {}).get("source")

        record: dict[str, Any] = {
            "op": "confirm" if metadata.get("confirmed") else op,
            "at": float(row.timestamp),
            "reason": metadata.get("reason"),
            "source": source or None,
        }
        if metadata.get("rollback"):
            record["rollback_snapshot_id"] = metadata.get("snapshot_id")
        if values != "none":
            if forgotten:
                record["values_redacted"] = True
            elif op != OpType.FORGET.value:
                if before is not None:
                    record["before"] = _render_value(_state_value(before), values)
                if after is not None:
                    record["after"] = _render_value(_state_value(after), values)
        records.append(record)
    return records


@dataclass(frozen=True)
class ProjectSnapshot:
    """Persisted project snapshot metadata.

    Deliberately excludes the snapshot's entries: listing checkpoints must not
    stream a project's entire memory back to the caller.
    """

    id: str
    created_at: float
    total_entries: int
    by_type: dict[str, int]
    root_hash: str | None
    label: str | None = None
    metadata: dict[str, Any] | None = None


class ProjectRuntimeManager:
    """
    Keep each hosted project in its own physical SQLite runtime.

    The control plane owns org/project authorization. This manager deliberately
    accepts only a validated project UUID and maps it to:

    ``<base_dir>/<project_id>/bilinc.db``

    That gives the private-beta runtime a hard filesystem boundary while the
    higher-level Cloud control plane keeps billing and entitlements in Postgres.
    """

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir).expanduser()
        self._planes: dict[str, StatePlane] = {}
        self._mutation_locks: dict[str, asyncio.Lock] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def normalize_project_id(project_id: str) -> str:
        """Validate and normalize a project UUID before using it as a path segment."""
        try:
            return str(UUID(str(project_id)))
        except (ValueError, AttributeError) as exc:
            raise ValueError("invalid_project_id") from exc

    def project_dir(self, project_id: str) -> Path:
        return self.base_dir / self.normalize_project_id(project_id)

    def db_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "bilinc.db"

    def snapshot_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "snapshots"

    async def get_plane(self, project_id: str) -> StatePlane:
        normalized = self.normalize_project_id(project_id)
        existing = self._planes.get(normalized)
        if existing is not None:
            return existing

        async with self._lock:
            existing = self._planes.get(normalized)
            if existing is not None:
                return existing

            db_path = self.db_path(normalized)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            backend_mode = os.getenv("BILINC_STORAGE_BACKEND", "sqlite").lower()
            if backend_mode == "postgres":
                dsn = os.getenv("BILINC_POSTGRES_DSN")
                if not dsn:
                    raise RuntimeError("BILINC_POSTGRES_DSN is required for postgres backend")
                # One schema per project: the same isolation the SQLite runtime
                # gets from one database file per project.
                backend = PostgresBackend(dsn=dsn, schema=project_schema(normalized))
                audit_enabled = True
            else:
                backend = SQLiteBackend(db_path=str(db_path))
                audit_enabled = True
            plane = StatePlane(
                backend=backend,
                enable_verification=True,
                enable_audit=audit_enabled,
            )
            await plane.init()
            plane.init_agm()
            plane.init_knowledge_graph()

            if plane.backend and plane.agm_engine:
                entries = await plane.backend.list_all()
                plane.agm_engine.load_beliefs_from_entries(entries)

            self._planes[normalized] = plane
            return plane

    async def _project_mutation_lock(self, project_id: str) -> asyncio.Lock:
        normalized = self.normalize_project_id(project_id)
        async with self._lock:
            return self._mutation_locks.setdefault(normalized, asyncio.Lock())

    @_serialized_project_mutation
    async def commit(
        self,
        project_id: str,
        *,
        key: str,
        value: Any,
        memory_type: str = MemoryType.SEMANTIC.value,
        importance: float = 1.0,
        metadata: dict[str, Any] | None = None,
        source: str | None = None,
        session_id: str | None = None,
        canonical: bool | None = None,
        priority: float | None = None,
        ttl: float | None = None,
        if_absent: bool = False,
    ) -> dict[str, Any]:
        """Write ``key``, revising it if it already exists.

        With ``if_absent`` the write is create-only: an existing entry is left
        untouched and ``memory_exists`` is raised instead. The check runs inside
        the per-project mutation lock, so it cannot race another writer. It uses
        the same existence test as ``revise``, so exactly one of the two succeeds.
        """
        plane = await self.get_plane(project_id)
        if if_absent:
            if not plane.backend:
                raise ValueError("invalid_request")
            if await plane.backend.load(key) is not None:
                raise ValueError("memory_exists")
        result = await plane.commit_with_agm_async(
            key=key,
            value=value,
            memory_type=memory_type,
            importance=importance,
            metadata=build_entry_metadata(
                metadata,
                source=source,
                session_id=session_id,
                canonical=canonical,
                priority=priority,
                ttl=ttl,
            ),
            source=source or "bilinc_cloud",
            session_id=session_id or "",
            ttl=ttl,
        )
        success = bool(getattr(result, "success", False))
        return {
            "success": success,
            "operation": getattr(getattr(result, "operation", None), "value", None),
            "affected_keys": list(getattr(result, "affected_keys", []) or []),
            "removed_keys": list(getattr(result, "removed_keys", []) or []),
            "entry_version": await self._entry_version(plane, key) if success else None,
            "state_version": state_version(plane),
        }

    @staticmethod
    async def _attach_provenance(plane: StatePlane, results: Any) -> None:
        """Add ``entry_version``, ``source`` and timestamps to each recalled entry.

        The version is what ``revise`` and ``forget`` accept as
        ``expected_version``, so a caller can act on exactly what it read.
        Only public provenance is added, never internal scoring state.
        """
        if not plane.backend or not isinstance(results, list):
            return
        for item in results:
            if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                continue
            entry = await plane.backend.load(item["key"])
            if entry is None:
                continue
            state = entry.to_dict()
            item["entry_version"] = entry_version(state)
            item["source"] = state.get("source") or (state.get("metadata") or {}).get("source")
            item["created_at"] = state.get("created_at")
            item["updated_at"] = state.get("updated_at")

    @staticmethod
    async def _entry_version(plane: StatePlane, key: str) -> str | None:
        """Return the opaque version of the entry currently stored under ``key``."""
        if not plane.backend:
            return None
        entry = await plane.backend.load(key)
        return entry_version(entry.to_dict()) if entry else None

    async def recall(
        self,
        project_id: str,
        *,
        query: str,
        profile: str,
        limit: int = 10,
        memory_types: list[str] | None = None,
        explain: bool = False,
        query_timestamp: str | None = None,
    ) -> dict[str, Any]:
        plane = await self.get_plane(project_id)

        # Validate before dispatching, so an unknown memory type is rejected
        # even on a runtime that could not have filtered by it anyway.
        coerced_types = _coerce_memory_types(memory_types)
        supported = _supported_recall_kwargs(type(plane))

        kwargs: dict[str, Any] = {"query": query, "profile": profile, "limit": limit}
        if coerced_types is not None and "memory_types" in supported:
            kwargs["memory_types"] = coerced_types
        if explain and "explain" in supported:
            kwargs["explain"] = True
        if query_timestamp is not None and "query_timestamp" in supported:
            kwargs["query_timestamp"] = query_timestamp

        payload = await plane.recall_profiled(**kwargs)
        payload["state_version"] = state_version(plane)
        await self._attach_provenance(plane, payload.get("results"))

        # Never let a caller believe it received evidence it did not get.
        if explain and "explain" not in supported:
            payload["explain_supported"] = False
        if query_timestamp is not None and "query_timestamp" not in supported:
            payload["query_timestamp_supported"] = False
        return payload

    async def history(
        self,
        project_id: str,
        *,
        key: str,
        limit: int = 20,
        values: str = "full",
    ) -> dict[str, Any]:
        """Return one key's recorded changes, newest first. Read-only."""
        if values not in VALUE_MODES:
            raise ValueError("invalid_request")
        plane = await self.get_plane(project_id)
        if not plane.enable_audit or not plane.audit:
            raise ValueError("invalid_request")

        bound = max(1, int(limit))
        # Paired FORGET rows collapse into one event, so a page of raw rows can
        # hold fewer events than asked for. Widen the fetch until one event
        # past the page is visible, or the key's history is exhausted.
        fetch = bound + 2
        while True:
            rows = plane.audit.get_history(key, limit=fetch)
            records = history_records(rows, values=values)
            if len(records) > bound or len(rows) < fetch:
                break
            fetch *= 2
        exists = plane.backend is not None and await plane.backend.load(key) is not None
        result = {
            "key": key,
            "exists": exists,
            "entries": records[:bound],
            "truncated": len(records) > bound,
            "values": values,
        }
        # One entry is always returned whole, so a caller can always page down
        # to a single change instead of losing it to the bound.
        if len(result["entries"]) > 1 and len(json.dumps(result, default=str)) > MAX_HISTORY_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        return result

    async def list_memories(
        self,
        project_id: str,
        *,
        prefix: str | None = None,
        memory_type: str | None = None,
        updated_after: float | None = None,
        updated_before: float | None = None,
        cursor: str | None = None,
        limit: int = 50,
        values: str = "preview",
    ) -> dict[str, Any]:
        """Return one key-ordered page of stored memories. Read-only.

        Paging is by key, so a cursor stays valid while other writes land.
        ``total`` counts every entry matching the filters, not just this page.
        """
        if values not in VALUE_MODES:
            raise ValueError("invalid_request")
        if memory_type is not None:
            _coerce_memory_types([memory_type])
        plane = await self.get_plane(project_id)
        backend = plane.backend
        if backend is None or not hasattr(backend, "list_page"):
            raise ValueError("invalid_request")

        after_key = decode_cursor(cursor) if cursor else None
        bound = max(1, int(limit))
        filters = {
            "prefix": prefix or None,
            "memory_type": memory_type,
            "updated_after": updated_after,
            "updated_before": updated_before,
        }
        page = await backend.list_page(**filters, after_key=after_key, limit=bound + 1)
        has_more = len(page) > bound
        page = page[:bound]

        entries = []
        for entry in page:
            state = entry.to_dict()
            item: dict[str, Any] = {
                "key": entry.key,
                "memory_type": state.get("memory_type"),
                "importance": entry.importance,
                "source": state.get("source") or (state.get("metadata") or {}).get("source") or None,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "entry_version": entry_version(state),
            }
            if values != "none":
                item["value"] = _render_value(entry.value, values)
            entries.append(item)

        result = {
            "entries": entries,
            "next_cursor": encode_cursor(page[-1].key) if has_more and page else None,
            "total": await backend.count_filtered(**filters),
            "values": values,
            "state_version": state_version(plane),
        }
        # One entry is always returned whole: an export that pages down to a
        # single memory gets its full value, however large.
        if (
            values == "full"
            and len(entries) > 1
            and len(json.dumps(result, default=str)) > MAX_LIST_RESPONSE_BYTES
        ):
            raise ValueError("response_too_large")
        return result

    @_serialized_project_mutation
    async def revise(
        self,
        project_id: str,
        *,
        key: str,
        value: Any,
        importance: float = 1.0,
        strategy: str = "entrenchment",
        reason: str | None = None,
        expected_version: str | None = None,
    ) -> dict[str, Any]:
        """Deliberately replace a known memory, preserving AGM conflict handling.

        Unlike ``commit``, this refuses to create the entry: revising something
        that is not there is a caller mistake, not a silent insert. That is what
        makes a revision distinguishable from an accidental overwrite.
        """
        plane = await self.get_plane(project_id)
        if not plane.backend or not plane.agm_engine:
            raise ValueError("invalid_request")

        previous = await plane.backend.load(key)
        if previous is None:
            raise ValueError("memory_not_found")

        previous_state = previous.to_dict()
        self._assert_expected_version(previous_state, expected_version)
        return await self._revise_loaded(
            plane,
            key=key,
            previous_state=previous_state,
            value=value,
            importance=importance,
            strategy=strategy,
            audit_metadata={"reason": reason},
        )

    @_serialized_project_mutation
    async def confirm(
        self,
        project_id: str,
        *,
        key: str,
        expected_version: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Record that a memory is still accurate, without resending its value.

        This is a same-value revision: the value, type and importance stay as
        stored, ``updated_at`` moves to now, and the audit trail gets an UPDATE
        marked ``confirmed`` so history can tell a confirmation from an edit.
        """
        plane = await self.get_plane(project_id)
        if not plane.backend or not plane.agm_engine:
            raise ValueError("invalid_request")

        previous = await plane.backend.load(key)
        if previous is None:
            raise ValueError("memory_not_found")

        previous_state = previous.to_dict()
        self._assert_expected_version(previous_state, expected_version)
        result = await self._revise_loaded(
            plane,
            key=key,
            previous_state=previous_state,
            value=previous.value,
            importance=previous.importance,
            strategy="entrenchment",
            audit_metadata={"reason": reason, "confirmed": True},
        )
        if not result["success"]:
            raise ValueError("invalid_request")
        current = await plane.backend.load(key)
        return {
            "success": True,
            "key": key,
            "confirmed": True,
            "updated_at": current.updated_at if current else None,
            "entry_version": result["entry_version"],
            "state_version": result["state_version"],
        }

    async def _revise_loaded(
        self,
        plane: StatePlane,
        *,
        key: str,
        previous_state: dict[str, Any],
        value: Any,
        importance: float,
        strategy: str,
        audit_metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply a revision to an entry the caller already loaded and version-checked.

        Callers hold the project mutation lock.
        """
        from bilinc.adaptive.agm_engine import ConflictStrategy
        from bilinc.core.models import MemoryEntry

        # The backend is the source of truth. A rollback restores entries in
        # the backend only, so the in-memory belief can still hold a newer,
        # more entrenched value that would make AGM reject this revision.
        plane.agm_engine.belief_state.add_belief(MemoryEntry.from_dict(dict(previous_state)))

        try:
            conflict_strategy = ConflictStrategy(strategy)
        except ValueError as exc:
            raise ValueError("invalid_request") from exc

        entry_data = dict(previous_state)
        entry_data.update(
            {
                "key": key,
                "value": value,
                "importance": importance,
                "updated_at": time.time(),
            }
        )
        entry = MemoryEntry.from_dict(entry_data)
        plane._apply_entry_verification(entry)

        result = plane.agm_engine.revise(entry, strategy=conflict_strategy)
        winning = plane.agm_engine.belief_state.get_belief(key)

        # AGM treats an identical value as a no-op, but an explicit revision can
        # still carry importance or metadata corrections that must persist.
        if result.success and winning and entry.value == winning.value and entry.to_dict() != winning.to_dict():
            plane.agm_engine.belief_state.add_belief(entry)
            if key not in result.affected_keys:
                result.affected_keys.append(key)
            result.new_beliefs[key] = entry
            winning = entry

        if not result.success or winning is None:
            return {
                "success": False,
                "key": key,
                "strategy": conflict_strategy.value,
                "conflicts_resolved": result.conflicts_resolved,
                "affected_keys": list(result.affected_keys or []),
                "removed_keys": list(result.removed_keys or []),
                "entry_version": entry_version(previous_state),
                "state_version": state_version(plane),
            }

        if plane.knowledge_graph:
            plane.knowledge_graph.ingest_memory_entry(winning)

        if not await plane.backend.save(winning):
            raise ValueError("invalid_request")
        await plane._project_claims_for_entry(winning)

        next_state = winning.to_dict()
        if plane.enable_audit and plane.audit and next_state != previous_state:
            plane.audit.log(
                OpType.UPDATE,
                key,
                before_value=previous_state,
                after_value=next_state,
                metadata={
                    "revision_strategy": conflict_strategy.value,
                    "conflicts_resolved": result.conflicts_resolved,
                    # The reason is audit-visible; the value is already in the diff.
                    **audit_metadata,
                    "origin": "bilinc_cloud",
                },
            )

        return {
            "success": True,
            "key": key,
            "strategy": conflict_strategy.value,
            "conflicts_resolved": result.conflicts_resolved,
            "affected_keys": list(result.affected_keys or []),
            "removed_keys": list(result.removed_keys or []),
            "entry_version": entry_version(next_state),
            "state_version": state_version(plane),
        }

    @_serialized_project_mutation
    async def forget(
        self,
        project_id: str,
        *,
        key: str,
        reason: str,
        expected_version: str | None = None,
    ) -> dict[str, Any]:
        """Remove a memory from active recall, keeping an audit-safe receipt.

        The deleted value is never returned. The audit trail keeps the prior
        state under the existing retention policy; this is deliberately *not*
        regulatory erasure, which is a separate admin lifecycle.
        """
        plane = await self.get_plane(project_id)
        if not plane.backend:
            raise ValueError("invalid_request")

        existing = await plane.backend.load(key)
        if existing is None:
            raise ValueError("memory_not_found")

        previous_state = existing.to_dict()
        self._assert_expected_version(previous_state, expected_version)

        removed = await plane.forget(key)
        if plane.enable_audit and plane.audit:
            # A second, value-free entry so the reason is auditable without
            # duplicating the memory payload.
            plane.audit.log(
                OpType.FORGET,
                key,
                metadata={"reason": reason, "origin": "bilinc_cloud", "deleted": bool(removed)},
            )

        return {
            "success": bool(removed),
            "key": key,
            "removed": bool(removed),
            "reason_recorded": True,
            "state_version": state_version(plane),
        }

    @staticmethod
    def _assert_expected_version(entry_state: dict[str, Any], expected: str | None) -> None:
        if expected and entry_version(entry_state) != expected:
            raise ValueError("version_conflict")

    @_serialized_project_mutation
    async def create_snapshot(
        self,
        project_id: str,
        *,
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectSnapshot:
        normalized = self.normalize_project_id(project_id)
        plane = await self.get_plane(normalized)
        snapshot = await plane.snapshot()
        snapshot_id = new_snapshot_id()
        payload = {
            "id": snapshot_id,
            "created_at": snapshot["timestamp"],
            "total_entries": snapshot["total_entries"],
            "by_type": snapshot["by_type"],
            "root_hash": snapshot["root_hash"],
            "label": label,
            "metadata": dict(metadata) if isinstance(metadata, dict) else {},
            "snapshot": snapshot,
        }

        directory = self.snapshot_dir(normalized)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{snapshot_id}.json").write_text(
            json.dumps(payload, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return self._snapshot_from_payload(payload)

    async def list_snapshots(self, project_id: str, *, limit: int = 20) -> list[ProjectSnapshot]:
        directory = self.snapshot_dir(project_id)
        if not directory.exists():
            return []

        snapshots: list[ProjectSnapshot] = []
        for path in directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                snapshots.append(self._snapshot_from_payload(payload))
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
                # A corrupted or half-written checkpoint must not break listing.
                continue

        # Sort on recorded creation time, not filename: identifiers changed from
        # timestamp-derived to random, and both forms must stay listable.
        snapshots.sort(key=lambda snapshot: snapshot.created_at, reverse=True)
        return snapshots[: max(1, int(limit))]

    async def load_snapshot(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        """Load a stored snapshot payload for the given project.

        A snapshot identifier belonging to another project simply does not
        exist under this project's directory, so cross-tenant probing is
        indistinguishable from asking for something that never existed.
        """
        normalized = self.normalize_project_id(project_id)
        path = self.snapshot_dir(normalized) / f"{normalize_snapshot_id(snapshot_id)}.json"
        if not path.exists():
            raise ValueError("snapshot_not_found")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("snapshot_unreadable") from exc
        if not isinstance(payload, dict) or "snapshot" not in payload:
            raise ValueError("snapshot_unreadable")
        return payload

    async def diff(
        self,
        project_id: str,
        *,
        from_snapshot_id: str,
        to_snapshot_id: str | None = None,
        include_values: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Compare a snapshot against another snapshot or against current state.

        Read-only, and values are redacted unless explicitly requested, so an
        operator can decide whether to restore a checkpoint without the diff
        itself becoming a bulk export of the project's memory.
        """
        normalized = self.normalize_project_id(project_id)
        source = await self.load_snapshot(normalized, from_snapshot_id)
        from_entries = _snapshot_entries(source)

        if to_snapshot_id is None:
            plane = await self.get_plane(normalized)
            to_entries = await plane._persistent_state()
            to_root = state_version(plane)
            target_label = "current"
        else:
            target = await self.load_snapshot(normalized, to_snapshot_id)
            to_entries = _snapshot_entries(target)
            to_root = target.get("root_hash")
            target_label = "snapshot"

        from_keys = set(from_entries)
        to_keys = set(to_entries)
        added = sorted(to_keys - from_keys)
        removed = sorted(from_keys - to_keys)
        modified = sorted(
            key for key in from_keys & to_keys if from_entries[key] != to_entries[key]
        )

        bound = max(1, int(limit))
        truncated = any(len(group) > bound for group in (added, removed, modified))

        result = {
            "from_snapshot_id": normalize_snapshot_id(from_snapshot_id),
            "to_snapshot_id": normalize_snapshot_id(to_snapshot_id) if to_snapshot_id else None,
            "target": target_label,
            "from_root_hash": source.get("root_hash"),
            "to_root_hash": to_root,
            "counts": {"added": len(added), "modified": len(modified), "removed": len(removed)},
            "added": [
                _diff_record(key, None, to_entries[key], include_values) for key in added[:bound]
            ],
            "modified": [
                _diff_record(key, from_entries[key], to_entries[key], include_values)
                for key in modified[:bound]
            ],
            "removed": [
                _diff_record(key, from_entries[key], None, include_values) for key in removed[:bound]
            ],
            "values_included": bool(include_values),
            "truncated": truncated,
        }

        if include_values and len(json.dumps(result, default=str)) > MAX_DIFF_RESPONSE_BYTES:
            raise ValueError("response_too_large")
        return result

    async def rollback_preview(
        self,
        project_id: str,
        *,
        snapshot_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Describe what restoring ``snapshot_id`` would do, without doing it.

        The returned ``current_root_hash`` is what the control plane binds its
        confirmation token to, so an execute issued after the project moved on
        can be refused rather than silently destroying newer state.
        """
        normalized = self.normalize_project_id(project_id)
        payload = await self.load_snapshot(normalized, snapshot_id)
        target_state = _snapshot_entries(payload)

        plane = await self.get_plane(normalized)
        current_state = await plane._persistent_state()

        create = sorted(set(target_state) - set(current_state))
        remove = sorted(set(current_state) - set(target_state))
        update = sorted(
            key
            for key in set(target_state) & set(current_state)
            if target_state[key] != current_state[key]
        )
        bound = max(1, int(limit))

        return {
            "snapshot_id": normalize_snapshot_id(snapshot_id),
            "current_root_hash": state_version(plane),
            "target_root_hash": payload.get("root_hash"),
            "counts": {"create": len(create), "update": len(update), "remove": len(remove)},
            # Keys only. A preview must not stream back what is about to change.
            "create_keys": create[:bound],
            "update_keys": update[:bound],
            "remove_keys": remove[:bound],
            "truncated": any(len(group) > bound for group in (create, update, remove)),
            "destructive": True,
        }

    @_serialized_project_mutation
    async def rollback_execute(
        self,
        project_id: str,
        *,
        snapshot_id: str,
        reason: str,
        expected_current_root: str | None,
    ) -> dict[str, Any]:
        """Restore the project to a stored snapshot. Destructive.

        Restores from the snapshot's own recorded entries rather than replaying
        the audit trail to a timestamp: the stored checkpoint is the artifact
        the operator previewed and approved.
        """
        normalized = self.normalize_project_id(project_id)
        payload = await self.load_snapshot(normalized, snapshot_id)
        target_state = _snapshot_entries(payload)

        plane = await self.get_plane(normalized)
        if not plane.backend:
            raise ValueError("invalid_request")

        current_root = state_version(plane)
        if expected_current_root is not None and current_root != expected_current_root:
            raise ValueError("state_changed_since_preview")

        current_state = await plane._persistent_state()
        created: list[str] = []
        updated: list[str] = []
        deleted: list[str] = []

        for key in sorted(set(current_state) - set(target_state)):
            existing = await plane.backend.load(key)
            await plane.backend.delete(key)
            plane.working_memory.remove(key)
            if plane.enable_audit and plane.audit:
                plane.audit.log(
                    OpType.DELETE,
                    key,
                    before_value=existing.to_dict() if existing else current_state[key],
                    metadata={"rollback": True, "snapshot_id": snapshot_id, "reason": reason},
                )
            deleted.append(key)

        for key, target_entry_state in sorted(target_state.items()):
            existing = await plane.backend.load(key)
            if existing and existing.to_dict() == target_entry_state:
                continue

            restored = plane._coerce_audit_state_entry(key, target_entry_state)
            await plane._restore_backend_entry(restored)
            if hasattr(plane.backend, "delete_claims_for_memory_key"):
                await plane.backend.delete_claims_for_memory_key(key)
            if hasattr(plane.backend, "delete_entity_mentions_for_memory_key"):
                await plane.backend.delete_entity_mentions_for_memory_key(key)
            await plane._project_claims_for_entry(restored)
            await plane._project_entities_for_entry(restored)
            plane.working_memory.remove(key)

            if plane.enable_audit and plane.audit:
                plane.audit.log(
                    OpType.UPDATE if existing else OpType.CREATE,
                    key,
                    before_value=existing.to_dict() if existing else None,
                    after_value=target_entry_state,
                    metadata={"rollback": True, "snapshot_id": snapshot_id, "reason": reason},
                )
            (updated if existing else created).append(key)

        if plane.enable_audit and plane.audit:
            plane.audit.log(
                OpType.ROLLBACK,
                "__system",
                metadata={
                    "snapshot_id": snapshot_id,
                    "reason": reason,
                    "origin": "bilinc_cloud",
                    "counts": {
                        "created": len(created),
                        "updated": len(updated),
                        "deleted": len(deleted),
                    },
                },
            )

        # Counts only: a rollback response must never carry restored or
        # deleted values back to the caller.
        return {
            "success": True,
            "snapshot_id": normalize_snapshot_id(snapshot_id),
            "counts": {"created": len(created), "updated": len(updated), "deleted": len(deleted)},
            "previous_root_hash": current_root,
            "state_version": state_version(plane),
            "reason_recorded": True,
        }

    async def close(self) -> None:
        for plane in self._planes.values():
            backend = getattr(plane, "backend", None)
            if backend and hasattr(backend, "close"):
                await backend.close()
        self._planes.clear()
        self._mutation_locks.clear()

    @staticmethod
    def _snapshot_from_payload(payload: dict[str, Any]) -> ProjectSnapshot:
        metadata = payload.get("metadata")
        return ProjectSnapshot(
            id=str(payload["id"]),
            created_at=float(payload["created_at"]),
            total_entries=int(payload["total_entries"]),
            by_type={str(key): int(value) for key, value in dict(payload["by_type"]).items()},
            root_hash=str(payload["root_hash"]) if payload.get("root_hash") is not None else None,
            label=str(payload["label"]) if payload.get("label") else None,
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )
