"""Database-side serialization of hash-chain appends.

An append reads the chain head and inserts the next link in one transaction. Without a lock two
transactions can read the same head and both link to it, which forks the chain for good. Every
append takes this transaction-scoped advisory lock first, so only one append per tenant schema
and chain is between reading the head and committing. The lock key follows ``current_schema()``,
so it is per tenant (or ``public``) without the caller naming it.
"""
from __future__ import annotations

# Bounds the wait: a second writer stuck idle in a transaction fails the append instead of
# freezing a process that waits in a blocking call.
CHAIN_LOCK_TIMEOUT = "10s"

_CHAINS = ("audit_log", "memory_events")


def lock_timeout_sql() -> str:
    return f"SET LOCAL lock_timeout = '{CHAIN_LOCK_TIMEOUT}'"


def lock_sql(chain: str) -> str:
    if chain not in _CHAINS:
        raise ValueError(f"unknown chain: {chain}")
    return f"SELECT pg_advisory_xact_lock(hashtextextended('bilinc_chain:{chain}:' || current_schema(), 0))"
