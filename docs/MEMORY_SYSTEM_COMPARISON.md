# Memory System Comparison Guide

## Overview

Hermes Agent supports three complementary memory systems, each designed for different use cases and memory architectures. This guide helps you choose the right system for your needs.

---

## Quick Comparison Table

| Feature | **hindsight** | **memory_graph** | **memory_tencentdb** |
|---------|---------------|------------------|---------------------|
| **Storage Type** | SQLite (local) | SQLite (local) | Local files (L0-L3) via Gateway |
| **Memory Structure** | Raw conversation turns | Structured knowledge graph | Four-layer hierarchy (conversation → extraction → scenes → persona) |
| **Processing** | None (raw storage) | Manual structuring | AI-powered automatic extraction |
| **Best For** | Recent conversation context | Precise, hand-crafted knowledge | Long-term user persona & preferences |
| **Setup Complexity** | Zero config | Low (SQLite only) | Medium (requires Node.js Gateway) |
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
memory_providers:
  hindsight:
    enabled: true
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

**Configuration:**
```yaml
memory_providers:
  memory_graph:
    enabled: true
    db_path: ~/.hermes/memory_graph.db
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
# In hermes config
memory_providers:
  memory_tencentdb:
    enabled: true
```

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

### Configuration 1: Minimal (Zero Setup)
**Goal:** Basic conversation continuity within a session

```yaml
memory_providers:
  hindsight:
    enabled: true
    window_size: 20
```

**Use case:** Quick prototyping, demos, short tasks

---

### Configuration 2: Power User (Manual Control)
**Goal:** Precise knowledge management + recent context

```yaml
memory_providers:
  hindsight:
    enabled: true
    window_size: 20
  memory_graph:
    enabled: true
    db_path: ~/.hermes/memory_graph.db
```

**Use case:**
- You maintain a "second brain" of facts, preferences, and worldview
- You want to define exact trigger rules for context injection
- You're willing to manually curate your memory graph

---

### Configuration 3: Autonomous Assistant (AI-Powered)
**Goal:** Agent learns about you automatically over time

```yaml
memory_providers:
  hindsight:
    enabled: true
    window_size: 20
  memory_tencentdb:
    enabled: true
```

**Use case:**
- Long-term personal assistant
- Cross-session memory persistence
- You want the agent to remember preferences without manual input
- You have Node.js and can run the Gateway

---

### Configuration 4: Complete (All Systems)
**Goal:** Hybrid approach with all memory types

```yaml
memory_providers:
  hindsight:
    enabled: true
    window_size: 20
  memory_graph:
    enabled: true
  memory_tencentdb:
    enabled: true
```

**Use case:**
- **hindsight** handles immediate context ("what we just discussed")
- **memory_graph** stores your hand-crafted worldview and rules
- **memory_tencentdb** learns your preferences and patterns automatically

**How they work together:**
1. **hindsight** provides recent conversation context (last 20 turns)
2. **memory_graph** injects relevant structured knowledge when triggers match
3. **memory_tencentdb** adds long-term user profile and preferences
4. All three are merged into a single context block by `MemoryManager`

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
# hindsight
sqlite3 ~/.hermes/hindsight.db ".dump" > hindsight_backup.sql

# memory_graph
sqlite3 ~/.hermes/memory_graph.db ".dump" > memory_graph_backup.sql

# memory_tencentdb
tar -czf memory_tencentdb_backup.tar.gz ~/.memory-tencentdb/memory-tdai/
```

---

## Troubleshooting

### hindsight not recalling recent turns?
```bash
# Check if enabled
hermes config get memory_providers.hindsight.enabled

# Check database
sqlite3 ~/.hermes/hindsight.db "SELECT COUNT(*) FROM conversations;"
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
- **memory_graph**: See `/root/hermes-patches/docs/MEMORY_ARCHITECTURE.md`
- **memory_tencentdb**: See `/root/hermes-patches/docs/SEARCH_AS_CODE.md`

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
