"""Tenant isolation for the PostgreSQL backend.

Every Bilinc Cloud project gets its own PostgreSQL schema, and every connection
that serves the project pins ``search_path`` to it. That mirrors the SQLite
runtime, where each project owns a separate database file: no query can read or
write another project's rows, because another project's tables are simply not
visible on the connection. It does not depend on every query remembering a
``WHERE project_id = ...`` filter.
"""
from __future__ import annotations

import re
from uuid import UUID

#: Tables the backend and the audit trail create; all must live in the tenant schema.
TENANT_TABLES = (
    "schema_version",
    "bilinc_entries",
    "eval_candidates",
    "bilinc_claims",
    "entities",
    "entity_mentions",
    "memory_events",
    "audit_log",
)

_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_PROJECT_SCHEMA_PREFIX = "bilinc_p_"


def project_schema(project_id: str) -> str:
    """Schema name for a project: ``bilinc_p_`` plus the UUID's 32 hex digits."""
    return f"{_PROJECT_SCHEMA_PREFIX}{UUID(str(project_id)).hex}"


def validate_schema_name(name: str) -> str:
    """Return ``name`` if it is a safe, unquoted-style identifier; raise otherwise."""
    if not isinstance(name, str) or not _SCHEMA_NAME.match(name) or name in {"public", "pg_catalog", "information_schema"}:
        raise ValueError("invalid_tenant_schema")
    return name


def quoted(name: str) -> str:
    """Double-quoted identifier for an already-validated schema name."""
    return '"' + validate_schema_name(name) + '"'


def search_path_sql(name: str) -> str:
    """``SET search_path`` pinning the tenant schema first; ``public`` only resolves extension types."""
    return f"SET search_path TO {quoted(name)}, public"


def search_path_setting(name: str) -> str:
    """The ``search_path`` value to send as a connection startup parameter.

    A startup parameter becomes the session default, so poolers that run
    ``RESET ALL`` between uses (asyncpg does) return to the tenant schema
    instead of falling back to ``public``. Names are validated, so no quoting
    is needed.
    """
    return f"{validate_schema_name(name)},public"
