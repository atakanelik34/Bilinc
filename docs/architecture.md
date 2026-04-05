# Architecture

Brain-Bridge uses a **multi-layer memory architecture** with semantic search as the primary retrieval method.

## Layers

### Layer 1: Memory (Injected)
- **Size**: ~2,200 chars max
- **Purpose**: Ultra-critical info injected every turn
- **Content**: User preferences, core rules, search flow pattern
- **Update**: Via `memory` tool (add/replace/remove)

### Layer 2: Fabric (Semantic Vector Store)
- **Purpose**: Main knowledge repository
- **Content**: Decisions, research, notes, resolutions, tasks
- **Tools**: `fabric_write`, `fabric_recall`, `fabric_search`
- **Search**: Semantic similarity scoring (ranked results)
- **Training**: High-value entries export for fine-tuning

### Layer 3: Skills (Procedural Memory)
- **Purpose**: Reusable workflows and how-tos
- **Format**: SKILL.md + linked files in ~/.hermes/skills/
- **Content**: Install guides, pitfall lists, verification steps
- **Search**: File content grep

### Layer 4: Session Search (Conversation History)
- **Purpose**: All past conversations, searchable
- **Content**: Full transcripts with LLM-generated summaries
- **Search**: FTS5 + LLM summarization

### Layer 5: Config Files (Technical State)
- **Purpose**: Auth tokens, API keys, environment config
- **Format**: .env, .yml, .json
- **Search**: grep / file inspection

## Bridging Strategy

### Master Index Pattern
Each important topic gets one `fabric_write` entry with `tags: master-index`. This is the **single source of truth** for that topic.

### Cross-References
Master index entries reference each other:
- By `tags` (shared tags connect related entries)
- By `session_id` (links to the conversation that created them)
- By content (explicit links like "→ Infrastructure & Auth: entry_id")

### Search Priority
1. **fabric_recall** — semantic search across all fabric entries (returns ranked by score)
2. **fabric_search** — keyword grep for exact matches
3. **session_search** — historical conversation lookup
4. **skills** — procedural knowledge
5. **memory** — always-injected preferences

### When to Write
- **Auth changes** → fabric entry + config update
- **New tool installed** → fabric entry + skill update
- **Decision made** → fabric_write type=decision
- **Problem solved** → fabric_write type=resolution with outcome
