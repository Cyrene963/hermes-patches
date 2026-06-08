# Memory System Comparison Guide

## Overview

Hermes Agent supports three complementary memory systems, each designed for different use cases and memory architectures. This guide helps you choose the right system for your needs.

---

## Quick Comparison Table

| Feature | **hindsight** | **memory_graph** | **memory_tencentdb** |
|---------|---------------|------------------|---------------------|
| **Storage Type** | SQLite/session or configured backend | PostgreSQL (`hindsight` DB, `mg_*` tables) + HTTP service | Local files / SQLite or Tencent VectorDB via Gateway |
| **Memory Structure** | Raw/evidence memory units | Structured knowledge graph | Four-layer hierarchy (conversation → extraction → scenes → persona) |
| **Processing** | Provider-managed retain/recall | Explicit tools + review/approval | AI-powered automatic extraction |
| **Best For** | Evidence archive and semantic recall | Precise canonical facts/rules/projects | Long-term user persona & preferences |
| **Setup Complexity** | Provider-dependent | Medium (PostgreSQL + Memory Graph service) | Medium (requires Node.js Gateway) |
| **Recall Speed** | Instant (N recent turns) | Fast (indexed graph) | Fast (semantic search) |
| **Memory Lifespan** | Short-term (sliding window) | Permanent (until deleted) | Long-term (persistent across sessions) |
| **Content Type** | Verbatim dialogue | Facts, rules, worldview | User preferences, history, patterns |
| **Editing** | Automatic (FIFO) | Manual via tools | Automatic via LLM |
| **Search Method** | Recency-based | Graph traversal + disclosure rules | Semantic similarity (embeddings) |
| **Typical Size** | Last 10-50 turns | 100s-1000s of nodes | Unlimited (compresses via layers) |

---

## Detailed System Descriptions

### 1. hindsight — Short-Term Conversation Memory

**What it does:**
- Stores the most recent N conversation turns verbatim
- Automatically injects recent context into each new turn
- Works as a sliding window: oldest turns drop out as new ones arrive

**Architecture:**
```
[Turn 1] → [Turn 2] → [Turn 3] → ... → [Turn N]
   ↓          ↓          ↓                  ↓
Oldest turns automatically pruned when limit is reached
```

**When to use:**
- ✅ You want the agent to remember "what we just talked about"
- ✅ Zero configuration required
- ✅ Conversations are short-lived (single session)
- ❌ Don't use for long-term memory (disappears after N turns)

**Configuration:**
```yaml
memory:
  provider: hindsight
  hindsight:
    window_size: 20  # Keep last 20 turns
```

**Example use case:**
> User: "I need to debug that authentication issue"  
> Agent: [recalls from hindsight] "You mentioned the auth token expires in 5 minutes..."

---

### 2. memory_graph — Structured Knowledge Graph

**What it does:**
- Stores hand-crafted, structured knowledge as nodes and edges
- Supports hierarchical organization (namespaces, child nodes)
- Uses "disclosure rules" to trigger context injection based on keywords

**Architecture:**
```
root://
├── core://
│   ├── user-preferences
│   │   ├── coding-style (trigger: "code style|format")
│   │   └── tools (trigger: "vim|editor")
│   └── projects/
│       └── hermes-agent (trigger: "hermes|agent")
└── worldview://
    └── memory-architecture (trigger: "memory system")
```

**When to use:**
- ✅ You want precise control over what the agent remembers
- ✅ You need hierarchical organization (worldview, projects, preferences)
- ✅ You want trigger-based context injection ("when user says X, remind me of Y")
- ❌ Don't use if you want fully automatic memory extraction

**Configuration / health check:**
```bash
# Memory Graph is a patched service/toolset, not a SQLite db_path provider.
curl -fsS http://127.0.0.1:8900/health
cd ~/.hermes/hermes-agent
venv/bin/python - <<'PY'
from toolsets import TOOLSETS, _HERMES_CORE_TOOLS
print('memory_graph tools:', len(TOOLSETS.get('memory_graph', {}).get('tools', [])))
print('memory_graph_search in core:', 'memory_graph_search' in _HERMES_CORE_TOOLS)
PY
```

**Example use case:**
> You create a node: `core://projects/focuspomo` with content "Focus timer app, uses TypeScript, Redis for state"  
> Trigger: `"focuspomo|focus.*timer"`  
> 
> Later:  
> User: "How does focuspomo handle state?"  
> Agent: [auto-injects node] "Focuspomo uses Redis for state management..."

---

### 3. memory_tencentdb — AI-Powered Long-Term Memory

**What it does:**
- Automatically extracts structured memories from conversations using LLM
- Organizes memories into 4 layers:
  - **L0**: Raw conversation history
  - **L1**: Extracted facts & events
  - **L2**: Scene blocks (thematic clusters)
  - **L3**: Persona synthesis (user profile)
- Provides semantic search across all layers

**Architecture:**
```
L0 (Raw Dialogue)
   ↓ LLM extraction
L1 (Facts & Events)
   "User prefers dark mode"
   "User's project: hermes-agent"
   ↓ clustering
L2 (Scene Blocks)
   "User Interface Preferences"
   "Active Projects"
   ↓ synthesis
L3 (Persona)
   "Software engineer working on AI agents,
    prefers minimal UI, uses Vim..."
```

**When to use:**
- ✅ You want the agent to "learn" about the user over time
- ✅ You need cross-session memory (remembers across restarts)
- ✅ You want automatic preference detection ("I like X", "I don't like Y")
- ✅ You need semantic search ("what did I say about databases?")
- ❌ Don't use if you can't run Node.js Gateway (requires external service)

**Configuration:**
```bash
# Environment variables
export MEMORY_TENCENTDB_GATEWAY_PORT=8420
export MEMORY_TENCENTDB_LLM_API_KEY="your-api-key"
export MEMORY_TENCENTDB_LLM_MODEL="gpt-4o"
```

```yaml
# In hermes config (canonical single-provider schema)
memory:
  provider: memory_tencentdb
```

> Do not mix this with legacy `memory_providers:` examples unless the specific provider README documents that schema. For the default Hermes/Hindsight path, use `memory.provider: hindsight`.

**Example use case:**
> Session 1:  
> User: "I prefer using PostgreSQL over MySQL for production"  
> [memory_tencentdb captures → L1 extraction → L2 clustering → L3 persona]
> 
> Session 2 (days later):  
> User: "What database should I use for this new project?"  
> Agent: [searches memory_tencentdb] "You mentioned you prefer PostgreSQL for production..."

---

## Decision Tree: Which System Should I Use?

```
┌─ Do you need memory at all?
│  ├─ No → Skip all memory providers
│  └─ Yes ↓

├─ Is this a single short conversation?
│  ├─ Yes → Use **hindsight** only
│  └─ No ↓

├─ Do you want manual control over memory structure?
│  ├─ Yes → Add **memory_graph**
│  │  └─ Use cases:
│  │      • Worldview / character definitions
│  │      • Project-specific rules
│  │      • Trigger-based context injection
│  └─ No ↓

├─ Do you want the agent to automatically learn about the user?
│  ├─ Yes → Add **memory_tencentdb**
│  │  └─ Requirements:
│  │      • Node.js installed
│  │      • LLM API key for extraction
│  │      • Willing to run Gateway sidecar
│  └─ No → Stick with **hindsight**
```

---

## Common Configurations

### Configuration 1: Minimal (session + evidence memory)
**Goal:** Basic conversation continuity and evidence recall

```yaml
memory:
  provider: hindsight
  hindsight:
    window_size: 20
```

**Use case:** Quick prototyping, demos, short tasks, or a simple evidence archive.

---

### Configuration 2: Power User (Manual Canonical Graph)
**Goal:** Precise knowledge management + recent/evidence context

Memory Graph is a patched service/toolset backed by PostgreSQL. Keep the normal memory provider config separate, then verify Memory Graph service/tool wiring:

```yaml
memory:
  provider: hindsight
  hindsight:
    window_size: 20
```

```bash
curl -fsS http://127.0.0.1:8900/health
cd ~/.hermes/hermes-agent
venv/bin/python - <<'PY'
from toolsets import TOOLSETS, _HERMES_CORE_TOOLS
assert 'memory_graph' in TOOLSETS
assert 'memory_graph_search' in _HERMES_CORE_TOOLS
print('memory_graph ready')
PY
```

**Use case:**
- You maintain a "second brain" of facts, preferences, and worldview
- You want exact tools/review queues for canonical facts
- You're willing to manually curate or approve Memory Graph changes

---

### Configuration 3: Autonomous Assistant (AI-Powered)
**Goal:** Agent learns about you automatically over time

```yaml
memory:
  provider: memory_tencentdb
```

> `memory_tencentdb` has its own provider README and sidecar requirements. Do not mix this with Memory Graph's PostgreSQL/toolset setup unless you have verified namespace, bank, and prompt-injection behavior for both.

**Use case:**
- Long-term personal assistant
- Cross-session memory persistence
- You want the agent to remember preferences without manual input
- You have Node.js and can run the Gateway

---

### Configuration 4: Hybrid (evidence + canonical graph + optional learned persona)
**Goal:** Hybrid approach with explicit boundaries

```yaml
memory:
  provider: hindsight
  hindsight:
    window_size: 20
```

Then separately verify Memory Graph (`curl :8900/health` + toolset registration) and only enable `memory_tencentdb` if you intentionally want the extra sidecar.

**Use case:**
- **hindsight** handles evidence / raw recall
- **memory_graph** stores canonical facts, rules, projects, and approved review proposals
- **memory_tencentdb** can optionally learn preferences/patterns, but should not be enabled casually on a multi-user instance

**How they work together:**
1. **hindsight** provides evidence and semantic recall
2. **memory_graph** provides approved canonical facts and rules through tools/review queues
3. **memory_tencentdb** is optional and provider-specific
4. Avoid enabling multiple automatic memory writers until namespace/readback behavior is verified

---

## System Integration & Data Flow

### How Hermes Merges Multiple Memory Systems

When multiple providers are enabled, Hermes calls each one during the prefetch phase and combines their results:

```
User message: "Let's work on the auth bug we talked about yesterday"
                           ↓
┌─────────────────────────────────────────────────────┐
│ MemoryManager.prefetch_all()                        │
├─────────────────────────────────────────────────────┤
│ 1. hindsight.prefetch()                             │
│    → "Yesterday you mentioned JWT tokens expiring"  │
│                                                      │
│ 2. memory_graph.prefetch()                          │
│    → [trigger: "auth"] "Auth module: src/auth.ts"   │
│                                                      │
│ 3. memory_tencentdb.prefetch()                      │
│    → "User prefers OAuth2 over session cookies"     │
└─────────────────────────────────────────────────────┘
                           ↓
        Combined context injected into system prompt
                           ↓
                    LLM generates response
```

**No conflicts:** Each system contributes different types of information:
- hindsight → "what did we just say?"
- memory_graph → "what structured knowledge applies here?"
- memory_tencentdb → "what does the user prefer/believe/know?"

---

## Search Tools Comparison

Each system exposes different search capabilities:

| System | Tool Name | Search Method | Use When |
|--------|-----------|---------------|----------|
| hindsight | (auto-injected) | Recency | Recent conversation only |
| memory_graph | `memory_graph_search` | Graph traversal + text match | Searching structured knowledge |
| memory_tencentdb | `memory_tencentdb_memory_search` | Semantic embeddings | Finding user preferences/history |
| memory_tencentdb | `memory_tencentdb_conversation_search` | Full-text on L0 | Finding exact past dialogue |

**When to use each search tool:**

```python
# Example 1: User asks about a preference
"What's my favorite database?"
→ Use: memory_tencentdb_memory_search(query="favorite database")

# Example 2: User asks about a structured fact you defined
"What's the project structure?"
→ Use: memory_graph_search(query="project structure")

# Example 3: User asks "what did I say exactly?"
"What were my exact words when I described the bug?"
→ Use: memory_tencentdb_conversation_search(query="described the bug")

# Example 4: User asks about recent conversation
"Remind me what we discussed 5 minutes ago?"
→ No tool needed: hindsight auto-injects recent turns
```

---

## Performance Characteristics

| System | Latency | Storage Size | Memory Usage | Network Required |
|--------|---------|--------------|--------------|------------------|
| hindsight | <1ms | ~10 KB (20 turns) | <1 MB | No |
| memory_graph | <10ms | ~1-10 MB (1000s nodes) | <10 MB | No |
| memory_tencentdb | 50-200ms | ~100 MB-1 GB | <50 MB | No (Gateway is local) |

**Optimization tips:**
- hindsight: Reduce `window_size` if context is too long
- memory_graph: Use disclosure triggers to limit injected context
- memory_tencentdb: Increase `limit` in search calls if results are insufficient

---

## Migration & Interoperability

### Can I switch between systems?

**hindsight ↔ memory_graph:** No data migration needed (different purposes)

**hindsight → memory_tencentdb:**
- memory_tencentdb will automatically capture future conversations
- Past hindsight data is not retroactively imported
- Solution: Let memory_tencentdb run for a few days to build up L1-L3

**memory_graph → memory_tencentdb:**
- No automatic migration (different data models)
- memory_graph = explicit structure, memory_tencentdb = learned patterns
- Recommended: Keep both (they complement each other)

### Data export/backup

```bash
# Hermes session store / local SQLite stores, if used
sqlite3 ~/.hermes/state.db ".backup hermes_state_backup.db"

# Hindsight / Memory Graph PostgreSQL database
sudo -u postgres pg_dump hindsight > hindsight_memory_graph_backup.sql

# memory_tencentdb
# Follow the provider README; storage may be local SQLite/files or Tencent VectorDB.
tar -czf memory_tencentdb_backup.tar.gz ~/.memory-tencentdb/memory-tdai/ 2>/dev/null || true
```

---

## Troubleshooting

### hindsight not recalling recent turns?
```bash
# Check configured provider
hermes config get memory.provider

# Check Hindsight service and PostgreSQL-backed async queue
curl -fsS http://127.0.0.1:9177/health
sudo -u postgres psql -d hindsight -c "SELECT bank_id, COUNT(*) FROM memory_units GROUP BY bank_id ORDER BY count DESC;"
```

### memory_graph triggers not firing?
```bash
# Verify trigger patterns
hermes memory-graph list --show-triggers

# Test pattern matching
hermes memory-graph test-trigger "your test message"
```

### memory_tencentdb search returns empty?
```bash
# Check Gateway status
curl http://localhost:8420/health

# Check if data was captured
curl http://localhost:8420/api/v1/memories?user_id=default

# Verify LLM API key
echo $MEMORY_TENCENTDB_LLM_API_KEY
```

---

## Further Reading

- **hindsight**: See `hermes/agent/memory/hindsight.py`
- **memory_graph**: See `docs/MEMORY_ARCHITECTURE.md`
- **memory_tencentdb**: See `docs/SEARCH_AS_CODE.md`

---

## Summary

- Use **hindsight** for short-term conversation continuity (always recommended)
- Use **memory_graph** for hand-crafted structured knowledge (power users)
- Use **memory_tencentdb** for AI-powered long-term user learning (autonomous assistants)
- Use **all three** for maximum memory capabilities (they complement, not conflict)

The key insight: these systems are **complementary**, not **competing**:
- hindsight = immediate context
- memory_graph = explicit knowledge
- memory_tencentdb = learned patterns

Choose based on your needs, and don't be afraid to enable multiple systems — Hermes merges them intelligently.
