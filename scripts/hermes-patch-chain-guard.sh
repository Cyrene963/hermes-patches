#!/usr/bin/env bash
# Hermes patch-chain guard: verify that the GitHub/local patch tree, installed Hermes code,
# Memory Graph service, and dashboard API are all present and mutually usable.
set -euo pipefail

HERMES_DIR="${HERMES_DIR:-$HOME/.hermes/hermes-agent}"
PATCHES_DIR="${PATCHES_DIR:-$HOME/.hermes/patches}"
MG_URL="${MG_URL:-http://127.0.0.1:8233}"
MG_PUBLIC_URL="${MG_PUBLIC_URL:-}"
MG_CORE_URL="${MG_CORE_URL:-http://127.0.0.1:8900}"
DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:9119}"
FAIL=0

ok() { printf '✅ %s\n' "$*"; }
warn() { printf '⚠️ %s\n' "$*"; }
fail() { printf '❌ %s\n' "$*"; FAIL=1; }

require_file() {
  local path="$1" label="$2"
  if [ -f "$path" ]; then ok "$label: $path"; else fail "$label missing: $path"; fi
}
require_dir() {
  local path="$1" label="$2"
  if [ -d "$path" ]; then ok "$label: $path"; else fail "$label missing: $path"; fi
}

require_dir "$HERMES_DIR" "Hermes worktree"
require_dir "$PATCHES_DIR" "Patch worktree"
require_file "$PATCHES_DIR/install.sh" "Patch installer"
require_file "$HERMES_DIR/tools/memory_graph_tool.py" "Installed Memory Graph tool"
require_file "$HERMES_DIR/agent/memory_metacognition.py" "Installed metacognition module"
require_file "$HERMES_DIR/agent/memory_write_pipeline.py" "Installed write pipeline module"
require_file "$HERMES_DIR/agent/shadow_write_logger.py" "Installed shadow logger module"
require_file "$HERMES_DIR/toolsets.py" "Installed toolsets.py"
require_dir "$PATCHES_DIR/hermes_cli/web_dist" "Patch dashboard web_dist bundle"
require_dir "$HERMES_DIR/hermes_cli/web_dist" "Installed dashboard web_dist bundle"

if [ -d "$PATCHES_DIR/hermes_cli/web_dist/assets" ] && [ -d "$HERMES_DIR/hermes_cli/web_dist/assets" ]; then
  patch_assets=$(find "$PATCHES_DIR/hermes_cli/web_dist/assets" -maxdepth 1 -type f \( -name 'index-*.js' -o -name 'index-*.css' \) -printf '%f\n' | sort | tr '\n' ' ')
  runtime_assets=$(find "$HERMES_DIR/hermes_cli/web_dist/assets" -maxdepth 1 -type f \( -name 'index-*.js' -o -name 'index-*.css' \) -printf '%f\n' | sort | tr '\n' ' ')
  if [ -n "$patch_assets" ] && [ "$patch_assets" = "$runtime_assets" ]; then
    ok "Dashboard web_dist assets match patch overlay: $runtime_assets"
  else
    fail "Dashboard web_dist asset mismatch patch=[$patch_assets] runtime=[$runtime_assets]"
  fi
fi

if [ -f "$HERMES_DIR/toolsets.py" ]; then
  grep -q '"memory_graph"' "$HERMES_DIR/toolsets.py" && ok "memory_graph toolset registered" || fail "memory_graph toolset missing from toolsets.py"
  grep -q 'memory_graph_search' "$HERMES_DIR/toolsets.py" && ok "memory_graph tools included in core/toolsets" || fail "memory_graph_search missing from toolsets.py"
fi

if [ -d "$PATCHES_DIR/.git" ]; then
  git -C "$PATCHES_DIR" remote -v | sed 's/^/patch remote: /'
  git -C "$PATCHES_DIR" status --short | sed 's/^/patch status: /' || true
  ok "Patch repo git metadata readable"
else
  warn "Patch worktree has no .git metadata; cannot compare with GitHub remote"
fi

if [ -d "$HERMES_DIR/.git" ]; then
  git -C "$HERMES_DIR" rev-parse --short HEAD | sed 's/^/hermes head: /'
  git -C "$HERMES_DIR" status --short | sed 's/^/hermes status: /' || true
  ok "Hermes repo git metadata readable"
else
  warn "Hermes worktree has no .git metadata"
fi

if command -v curl >/dev/null 2>&1; then
  # Resident memory stack health: this catches the real failure mode where
  # Memory Graph HTTP or WebUI can look alive while PostgreSQL/Hindsight/CRUD is broken.
  if command -v pg_lsclusters >/dev/null 2>&1; then
    if pg_lsclusters | awk '$1=="15" && $2=="main" && $4=="online" {found=1} END{exit found?0:1}'; then
      ok "PostgreSQL cluster 15/main online"
    else
      fail "PostgreSQL cluster 15/main is not online"
    fi
  fi
  if curl -fsS -m 5 "http://127.0.0.1:9177/health" >/tmp/hermes-hindsight-health.json 2>/tmp/hermes-hindsight-health.err; then
    if grep -q '"database".*"connected"' /tmp/hermes-hindsight-health.json; then
      ok "Hindsight health database connected: $(tr -d '\n' </tmp/hermes-hindsight-health.json)"
    else
      fail "Hindsight health did not report database connected: $(tr -d '\n' </tmp/hermes-hindsight-health.json)"
    fi
  else
    fail "Hindsight health failed: $(tr -d '\n' </tmp/hermes-hindsight-health.err 2>/dev/null || true)"
  fi
  if curl -fsS -m 5 "$MG_CORE_URL/health" >/tmp/hermes-mg-core-health.json 2>/tmp/hermes-mg-core-health.err; then
    ok "Memory Graph core health reachable: $(tr -d '\n' </tmp/hermes-mg-core-health.json)"
  else
    fail "Memory Graph core health failed at $MG_CORE_URL/health: $(tr -d '\n' </tmp/hermes-mg-core-health.err 2>/dev/null || true)"
  fi

  if curl -fsS -m 5 "$MG_URL/health" >/tmp/hermes-mg-health.json 2>/tmp/hermes-mg-health.err; then
    ok "Memory Graph health reachable: $(tr -d '\n' </tmp/hermes-mg-health.json)"
  else
    fail "Memory Graph health failed at $MG_URL/health: $(tr -d '\n' </tmp/hermes-mg-health.err 2>/dev/null || true)"
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$MG_URL" "$MG_PUBLIC_URL" <<'PY' || exit_code=$?
import json, sys, urllib.request
bases = []
local = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else ''
public = sys.argv[2].rstrip('/') if len(sys.argv) > 2 else ''
if local:
    bases.append(('local', local))
if public:
    bases.append(('public', public))
for label, base in bases:
    if not (base.startswith('http://') or base.startswith('https://')):
        raise SystemExit(f'{label} Memory Graph WebUI base URL is not absolute: {base!r}')
    req = urllib.request.Request(base + '/openapi.json', headers={'User-Agent': 'Hermes-Patch-Guard/1.0'})
    data = json.load(urllib.request.urlopen(req, timeout=15))
    paths = set(data.get('paths', {}))
    required = {'/api/browse/node', '/api/browse/search', '/api/settings', '/api/review'}
    missing = sorted(p for p in required if p not in paths)
    if missing:
        raise SystemExit(f'{label} Memory Graph WebUI missing endpoints: {missing}')
if not bases:
    raise SystemExit('no Memory Graph WebUI base URL configured')
print('MG_WEBUI_OK standalone browse/settings/review API surface reachable')
PY
    rc=${exit_code:-0}
    unset exit_code
    if [ "$rc" -eq 0 ]; then ok "Standalone Memory Graph WebUI API surface reachable"; else fail "Memory Graph WebUI API surface probe failed"; fi
  fi

  # Dashboard protected APIs require the ephemeral token injected into index.html.
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$DASHBOARD_URL" <<'PY' || exit_code=$?
import re, sys, urllib.request, urllib.error
base = sys.argv[1].rstrip('/')
try:
    req = urllib.request.Request(base + '/', headers={'User-Agent': 'Hermes-Patch-Guard/1.0'})
    html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8', 'replace')
    m = re.search(r'__HERMES_SESSION_TOKEN__="([^"]+)"', html)
    if not m:
        print('DASHBOARD_FAIL no session token in index.html')
        sys.exit(2)
    token = m.group(1)
    for ep in ['/api/model/info', '/api/analytics/models?days=30', '/api/model/auxiliary', '/api/sessions?limit=1&offset=0']:
        req = urllib.request.Request(base + ep, headers={'X-Hermes-Session-Token': token, 'User-Agent': 'Hermes-Patch-Guard/1.0'})
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status != 200:
                print(f'DASHBOARD_FAIL {ep} status={r.status}')
                sys.exit(3)
    print('DASHBOARD_OK protected APIs reachable')
except Exception as e:
    print('DASHBOARD_FAIL', type(e).__name__, str(e))
    sys.exit(4)
PY
    rc=${exit_code:-0}
    unset exit_code
    if [ "$rc" -eq 0 ]; then ok "Dashboard protected APIs reachable"; else fail "Dashboard protected API probe failed"; fi
  fi
fi

# Aegis-lite completion gate: do not declare completion from a restart/import alone.
# Require baseline evidence, live health, CRUD proof, and guarded final status.
if command -v df >/dev/null 2>&1; then
  disk_pct=$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')
  if [ -n "${disk_pct:-}" ] && [ "$disk_pct" -lt 95 ]; then
    ok "Aegis-lite baseline: root disk below death zone (${disk_pct}%)"
  else
    fail "Aegis-lite baseline: root disk still at/above 95% (${disk_pct:-unknown}%)"
  fi
fi

if command -v curl >/dev/null 2>&1; then
  if curl -fsS -m 5 "http://127.0.0.1:8642/health" >/tmp/hermes-api-health.json 2>/tmp/hermes-api-health.err; then
    ok "Aegis-lite live path: API server health reachable"
  else
    fail "Aegis-lite live path: API server health failed: $(tr -d '\n' </tmp/hermes-api-health.err 2>/dev/null || true)"
  fi
fi

# AST structural audit: catches high-risk code shapes that plain grep misses.
if [ -x "$HOME/.hermes/scripts/hermes-ast-grep-audit.sh" ]; then
  if AST_GREP_FAIL_ON_WARNINGS="${AST_GREP_FAIL_ON_WARNINGS:-0}" "$HOME/.hermes/scripts/hermes-ast-grep-audit.sh"; then
    ok "ast-grep structural audit completed"
  else
    fail "ast-grep structural audit failed"
  fi
elif [ -f "$PATCHES_DIR/scripts/hermes-ast-grep-audit.sh" ]; then
  if AST_GREP_FAIL_ON_WARNINGS="${AST_GREP_FAIL_ON_WARNINGS:-0}" bash "$PATCHES_DIR/scripts/hermes-ast-grep-audit.sh"; then
    ok "ast-grep structural audit completed"
  else
    fail "ast-grep structural audit failed"
  fi
else
  warn "ast-grep structural audit script not installed; skipped"
fi

# Python import smoke: catches copied files that exist but fail at import time.
if [ -x "$HERMES_DIR/venv/bin/python" ]; then
  "$HERMES_DIR/venv/bin/python" - <<'PY' || exit_code=$?
import importlib
mods = [
    'tools.memory_graph_tool',
    'agent.memory_metacognition',
    'agent.memory_write_pipeline',
    'agent.shadow_write_logger',
    'agent.hindsight_reranker',
]
for m in mods:
    importlib.import_module(m)
print('IMPORT_OK', ','.join(mods))
PY
  rc=${exit_code:-0}
  unset exit_code
  if [ "$rc" -eq 0 ]; then ok "Patched Python modules import"; else fail "Patched Python module import smoke failed"; fi

  "$HERMES_DIR/venv/bin/python" - <<'PY' || exit_code=$?
import json, time
from tools import memory_graph_tool as m
stamp = str(int(time.time()))
title = 'guard-smoke-' + stamp
created = json.loads(m._create({'parent_uri':'core://系统架构','title':title,'content':'Patch-chain guard temporary Memory Graph smoke '+stamp,'priority':9,'domain':'core'}))
if created.get('error'):
    raise SystemExit('create failed: ' + json.dumps(created, ensure_ascii=False))
uri = created.get('uri') or 'core://系统架构/' + title
search = json.loads(m._search({'query':title,'limit':5,'domain':'core'}))
if not any(title in (r.get('path','') + r.get('snippet','') + r.get('name','')) for r in search.get('results', [])):
    raise SystemExit('search miss after create')
deleted = json.loads(m._delete({'uri':uri,'domain':'core'}))
if not deleted.get('deleted'):
    raise SystemExit('delete failed: ' + json.dumps(deleted, ensure_ascii=False))
search2 = json.loads(m._search({'query':title,'limit':5,'domain':'core'}))
if any(title in (r.get('path','') + r.get('snippet','') + r.get('name','')) for r in search2.get('results', [])):
    raise SystemExit('search hit after delete')
print('MG_CRUD_OK', uri)
PY
  rc=${exit_code:-0}
  unset exit_code
  if [ "$rc" -eq 0 ]; then ok "Memory Graph CRUD smoke passed"; else fail "Memory Graph CRUD smoke failed"; fi
else
  warn "Hermes venv python not executable; skipped import smoke"
fi

if [ "$FAIL" -ne 0 ]; then
  echo ""
  fail "Hermes patch-chain guard FAILED"
  exit 1
fi

echo ""
ok "Hermes patch-chain guard passed"
