# 🧠⚡ SynapticAI

**Semantic Multi-Layer Memory System for AI Agents**

SynapticAI gives AI agents a unified memory architecture with semantic search, cross-layer bridging, and master index patterns — so your agent can actually *remember* and *connect the dots*.

## The Problem

AI agents typically have 4-5 separate memory systems:
- Short-term injected memory (system prompt)
- Vector database entries (semantic search)
- Procedural skills (installation guides, workflows)
- Session transcripts (conversation history)
- Config files (tokens, env vars, auth)

**None of them talk to each other.** You have to query each one separately.

## The Solution

SynapticAI connects them all with:

1. **Master Index Pattern** — One authoritative entry per topic
2. **Semantic Search First** — `fabric_recall` finds relevant info across all layers
3. **Cross-Layer References** — Entries link to each other (`tags`, `session_id`, source)
4. **Search Flow Priority** — Single query → ranked results from all layers

## Architecture

```
┌─────────────────────────────────────────────┐
│              fabric_recall "query"          │
│         (semantic search — first stop)       │
├─────────────┬───────────┬─────────┬─────────┤
│  Memory     │  Fabric   │ Session │ Skills  │
│  (prefs)    │  (notes,  │ (history│ (procs) │
│  injected   │  decisions│  + LLM  │ + guide │
│  per-turn)  │  + outcomes) │ sum)  │  lines  │
└─────────────┴───────────┴─────────┴─────────┘
         │           │           │
         └───────────┼───────────┘
                     ▼
            Cross-Layer Index
         (tags, session_id, refs)
```

## Search Flow

```
1. fabric_recall "query"      → semantic search (priority 1)
2. fabric_search "keyword"    → exact keyword match
3. session_search "query"     → historical conversations
4. skills                     → procedural how-tos
5. memory                     → user preferences (always injected)
```

## Master Index Structure

Each master index is a single `fabric_write` entry tagged `master-index`:

```markdown
# Master Index — Topic Name

## Current Status
## Components
## Auth & Config
## Related Skills
## Decisions Made
## Cross-References → other master entries
```

## Installation

```bash
# For Hermes Agent users:
# 1. Clone this repo
# 2. Run the setup script
./scripts/setup.sh

# The script creates:
# - Master index templates in ~/fabric/
# - unified-search skill in ~/.hermes/skills/
# - Memory bridge entries
```

## Usage

Once installed, any agent can retrieve cross-layer memory with:

```
fabric_recall "any topic"    → ranked semantic results
fabric_remember "decision"   → log important decisions
fabric_link "entry_id"       → cross-reference entries
```

## Why It Works

- **Lightweight** — No new infrastructure, just patterns on existing tools
- **Agent-native** — Designed for AI agent memory, not human note-taking
- **Extensible** — Works with fabric, session_search, skills, any config store
- **Search-first** — Single query replaces 5 separate lookups

## License

MIT

## Author

Atakan Elik (@atakanelik34)
