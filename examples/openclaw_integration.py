"""Bilinc 2.0 cloud-only agent integration example.

Set BILINC_API_KEY before running. The public package talks to hosted Bilinc
Cloud; it does not include the old local StatePlane runtime.
"""

from __future__ import annotations

import os

from bilinc import CloudClient


client = CloudClient(api_key=os.environ.get("BILINC_API_KEY"))

client.commit(
    key="agent.session.current_task",
    value={
        "repo": "agent-runtime",
        "issue": "preserve durable debugging context between runs",
    },
    memory_type="episodic",
    importance=0.8,
    metadata={"source": "openclaw-example"},
)

results = client.recall("durable debugging context", profile="balanced", limit=5)
status = client.status()

print({"status": status.get("status"), "result_count": len(results.get("results", []))})
