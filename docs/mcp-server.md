# MCP Server Reference

Bilinc exposes full memory functionality via **Model Context Protocol (MCP)**, enabling any MCP-compatible agent (Claude Code, Cursor, OpenClaw, VS Code Copilot) to use Bilinc as a cross-tool memory layer.

## Quick Start

```python
from bilinc.mcp_server.server_v2 import create_mcp_server_v2
from bilinc import StatePlane
import asyncio
from mcp.server.stdio import stdio_server

# Initialize StatePlane with all components
plane = StatePlane()
plane.init_agm()
plane.init_knowledge_graph()

# Create MCP server (12 tools exposed)
server = create_mcp_server_v2(plane)

# Run (stdio transport — Claude Code compatible)
async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

asyncio.run(main())
```

## Tool Reference

### 1. commit_mem

Store a memory entry with automatic AGM belief revision.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| key | string | ✅ | — | Unique identifier (alphanumeric, max 256 chars) |
| value | string | ✅ | — | Memory content (any JSON-serializable value) |
| memory_type | string | ❌ | semantic | episodic, procedural, semantic, working, spatial |
| importance | number | ❌ | 1.0 | Importance 0.0-1.0 (affects AGM conflict resolution) |
| source | string | ❌ | mcp | Source system identifier |

**Returns:** AGM revision result with conflict resolution details.

```json
{
  "tool": "commit_mem",
  "success": true,
  "operation": "revise",
  "conflicts_resolved": 1,
  "explanation": "Replaced old value via entrenchment strategy"
}
```

### 2. recall

Retrieve memory entries by key, type, or all entries.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| key | string | ❌ | — | Specific key to recall |
| memory_type | string | ❌ | — | Filter by type |
| limit | integer | ❌ | 20 | Max entries to return |
| min_strength | number | ❌ | 0.0 | Minimum current_strength |

**Returns:** List of MemoryEntry objects with full metadata.

### 3. forget

Permanently remove a memory entry.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| key | string | ✅ | — | Memory key to delete |
| reason | string | ❌ | manual | Audit reason |

### 4. revise

AGM belief revision with configurable conflict resolution.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| key | string | ✅ | — | Memory key |
| value | string | ✅ | — | New value |
| importance | number | ❌ | 1.0 | Importance of new belief |
| strategy | string | ❌ | entrenchment | entrenchment, recency, verification, importance |

**Strategies:**
- **entrenchment**: Less entrenched beliefs are dropped first
- **recency**: Trust newer over older
- **verification**: Trust verified over unverified
- **importance**: Trust higher importance

### 5. status

Operational statistics for all components (AGM, Knowledge Graph, Belief Sync, Working Memory).

```json
{
  "tool": "status",
  "version": "0.4.0a1",
  "agm": {
    "beliefs": 42,
    "operations": 156,
    "entrenchment_keys": 38
  },
  "knowledge_graph": {
    "nodes": 2,
    "edges": 0,
    "contradictions": 0,
    "density": 0.0
  }
}
```

### 6. verify

Run Z3 SMT verification on a specific memory key.

### 7. consolidate

Trigger the sleep consolidation cycle (moves working memory → long-term, applies forgetting curves).

### 8. snapshot

Get a verifiable state snapshot including all beliefs, entrenchment values, and optionally full AGM operation log.

### 9. diff

Compare state between two timestamps (requires persistent storage).

### 10. rollback

Restore state to a previous timestamp (requires persistent storage).

### 11. query_graph

Query the Knowledge Graph for entities and relations.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| entity | string | ✅ | — | Entity name to query |
| max_depth | integer | ❌ | 2 | Maximum traversal depth (1-5) |
| relation_filter | array | ❌ | — | Filter by edge type: related_to, causes, contradicts, supports, temporal_before |

```json
{
  "tool": "query_graph",
  "nodes": [
    {"name": "server_config", "node_type": "fact", "properties": {"value": "host=prod..."}}
  ],
  "edges": [],
  "depth": 2,
  "start": "server_config"
}
```

### 12. contradictions

List all detected contradictions in the Knowledge Graph. Returns pairs of conflicting relations that require resolution.

## Security

- **API Key Auth**: Optional `Authorization: Bearer` header via `STATEMEL_API_KEY` env var
- **Rate Limiting**: Per-client token bucket (default: 10 req burst, 1/sec refill)
- **Input Validation**: Key pattern matching, path traversal protection, XSS sanitization
- **Resource Limits**: Max 16 working memory slots, max 50k episodic entries, max 100k KG nodes

## Error Handling

All tools return structured JSON on error:

```json
{
  "tool": "commit_mem",
  "error": "ValueError",
  "message": "Key contains illegal characters (path traversal attempt).",
  "success": false
}
```

Tools never crash on invalid input — errors are always returned as TextContent.
