"""MCP stdio adapter for Bilinc Cloud.

Run with:

    python -m bilinc.cloud_mcp

Requires BILINC_API_KEY at call time, not at import time.

This adapter exposes the eight core memory-lifecycle capabilities of hosted
Bilinc — write, recall, deliberately revise, deliberately forget, checkpoint,
inspect a change, restore a known-good state, and inspect runtime status —
without bundling local StatePlane or storage internals.

Operator/debug tooling (health, benchmark, export/import, workspace replay) and
the epistemic read tools (verify, claims, contradictions, graph queries) stay
local-only on purpose: they are not part of the hosted agent contract.
"""

from __future__ import annotations

from typing import Any

from bilinc.client import CloudClient

#: The exact public Cloud MCP surface. Docs, tests, and the site's product
#: truth all check against this list.
CLOUD_MCP_TOOLS = (
    "commit_mem",
    "recall",
    "revise",
    "forget",
    "status",
    "snapshot",
    "diff",
    "rollback",
)


def create_client(api_key: str | None = None, base_url: str = "https://bilinc.space") -> CloudClient:
    """Create a Bilinc Cloud client for MCP adapters."""

    return CloudClient(api_key=api_key, base_url=base_url)


def build_server():
    """Build the MCP server lazily so importing bilinc stays lightweight."""

    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover - depends on optional MCP runtime import path
        raise RuntimeError("Bilinc Cloud MCP adapter requires mcp>=1.0.0") from exc

    mcp = FastMCP("bilinc")

    @mcp.tool()
    def commit_mem(
        key: str,
        value: Any,
        memory_type: str = "semantic",
        importance: float = 1.0,
        metadata: dict[str, Any] | None = None,
        source: str | None = None,
        session_id: str | None = None,
        canonical: bool | None = None,
        priority: float | None = None,
        ttl: float | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Write a memory entry to hosted Bilinc Cloud.

        Creates the entry if it is new and revises it if the key already
        exists. Returns an opaque entry version you can pass to `revise` or
        `forget` as `expected_version` for optimistic concurrency.

        Pass `idempotency_key` when retrying: the same key with the same
        payload returns the original result instead of writing twice.
        """

        return create_client().commit(
            key,
            value,
            memory_type=memory_type,
            importance=importance,
            metadata=metadata,
            source=source,
            session_id=session_id,
            canonical=canonical,
            priority=priority,
            ttl=ttl,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def recall(
        query: str,
        profile: str = "balanced",
        limit: int = 10,
        memory_types: list[str] | None = None,
        explain: bool = False,
        query_timestamp: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve memories from hosted Bilinc Cloud.

        `profile` selects retrieval quality and cost: fast, balanced,
        verified, or deep. Higher profiles do more reflection and return more
        provenance, and are gated by the workspace plan — call `status` to see
        which profiles this key may use. Smart retrieval is this argument, not
        a separate tool.
        """

        return create_client().recall(
            query,
            profile=profile,
            limit=limit,
            memory_types=memory_types,
            explain=explain,
            query_timestamp=query_timestamp,
        )

    @mcp.tool()
    def revise(
        key: str,
        value: Any,
        importance: float = 1.0,
        strategy: str = "entrenchment",
        reason: str | None = None,
        expected_version: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Deliberately replace an existing memory, preserving belief revision.

        Use this instead of `commit_mem` when you intend to correct or
        supersede something you already know, so the change is recorded as a
        revision rather than an accidental overwrite.

        Fails with `memory_not_found` if the key does not exist: revise never
        creates. Pass `expected_version` from a previous write to fail with
        `version_conflict` instead of clobbering a concurrent change.
        """

        return create_client().revise(
            key,
            value,
            importance=importance,
            strategy=strategy,
            reason=reason,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def forget(
        key: str,
        reason: str,
        expected_version: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Remove a memory from active recall. DESTRUCTIVE.

        This is a destructive operation: the entry stops influencing every
        future recall in this project. `reason` is required and is written to
        the audit trail. The deleted value is never returned.

        Use this for state that is genuinely obsolete. To correct a memory
        rather than remove it, use `revise`.
        """

        return create_client().forget(
            key,
            reason=reason,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def status() -> dict[str, Any]:
        """Report the authenticated Bilinc Cloud workspace, plan, and capabilities.

        Read-only and never billed. Use this to discover which lifecycle
        operations and recall profiles the current API key may use before
        attempting them. Secrets are never returned.
        """

        return create_client().status()

    @mcp.tool()
    def snapshot(
        action: str = "create",
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
        limit: int = 20,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create or list project checkpoints.

        Take a checkpoint with `action="create"` before risky work so you can
        inspect or restore it later; `action="list"` returns existing
        checkpoints newest first and is free. Neither returns the checkpoint's
        contents.
        """

        return create_client().snapshot(
            action,
            label=label,
            metadata=metadata,
            limit=limit,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def diff(
        from_snapshot_id: str,
        to_snapshot_id: str | None = None,
        include_values: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Compare a checkpoint against another checkpoint or current state.

        Read-only and free. Leave `to_snapshot_id` empty to see what has
        changed since the checkpoint was taken. Values are redacted unless
        `include_values` is set; a value-bearing diff that would be too large
        is refused rather than silently truncated.
        """

        return create_client().diff(
            from_snapshot_id,
            to_snapshot_id=to_snapshot_id,
            include_values=include_values,
            limit=limit,
        )

    @mcp.tool()
    def rollback(
        snapshot_id: str,
        reason: str,
        mode: str = "preview",
        confirmation_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Restore the project to a checkpoint. DESTRUCTIVE in execute mode.

        Two stages, and you must run them in order:

        1. `mode="preview"` is free and changes nothing. It reports what would
           be created, updated, and removed, and returns a short-lived
           `confirmation_token`.
        2. `mode="execute"` requires that token and permanently discards every
           memory created or changed since the checkpoint.

        Execute fails with `state_changed_since_preview` if the project
        changed after the preview, so review the preview and act on it
        promptly rather than reusing an old one. `reason` is required in both
        modes and is written to the audit trail.
        """

        client = create_client()
        if mode == "preview":
            return client.rollback_preview(snapshot_id, reason=reason)
        if mode == "execute":
            return client.rollback(
                snapshot_id,
                confirmation_token=confirmation_token or "",
                reason=reason,
                idempotency_key=idempotency_key,
            )
        raise ValueError("mode must be either preview or execute")

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()


__all__ = ["CLOUD_MCP_TOOLS", "CloudClient", "build_server", "create_client", "main"]
