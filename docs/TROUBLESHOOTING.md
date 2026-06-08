# Troubleshooting Guide

Common issues and solutions for Hermes Agent community patches.

---

## Memory System Issues

### Memory Graph Issues

#### Issue: Search is slow or timing out

**Symptoms:**
- Memory graph searches take more than 1 second
- PostgreSQL connection/index errors
- High CPU usage during searches

**Solutions:**

1. **Verify the Memory Graph service and database are healthy**:
   ```bash
   curl -fsS http://127.0.0.1:8900/health
   pg_isready -h 127.0.0.1 -p 5432
   ```

2. **Check whether the PostgreSQL search index exists**:
   ```bash
   sudo -u postgres psql -d hindsight -c "\d+ mg_search_documents"
   ```
   You should see the `search_vector` column and a GIN index such as `ix_mg_search_vector_gin`.

3. **Run the PostgreSQL migration if the index is missing**:
   ```bash
   cd ~/.hermes/hermes-agent
   sudo -u postgres psql -d hindsight -f agent/memory_graph/db/init.sql
   ```

4. **Vacuum/analyze PostgreSQL tables after large migrations**:
   ```bash
   sudo -u postgres psql -d hindsight -c "VACUUM ANALYZE mg_search_documents;"
   ```

---

#### Issue: Disclosure rules not triggering

**Symptoms:**
- Memories not automatically injected when expected
- Trigger patterns not matching user messages

**Solutions:**

1. **Check disclosure metadata in PostgreSQL**:
   ```bash
   sudo -u postgres psql -d hindsight -c \
     "SELECT path, disclosure FROM mg_search_documents WHERE disclosure IS NOT NULL LIMIT 20;"
   ```

2. **Test pattern matching**:
   Create a test script to validate regex patterns:
   ```python
   import re
   pattern = r"hermes|agent|memory"
   test_message = "Let's work on the hermes agent"
   if re.search(pattern, test_message, re.IGNORECASE):
       print("Match!")
   ```

3. **Enable debug logging**:
   ```bash
   export HERMES_DEBUG=true
   hermes chat
   ```
   Check logs for "Disclosure matched:" messages.

---

#### Issue: Agent forgets things / doesn't recall memories

**Symptoms:**
- Previously stored facts are not recalled
- Agent asks questions about information already provided

**Solutions:**

1. **Verify Memory Graph tools and service are available**:
   ```bash
   curl -fsS http://127.0.0.1:8900/health
   cd ~/.hermes/hermes-agent
   venv/bin/python - <<'PY'
from toolsets import TOOLSETS, _HERMES_CORE_TOOLS
print('memory_graph tools:', len(TOOLSETS.get('memory_graph', {}).get('tools', [])))
print('search in core:', 'memory_graph_search' in _HERMES_CORE_TOOLS)
PY
   ```

2. **Check PostgreSQL has Memory Graph data**:
   ```bash
   sudo -u postgres psql -d hindsight -c "SELECT COUNT(*) FROM mg_paths;"
   ```
   If count is 0, Memory Graph has not stored any nodes.

3. **Verify manifest/system-prompt inventory is present**:
   ```bash
   test -s ~/.hermes/memories/MEMORY_MANIFEST.md && head -40 ~/.hermes/memories/MEMORY_MANIFEST.md
   ```

4. **Manually search through the deployed tool path**:
   ```bash
   cd ~/.hermes/hermes-agent
   venv/bin/python - <<'PY'
from tools import memory_graph_tool as m
print(m._search({'query': 'Hermes Agent', 'limit': 5, 'domain': 'core'}))
PY
   ```

---

### memory_tencentdb Issues

#### Issue: Gateway won't start

**Symptoms:**
- Error: "Gateway health check failed after 30s"
- Error: "Connection refused to localhost:8420"
- Gateway process not running

**Solutions:**

1. **Check Node.js is installed**:
   ```bash
   node --version
   ```
   Required: Node.js 16+ or 18+.

2. **Check pnpm is installed**:
   ```bash
   pnpm --version
   ```
   Install if missing: `npm install -g pnpm`

3. **Verify LLM API key is set**:
   ```bash
   echo $MEMORY_TENCENTDB_LLM_API_KEY
   ```
   If empty, set it:
   ```bash
   export MEMORY_TENCENTDB_LLM_API_KEY="your-api-key"
   ```

4. **Check port 8420 is available**:
   ```bash
   lsof -i :8420
   ```
   If port is in use, change it:
   ```bash
   export MEMORY_TENCENTDB_GATEWAY_PORT=8421
   ```

5. **Check Gateway logs**:
   ```bash
   # Default log location
   tail -f ~/.memory-tencentdb/logs/gateway.log
   
   # Or custom location
   tail -f $MEMORY_TENCENTDB_LOG_DIR/gateway.log
   ```

6. **Manually start Gateway for debugging**:
   ```bash
   cd ~/.hermes/hermes-agent/plugins/memory/memory_tencentdb
   node src/gateway/server.js
   ```
   Check for error messages in console output.

---

#### Issue: Gateway starts but searches return empty results

**Symptoms:**
- Gateway health check passes
- Searches return `[]` or "No results found"
- No errors in logs

**Solutions:**

1. **Verify data was captured**:
   ```bash
   curl http://localhost:8420/api/v1/memories?user_id=default | jq
   ```
   Should return JSON with memories.

2. **Check if LLM extraction is working**:
   Look for extraction logs:
   ```bash
   grep "L1 extraction" ~/.memory-tencentdb/logs/gateway.log
   ```

3. **Verify LLM credentials**:
   Test API manually:
   ```bash
   curl -X POST $MEMORY_TENCENTDB_LLM_BASE_URL/chat/completions \
     -H "Authorization: Bearer $MEMORY_TENCENTDB_LLM_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"model":"gpt-4o","messages":[{"role":"user","content":"test"}]}'
   ```

4. **Wait for extraction to complete**:
   L0→L1 extraction happens asynchronously. Wait 10-30 seconds after sending messages, then search again.

---

#### Issue: Gateway crashes frequently

**Symptoms:**
- Gateway exits unexpectedly
- Error: "ECONNRESET" or "EPIPE"
- Hermes Agent logs show repeated reconnection attempts

**Solutions:**

1. **Check system resources**:
   ```bash
   free -h  # Check memory
   df -h    # Check disk space
   ```
   Gateway needs at least 500MB RAM and 1GB disk space.

2. **Check for unhandled promise rejections**:
   ```bash
   grep "UnhandledPromiseRejection" ~/.memory-tencentdb/logs/gateway.log
   ```

3. **Increase Node.js memory limit**:
   ```bash
   export NODE_OPTIONS="--max-old-space-size=2048"
   ```

4. **Update dependencies**:
   ```bash
   cd ~/.hermes/hermes-agent/plugins/memory/memory_tencentdb
   pnpm install
   ```

---

### Auto Memory Detection Issues

#### Issue: HERMES_AUTO_MEMORY not working

**Symptoms:**
- Memories not auto-stored even with `HERMES_AUTO_MEMORY=true`
- Agent always asks "Should I remember this?"

**Solutions:**

1. **Verify environment variable is set**:
   ```bash
   echo $HERMES_AUTO_MEMORY
   ```
   Should output `true`.

2. **Check if auto_store_heuristic.py is installed**:
   ```bash
   ls -la ~/.hermes/hermes-agent/agent/auto_store_heuristic.py
   ```

3. **Check if memory_auto_hooks.py is installed**:
   ```bash
   ls -la ~/.hermes/hermes-agent/agent/memory_auto_hooks.py
   ```

4. **Test detection directly**:
   ```python
   from agent.auto_store_heuristic import should_auto_store
   result = should_auto_store("Remember: I prefer dark mode")
   print(f"Auto-store: {result['should_store']}, Confidence: {result['confidence']}")
   ```

5. **Check confidence threshold**:
   Default threshold is 0.50. Lower it for more aggressive auto-storing:
   ```python
   # In agent/memory_auto_hooks.py
   CONFIDENCE_THRESHOLD = 0.40  # Lower = more sensitive
   ```

---

## Installation Issues

### Issue: Patches fail to apply

**Symptoms:**
- Error: "patch does not apply"
- Error: "file to patch not found"
- Conflicts during `git apply`

**Solutions:**

1. **Check Hermes version**:
   ```bash
   cd ~/.hermes/hermes-agent
   git log --oneline -1
   ```
   Patches are tested on latest `main` branch.

2. **Update Hermes first**:
   ```bash
   hermes update
   ```

3. **Reset to clean state**:
   ```bash
   cd ~/.hermes/hermes-agent
   git reset --hard origin/main
   bash ~/hermes-patches/install.sh
   ```

4. **Check for merge conflicts**:
   ```bash
   git status
   ```
   Look for "both modified" files.

---

### Issue: install.sh hangs or fails

**Symptoms:**
- Script stops responding
- Error: "No such file or directory"
- Permission denied errors

**Solutions:**

1. **Check Git is available**:
   ```bash
   git --version
   ```

2. **Check network connectivity** (if downloading patches):
   ```bash
   curl -I https://github.com/Cyrene963/hermes-patches
   ```

3. **Run with verbose output**:
   ```bash
   bash -x ~/hermes-patches/install.sh
   ```

4. **Check permissions**:
   ```bash
   ls -ld ~/.hermes/hermes-agent
   ```
   You should own the directory.

---

## Performance Issues

### Issue: Agent is slow to respond

**Symptoms:**
- Long delays before first response
- Timeouts during context loading
- High memory usage

**Solutions:**

1. **Check provider-specific window size in the active provider config**:
   ```yaml
   # Canonical single-provider form in ~/.hermes/config.yaml
   memory:
     provider: hindsight
     hindsight:
       window_size: 10  # Reduce from 20 or 50
   ```
   Older docs may show `memory_providers:`. Treat that as legacy provider-specific configuration unless the provider README explicitly says otherwise.

2. **Disable unused memory providers by selecting only the provider you want**:
   ```yaml
   memory:
     provider: hindsight
   ```
   Do not enable multiple long-term memory providers unless you have verified their namespaces, banks, and prompt injection behavior.

3. **Check database sizes**:
   ```bash
   du -h ~/.hermes/state.db ~/.hindsight 2>/dev/null || true
   sudo -u postgres psql -d hindsight -c "SELECT pg_size_pretty(pg_database_size('hindsight'));"
   ```

4. **Vacuum/analyze databases**:
   ```bash
   # Hermes session SQLite store
   sqlite3 ~/.hermes/state.db "VACUUM;"
   # Memory Graph / Hindsight PostgreSQL database
   sudo -u postgres psql -d hindsight -c "VACUUM ANALYZE;"
   ```

---

## Configuration Issues

### Issue: Config changes not taking effect

**Symptoms:**
- Changed settings in `config.yaml` but behavior unchanged
- Agent uses old provider after switching

**Solutions:**

1. **Restart Gateway**:
   ```bash
   systemctl --user restart hermes-gateway
   # Or kill and let supervisor restart
   pkill -f "hermes.*gateway"
   ```

2. **Check config file syntax**:
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('~/.hermes/config.yaml'))"
   ```

3. **Check for environment variable overrides**:
   ```bash
   env | grep HERMES
   env | grep MEMORY
   ```
   Environment variables override config file settings.

4. **Verify config file location**:
   ```bash
   ls -la ~/.hermes/config.yaml
   ```

---

## Security Issues

### Issue: API keys visible in logs or debug output

**Symptoms:**
- Full API keys appear in `hermes.log`
- Keys visible in error messages

**Solutions:**

1. **Enable secret redaction**:
   ```bash
   export HERMES_SECRET_REDACTION=true
   ```

2. **Check redaction is working**:
   ```bash
   grep "sk-" ~/.hermes/logs/hermes.log
   ```
   Should show `sk-...****abcd` (masked), not full key.

3. **Rotate exposed keys immediately**:
   If keys were exposed, revoke and generate new ones.

---

## Getting More Help

### Enable Debug Logging

```bash
export HERMES_DEBUG=true
export MEMORY_TENCENTDB_LOG_DIR=~/.hermes/logs
hermes chat
```

Check logs:
```bash
tail -f ~/.hermes/logs/hermes.log
tail -f ~/.hermes/logs/gateway.log
```

### Check System Status

```bash
# Hermes version
hermes --version

# Check running processes
ps aux | grep hermes

# Check memory usage
free -h

# Check disk space
df -h ~/.hermes
```

### Report Issues

1. **Search existing issues**: https://github.com/Cyrene963/hermes-patches/issues
2. **Include debug logs** (with secrets redacted)
3. **Provide system info**: OS, Python version, Node.js version
4. **List steps to reproduce**

---

## Quick Diagnostics Script

Save this as `hermes-diag.sh` and run with `bash hermes-diag.sh`:

```bash
#!/bin/bash
echo "=== Hermes Diagnostics ==="
echo ""
echo "Hermes Path: $(which hermes)"
echo "Python: $(python3 --version)"
echo "Node.js: $(node --version 2>/dev/null || echo 'Not installed')"
echo ""
echo "=== Memory Providers ==="
grep -A 10 "memory:" ~/.hermes/config.yaml
echo ""
echo "=== Environment Variables ==="
env | grep -E "HERMES|MEMORY" | sed 's/\(API_KEY=\).*/\1***REDACTED***/'
echo ""
echo "=== Database Sizes ==="
du -h ~/.hermes/*.db 2>/dev/null || echo "No databases found"
echo ""
echo "=== Gateway Status ==="
curl -s http://localhost:8420/health 2>&1 | head -1
echo ""
echo "=== Recent Errors ==="
tail -20 ~/.hermes/logs/hermes.log 2>/dev/null | grep -i error || echo "No errors in logs"
```

---

## Related Documentation

- [MEMORY_SYSTEM_COMPARISON.md](MEMORY_SYSTEM_COMPARISON.md) — Choosing the right memory system
- [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md) — Deep dive into memory_graph
- [SEARCH_AS_CODE.md](SEARCH_AS_CODE.md) — memory_tencentdb technical details
- [README.md](../README.md) — Installation and overview
