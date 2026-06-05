# Memory Architecture

Hermes Agent uses a **three-layer memory system** to provide short-term, medium-term, and long-term recall capabilities. Each layer serves a distinct purpose and operates with different retention policies, query strategies, and data models.

## Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Hermes Agent                            │
│                       MemoryManager                             │
└────────────┬────────────────────┬────────────────┬──────────────┘
             │                    │                │
             ▼                    ▼                ▼
    ┌────────────────┐   ┌────────────────┐   ┌──────────────────┐
    │   Hindsight    │   │  Memory Graph  │   │ memory_tencentdb │
    │   (Layer 1)    │   │   (Layer 2)    │   │   (Layer 3)      │
    └────────────────┘   └────────────────┘   └──────────────────┘
         SQLite              PostgreSQL           Node.js Gateway
       Full-text            Hierarchical          4-Layer Memory
        Search             Path-based            (L0→L1→L2→L3)
                            Graph

         Session            Structured          Deep Episodic
         History            Knowledge           + Persona
```

## Layer 1: Hindsight — Session History & Full-Text Search

**Purpose**: Short-to-medium-term conversation history with semantic and full-text search.

**Storage**:
- SQLite database (`~/.hermes/hindsight/hindsight.db`)
- FTS5 (Full-Text Search 5) virtual tables for fast text retrieval
- Vector embeddings for semantic search (optional, via `sqlite-vec`)

**Data Model**:
```python
ConversationEntry:
  - id (autoincrement)
  - platform (telegram, cli, discord, weixin, ...)
  - user_id (platform-specific user identifier)
  - role (user | assistant | system)
  - content (message text)
  - timestamp
  - session_id
  - namespace (for multi-user isolation)
```

**When to Use**:
- Recall recent conversation context (last N turns)
- Full-text search across historical messages
- Session-specific memory (what happened in *this* conversation)
- Cross-platform user memory unification (via `user_mapper`)

**Write Path**:
1. Agent turn completes
2. `MemoryManager.store()` → Hindsight provider
3. Entry written to SQLite with FTS5 index update
4. Namespace isolation applied based on `user_id` / `platform`

**Recall Path**:
1. User query → `session_search` tool or auto-context retrieval
2. FTS5 query against `conversations` table
3. Filter by `namespace` / `user_id` for multi-user isolation
4. Results ranked by relevance and recency
5. Top K entries injected into system prompt

**Configuration**:
```yaml
# ~/.hermes/config.yaml
hindsight:
  enabled: true
  database_path: ~/.hermes/hindsight/hindsight.db
  retention_days: 90  # Automatic cleanup
  fts5_tokenizer: unicode61  # Or porter for stemming
```

**Key Features**:
- **Multi-user isolation**: Queries scoped by `namespace` (user_id + platform hash)
- **CJK search support**: Trigram-based search for Chinese/Japanese/Korean
- **Platform filtering**: `HINDSIGHT_SKIP_PLATFORMS` env var excludes platforms (e.g., `weixin` for privacy)
- **Auto-context retrieval**: Automatically injects relevant past messages into system prompt

---

## Layer 2: Memory Graph — Structured Hierarchical Knowledge

**Purpose**: Medium-to-long-term structured knowledge organized as a hierarchical graph with path-based navigation.

**Storage**:
- PostgreSQL database (shared with Hindsight or standalone)
- Tables: `mg_nodes`, `mg_memories`, `mg_edges`, `mg_paths`, `mg_search_documents`, `mg_glossary_keywords`

**Data Model**:
```
Node (UUID)
  └─ Memory (content, version history)
  └─ Edges (parent → child relationships)
       └─ Paths (namespace://domain://path/to/memory)
       └─ Glossary Keywords
       └─ Search Documents (derived, tsvector indexed)
```

**Schema**:
```
mg_nodes:           uuid, created_at, last_accessed_at
mg_memories:        id, node_uuid, content, deprecated, migrated_to
mg_edges:           parent_uuid, child_uuid, name, priority, disclosure
mg_paths:           namespace, domain, path, edge_id, node_uuid
mg_search_documents: namespace, domain, path, content, search_vector (tsvector)
mg_glossary_keywords: keyword, node_uuid, namespace
```

**When to Use**:
- Structured knowledge that needs to be organized hierarchically
- User preferences, instructions, project-specific rules
- Content that should be versioned (with rollback support)
- Knowledge that needs path-based addressing (`core://user/preferences/editor`)

**Write Path**:
1. Tool call: `memory_graph_create(parent_uri="core://projects", content="...", title="myproject")`
2. `GraphService.create_memory()`:
   - Create node UUID (or reuse existing)
   - Insert `Memory` record
   - Create `Edge` linking parent → child
   - Compute path from parent + name
   - Insert `Path` record
3. `SearchIndexer.refresh_search_documents_for_node()`:
   - Build derived `SearchDocument` rows (one per path)
   - Populate `search_vector` (tsvector) via GENERATED column
   - Insert into `mg_search_documents`

**Recall Path**:
1. Tool call: `memory_graph_read(uri="core://projects/myproject")`
   OR: `memory_graph_search(q="myproject")`
2. **Path-based recall**:
   - Parse `domain://path`
   - Query `mg_paths` → resolve to `node_uuid`
   - Query `mg_memories` where `node_uuid = X AND deprecated = false`
   - Return `{content, uri, priority, disclosure, ...}`
3. **Search-based recall**:
   - Tokenize query with CJK segmentation (jieba)
   - Query `mg_search_documents` using `websearch_to_tsquery('simple', query)`
   - Rank by `ts_rank_cd(search_vector, query)` + priority
   - Deduplicate by `node_uuid`
   - Return top K results

**Configuration**:
```yaml
# ~/.hermes/config.yaml
memory_graph:
  enabled: true
  database_url: postgresql://localhost/hindsight
  # Shares Hindsight's PostgreSQL by default
```

**Key Features**:
- **Path-based navigation**: `core://user/preferences/editor` → structured hierarchy
- **Multi-namespace**: Each user gets isolated graph (namespace = user_id hash)
- **Version history**: Memory updates create new records, old ones marked `deprecated`
- **Disclosure field**: Contextual hints injected into parent listings
- **Glossary keywords**: Custom search terms per node
- **Search-as-Code**: tsvector + GIN index + ts_rank_cd ranking (see SEARCH_AS_CODE.md)

---

## Layer 3: memory_tencentdb — Deep Episodic + Persona Memory

**Purpose**: Long-term episodic memory with automatic extraction, scene blocks, and persona synthesis.

**Architecture**:
```
Hermes Agent (Python)
  └─ MemoryTencentdbProvider
       ├─ GatewaySupervisor (starts Node.js Gateway)
       └─ MemoryTencentdbSdkClient (HTTP client)
            │
            ▼  HTTP (127.0.0.1:8420)
       memory-tencentdb Gateway (Node.js)
         └─ Four-Layer Memory Core
              ├─ L0: Conversation capture (SQLite + JSONL)
              ├─ L1: Episodic extraction (LLM + vector dedup)
              ├─ L2: Scene blocks (Markdown files)
              └─ L3: Persona synthesis (persona.md)
```

**Data Model**:

**L0 (Conversation Capture)**:
- Raw conversation turns stored in SQLite + JSONL
- No processing, just append-only log
- Retention: indefinite (or config-driven)

**L1 (Episodic Extraction)**:
- LLM extracts structured memories from L0
- Vector deduplication to avoid redundant storage
- Schema: `{type, content, timestamp, embedding}`

**L2 (Scene Blocks)**:
- Markdown files grouping related episodes by context/time
- File path: `~/.memory-tencentdb/memory-tdai/scenes/<date>_<topic>.md`

**L3 (Persona Synthesis)**:
- Single `persona.md` file synthesizing user's personality, preferences, communication style
- Updated periodically by LLM analyzing L1/L2 content

**When to Use**:
- Long-term episodic memory that survives session boundaries
- Automatic extraction of "important moments" from conversations
- Persona-aware responses (user's preferences, communication style)
- Projects requiring deep context understanding

**Write Path**:
1. Agent turn completes
2. `MemoryTencentdbProvider.sync_turn()` → background thread
3. `POST /capture` to Gateway (fire-and-forget)
4. Gateway schedules L0 write → L1 extraction → L2 scene update → L3 persona refresh (pipeline)

**Recall Path**:
1. `MemoryTencentdbProvider.prefetch(query)` → `POST /recall`
2. Gateway:
   - Query L1 vector store (semantic search on embeddings)
   - Query L2 scene blocks (full-text)
   - Query L3 persona (always included)
3. Return merged context as `<memory-context>` XML block
4. Injected into system prompt

**Configuration**:
```yaml
# ~/.hermes/config.yaml
memory:
  provider: memory_tencentdb

# Environment variables:
export MEMORY_TENCENTDB_LLM_API_KEY="sk-..."
export MEMORY_TENCENTDB_LLM_BASE_URL="https://api.openai.com/v1"
export MEMORY_TENCENTDB_LLM_MODEL="gpt-4o"
export TDAI_DATA_DIR="~/.memory-tencentdb/memory-tdai"
```

**Key Features**:
- **Zero-config auto-discovery**: Gateway auto-starts if `src/gateway/server.ts` found
- **Circuit breaker**: 5 consecutive failures → pause calls for 60s
- **Back-pressure control**: Max 4 concurrent capture threads
- **LLM tools**: `memory_tencentdb_memory_search`, `memory_tencentdb_conversation_search`
- **Supervised startup**: Health checks with crash diagnostics

---

## Decision Tree: Which Memory Layer to Use?

```
START: What kind of data are you storing?

├─ Recent conversation history (last N turns)?
│  └─ USE: Hindsight (Layer 1)
│     Tools: session_search, hindsight
│
├─ Structured knowledge (preferences, rules, project info)?
│  ├─ Needs hierarchical organization?
│  │  └─ USE: Memory Graph (Layer 2)
│  │     Tools: memory_graph_read, memory_graph_create, memory_graph_search
│  │
│  └─ Flat/unstructured?
│     └─ USE: Hindsight (Layer 1)
│
└─ Long-term episodic memory (persona, life events)?
   └─ USE: memory_tencentdb (Layer 3)
      Tools: memory_tencentdb_memory_search, memory_tencentdb_conversation_search
```

### Decision Matrix

| Use Case | Hindsight | Memory Graph | memory_tencentdb |
|----------|-----------|--------------|------------------|
| Recall last 5 messages | ✅ | ❌ | ❌ |
| Search past conversations | ✅ | ❌ | ✅ |
| Store user preferences | ⚠️ | ✅ | ✅ |
| Hierarchical navigation | ❌ | ✅ | ❌ |
| Version control/rollback | ❌ | ✅ | ❌ |
| Persona synthesis | ❌ | ❌ | ✅ |
| Multi-user isolation | ✅ | ✅ | ⚠️ (namespace) |
| CJK language support | ✅ | ✅ | ✅ |
| Automatic extraction | ❌ | ❌ | ✅ |
| Path-based addressing | ❌ | ✅ | ❌ |

---

## Data Flow Diagrams

### Write Path (All Layers)

```
Agent Turn Completes
  │
  ├─► Hindsight Provider
  │     └─► SQLite: INSERT conversation_entry
  │          └─► FTS5 index auto-update
  │
  ├─► Memory Graph Provider (if tool called)
  │     └─► PostgreSQL:
  │          ├─► INSERT mg_memories
  │          ├─► INSERT mg_edges
  │          ├─► INSERT mg_paths
  │          └─► Trigger: refresh_search_documents
  │               └─► INSERT mg_search_documents
  │                    └─► GENERATED tsvector column
  │
  └─► memory_tencentdb Provider
        └─► POST /capture (background thread)
             └─► Gateway:
                  ├─► L0: SQLite + JSONL write
                  ├─► L1: LLM extraction (async)
                  ├─► L2: Scene block update (async)
                  └─► L3: Persona refresh (periodic)
```

### Recall Path (All Layers)

```
User Query: "What did I say about the database?"

  │
  ├─► Auto-Context Retrieval
  │     ├─► Hindsight: FTS5 query
  │     │    └─► Top 3 matches → system prompt
  │     │
  │     └─► memory_tencentdb: POST /recall
  │          └─► L1 vector search + L2 text search + L3 persona
  │               └─► <memory-context> → system prompt
  │
  ├─► LLM decides to use tools
  │     │
  │     ├─► memory_graph_search(q="database")
  │     │    └─► PostgreSQL: websearch_to_tsquery + ts_rank_cd
  │     │         └─► Return ranked results
  │     │
  │     └─► session_search(query="database")
  │          └─► Hindsight: FTS5 query
  │               └─► Return conversation history
  │
  └─► LLM synthesizes answer from all sources
```

---

## Configuration Decision Tree

### "I want to enable memory in Hermes. What do I configure?"

```
1. Choose primary provider in ~/.hermes/config.yaml:

   memory:
     provider: hindsight          # Default, always available
     # OR
     provider: memory_tencentdb   # Requires Gateway setup

2. Hindsight is ALWAYS active (even if not primary provider)
   - No extra config needed
   - Auto-creates ~/.hermes/hindsight/hindsight.db

3. Memory Graph is ALWAYS active (bundled with hermes-patches)
   - Shares Hindsight's PostgreSQL
   - No extra config needed

4. memory_tencentdb requires:
   - Gateway LLM credentials:
     export MEMORY_TENCENTDB_LLM_API_KEY="sk-..."
     export MEMORY_TENCENTDB_LLM_BASE_URL="https://api.openai.com/v1"
     export MEMORY_TENCENTDB_LLM_MODEL="gpt-4o"
   - Gateway auto-discovers or manual start
```

### "How do I enable multi-user isolation?"

```yaml
# Hindsight: automatic via platform + user_id
# Memory Graph: automatic via namespace (user_id hash)
# memory_tencentdb: namespace-aware (configure in Gateway)

# Optional: Skip specific platforms in Hindsight
export HINDSIGHT_SKIP_PLATFORMS="weixin"  # Comma-separated
```

### "How do I tune search performance?"

See [SEARCH_AS_CODE.md](./SEARCH_AS_CODE.md) for:
- GIN index configuration
- FTS5 tokenizer selection
- CJK search optimization
- Benchmarks and query syntax

---

## Memory Lifecycle

### Hindsight (Session History)
- **Write**: Every agent turn → SQLite insert
- **Read**: On-demand via tools or auto-context
- **Retention**: Configurable (default: 90 days)
- **Cleanup**: Periodic DELETE WHERE timestamp < cutoff

### Memory Graph (Structured Knowledge)
- **Write**: Explicit tool calls only (`memory_graph_create`, `memory_graph_update`)
- **Read**: Path-based or search-based
- **Retention**: Indefinite (manual deletion only)
- **Version Control**: Old memories marked `deprecated`, rollback supported

### memory_tencentdb (Deep Episodic)
- **Write**: Every agent turn → Gateway pipeline (async)
- **Read**: Auto-injected via `prefetch()` or tool calls
- **Retention**: Configurable per layer (L0/L1/L2/L3)
- **Cleanup**: Gateway-managed (LLM-driven pruning)

---

## Troubleshooting

### "Hindsight not recalling past conversations"
1. Check namespace isolation: `SELECT DISTINCT namespace FROM conversations;`
2. Verify FTS5 index: `SELECT * FROM conversations_fts WHERE conversations_fts MATCH 'query';`
3. Check platform filtering: `HINDSIGHT_SKIP_PLATFORMS` env var

### "Memory Graph search returns no results"
1. Verify GIN index exists: `\d+ mg_search_documents` in psql
2. Check tsvector population: `SELECT search_vector FROM mg_search_documents LIMIT 1;`
3. Run migration: `psql -f agent/memory_graph/migrations/001_add_search_index.sql`

### "memory_tencentdb Gateway not starting"
1. Check auto-discovery: `~/.hermes/logs/memory_tencentdb/gateway.stderr.log`
2. Verify LLM credentials: `MEMORY_TENCENTDB_LLM_API_KEY` set?
3. Manual start: `node --import tsx src/gateway/server.ts`
4. Check health: `curl http://127.0.0.1:8420/health`

---

## Best Practices

1. **Use Hindsight for ephemeral context** (recent turns, session history)
2. **Use Memory Graph for durable knowledge** (preferences, rules, project state)
3. **Use memory_tencentdb for persona + life events** (long-term episodic)
4. **Enable auto-context retrieval** (searches Hindsight + memory_tencentdb on every turn)
5. **Set namespace isolation** in multi-user deployments
6. **Run GIN index migration** for Memory Graph performance
7. **Monitor Gateway health** for memory_tencentdb reliability

---

## Related Documentation

- [SEARCH_AS_CODE.md](./SEARCH_AS_CODE.md) — Full-text search implementation details
- [plugins/memory/memory_tencentdb/README.md](../plugins/memory/memory_tencentdb/README.md) — memory_tencentdb provider setup
- [agent/memory_graph/README.md](../agent/memory_graph/README.md) — Memory Graph API reference

---

Generated by hermes-patches documentation suite.
