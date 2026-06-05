#!/bin/bash
# Hermes Memory Stack watchdog.
# Checks resident Memory OS dependencies and remediates common runtime failures.
# Focus: disk-full -> PostgreSQL down -> Hindsight/Memory Graph degraded.

set -u

LOG_PREFIX="[hermes-memory-watchdog]"
HOME_DIR="${HOME:-/root}"
MG_URL="${MEMORY_GRAPH_HEALTH_URL:-http://127.0.0.1:8900/health}"
HINDSIGHT_URL="${HINDSIGHT_HEALTH_URL:-http://127.0.0.1:9177/health}"
HERMES_DIR="${HERMES_DIR:-$HOME_DIR/.hermes/hermes-agent}"
HERMES_HOME_DIR="${HERMES_HOME_DIR:-$HOME_DIR/.hermes}"
DISK_WARN_PCT="${DISK_WARN_PCT:-90}"
DISK_REMEDIATE_PCT="${DISK_REMEDIATE_PCT:-98}"
RUN_CRUD_SMOKE="${RUN_CRUD_SMOKE:-1}"
DRY_RUN="${DRY_RUN:-0}"

log() { echo "$LOG_PREFIX $*"; }
is_root() { [ "$(id -u)" -eq 0 ]; }

_disk_pct() {
    df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}'
}

_run_or_echo() {
    if [ "$DRY_RUN" = "1" ]; then
        log "DRY_RUN $*"
    else
        "$@"
    fi
}

safe_cleanup() {
    local pct="$1"
    if [ "$pct" -lt "$DISK_REMEDIATE_PCT" ]; then
        return 0
    fi
    log "disk usage ${pct}% >= ${DISK_REMEDIATE_PCT}%; running conservative cleanup"

    # Reproducible browser/runtime caches.
    for d in "$HOME_DIR/.cache/camoufox" "$HOME_DIR/.cache/ms-playwright" "$HOME_DIR/.cache/puppeteer"; do
        if [ -d "$d" ]; then
            log "cleanup cache: $d"
            _run_or_echo rm -rf "$d"
        fi
    done

    # Package caches only; not project node_modules.
    if command -v apt-get >/dev/null 2>&1 && is_root; then
        log "apt-get clean"
        _run_or_echo apt-get clean
    fi
    if [ -d "$HOME_DIR/.npm" ]; then
        log "cleanup npm cache: $HOME_DIR/.npm"
        _run_or_echo rm -rf "$HOME_DIR/.npm/_cacache" "$HOME_DIR/.npm/_logs"
    fi

    # Old direct-child patch/smoke workdirs. These are clean clones or generated
    # verification directories, not source-of-truth sessions or project DBs.
    local tasks="$HERMES_HOME_DIR/tasks"
    if [ -d "$tasks" ]; then
        find "$tasks" -mindepth 1 -maxdepth 1 -type d \( \
            -name 'memory-write-autowrite-smoke-*' -o \
            -name 'image-edit-clean-smoke-*' -o \
            -name 'hermes-v*-patch-check-*' -o \
            -name 'patch-audit-*' -o \
            -name 'hermes-patch-audit-*' -o \
            -name 'memory-os-sync-check-*' -o \
            -name 'hermes-install-test-*' -o \
            -name 'hermes-clean-*' -o \
            -name 'patch-verify-*' -o \
            -name 'telegram-context-patch-*' -o \
            -name 'telegram-context-combined-*' \
        \) -mtime +1 -print | while IFS= read -r d; do
            log "cleanup reproducible task dir: $d"
            _run_or_echo rm -rf "$d"
        done
    fi

    # Journal vacuum is safe and bounded.
    if command -v journalctl >/dev/null 2>&1 && is_root; then
        log "journalctl vacuum-size=100M"
        _run_or_echo journalctl --vacuum-size=100M >/dev/null 2>&1 || true
    fi

    log "disk after cleanup: $(df -h / | awk 'NR==2 {print $5 " used, " $4 " free"}')"
}

restart_system_service() {
    local svc="$1"
    if command -v systemctl >/dev/null 2>&1; then
        log "restarting $svc"
        systemctl restart "$svc" || log "restart failed: $svc"
    fi
}

check_http() {
    local url="$1"
    curl -fsS -m 5 "$url" >/dev/null 2>&1
}

check_postgres() {
    if command -v pg_lsclusters >/dev/null 2>&1; then
        pg_lsclusters | awk '$1=="15" && $2=="main" && $4=="online" {found=1} END{exit found?0:1}' || return 1
    fi
    if command -v pg_isready >/dev/null 2>&1; then
        pg_isready -q -h 127.0.0.1 -p 5432 -U postgres || return 1
    fi
    return 0
}

memory_graph_crud_smoke() {
    [ "$RUN_CRUD_SMOKE" = "1" ] || return 0
    [ -x "$HERMES_DIR/venv/bin/python" ] || { log "Hermes venv missing; skip Memory Graph CRUD smoke"; return 1; }
    cd "$HERMES_DIR" || return 1
    "$HERMES_DIR/venv/bin/python" - <<'PY'
import json, time, sys
from tools import memory_graph_tool as m
stamp = str(int(time.time()))
title = "watchdog-smoke-" + stamp
content = "Temporary Memory Graph watchdog smoke node " + stamp
parent = "core://系统架构"
created = json.loads(m._create({"parent_uri": parent, "title": title, "content": content, "priority": 9, "domain": "core"}))
if created.get("error"):
    raise SystemExit("create failed: " + json.dumps(created, ensure_ascii=False))
uri = created.get("uri") or ("core://系统架构/" + title)
search = json.loads(m._search({"query": title, "limit": 5, "domain": "core"}))
if not any(title in (r.get("path","") + r.get("snippet","") + r.get("name", "")) for r in search.get("results", [])):
    raise SystemExit("search miss after create: " + json.dumps(search, ensure_ascii=False)[:500])
deleted = json.loads(m._delete({"uri": uri, "domain": "core"}))
if not deleted.get("deleted"):
    raise SystemExit("delete failed: " + json.dumps(deleted, ensure_ascii=False))
search2 = json.loads(m._search({"query": title, "limit": 5, "domain": "core"}))
if any(title in (r.get("path","") + r.get("snippet","") + r.get("name", "")) for r in search2.get("results", [])):
    raise SystemExit("search hit after delete: " + json.dumps(search2, ensure_ascii=False)[:500])
print("MG_CRUD_OK", uri)
PY
}

failed=0
pct="$(_disk_pct 2>/dev/null || echo 100)"
if [ "$pct" -ge "$DISK_WARN_PCT" ]; then
    log "disk warning: ${pct}% used"
fi
safe_cleanup "$pct"

if ! check_postgres; then
    log "PostgreSQL unhealthy"
    if is_root; then
        restart_system_service postgresql@15-main.service
        sleep 3
    else
        log "not root; cannot restart PostgreSQL"
    fi
fi
if ! check_postgres; then
    log "PostgreSQL still unhealthy after remediation"
    failed=1
fi

if ! check_http "$HINDSIGHT_URL"; then
    log "Hindsight unhealthy: $HINDSIGHT_URL"
    if is_root; then
        restart_system_service hindsight.service
        sleep 3
    fi
fi
if ! check_http "$HINDSIGHT_URL"; then
    log "Hindsight still unhealthy"
    failed=1
fi

if ! check_http "$MG_URL"; then
    log "Memory Graph HTTP unhealthy: $MG_URL"
    if is_root; then
        restart_system_service hermes-memory-graph.service
        sleep 3
    else
        systemctl --user restart hermes-memory-graph.service || true
        sleep 3
    fi
fi
if ! check_http "$MG_URL"; then
    log "Memory Graph HTTP still unhealthy"
    failed=1
fi

if [ "$failed" -eq 0 ]; then
    if memory_graph_crud_smoke; then
        log "Memory Graph CRUD smoke passed"
    else
        log "Memory Graph CRUD smoke failed"
        failed=1
    fi
fi

if [ "$failed" -eq 0 ]; then
    log "healthy"
fi
exit "$failed"
