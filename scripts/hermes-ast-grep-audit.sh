#!/usr/bin/env bash
# Structural audit for Hermes patch/runtime trees using ast-grep.
# This guard is intentionally lightweight: it catches high-risk structural code
# patterns that grep misses, without replacing tests or semantic review.
set -euo pipefail

HERMES_DIR="${HERMES_DIR:-$HOME/.hermes/hermes-agent}"
PATCHES_DIR="${PATCHES_DIR:-$HOME/.hermes/patches}"
RULES_DIR="${AST_GREP_RULES_DIR:-$PATCHES_DIR/ast-grep-rules}"
if [ ! -d "$RULES_DIR" ] && [ -d "$HOME/.hermes/ast-grep-rules" ]; then
  RULES_DIR="$HOME/.hermes/ast-grep-rules"
fi
FAIL_ON_WARNINGS="${AST_GREP_FAIL_ON_WARNINGS:-0}"
MAX_RESULTS="${AST_GREP_MAX_RESULTS:-25}"

FAIL=0
MATCHES=0

ok() { printf '✅ %s\n' "$*"; }
warn() { printf '⚠️ %s\n' "$*"; }
fail() { printf '❌ %s\n' "$*"; FAIL=1; }

find_ast_grep() {
  if command -v ast-grep >/dev/null 2>&1; then
    command -v ast-grep
    return 0
  fi
  # Some installs provide sg, but /usr/bin/sg is Linux shadow-utils group switch.
  if command -v sg >/dev/null 2>&1 && sg --version 2>/dev/null | grep -qi 'ast-grep'; then
    command -v sg
    return 0
  fi
  if [ -x "$HOME/.hermes/node/bin/ast-grep" ]; then
    printf '%s\n' "$HOME/.hermes/node/bin/ast-grep"
    return 0
  fi
  if [ -x "$HOME/.npm-global/bin/ast-grep" ]; then
    printf '%s\n' "$HOME/.npm-global/bin/ast-grep"
    return 0
  fi
  return 1
}

AST_GREP="$(find_ast_grep || true)"
if [ -z "$AST_GREP" ]; then
  warn "ast-grep not installed; install with: npm install -g @ast-grep/cli"
  exit 0
fi

"$AST_GREP" --version | sed 's/^/ast-grep: /'

if [ ! -d "$RULES_DIR" ]; then
  warn "ast-grep rules directory missing: $RULES_DIR"
  exit 0
fi

scan_target() {
  local target="$1" label="$2"
  if [ ! -d "$target" ]; then
    warn "$label missing, skipped: $target"
    return 0
  fi
  ok "Scanning $label: $target"
  local rule rc out count
  shopt -s nullglob
  for rule in "$RULES_DIR"/*.yml "$RULES_DIR"/*.yaml; do
    out="$(mktemp)"
    set +e
    "$AST_GREP" scan --rule "$rule" --report-style short --max-results "$MAX_RESULTS" \
      --globs '!**/.git/**' --globs '!**/node_modules/**' --globs '!**/__pycache__/**' \
      --globs '!**/venv/**' --globs '!**/.venv/**' "$target" >"$out" 2>&1
    rc=$?
    set -e
    if [ "$rc" -gt 1 ]; then
      fail "ast-grep rule failed on $label: $(basename "$rule")"
      sed 's/^/  /' "$out" | head -80
    elif [ -s "$out" ]; then
      count=$(grep -E '^[^[:space:]].*:[0-9]+:[0-9]+' "$out" 2>/dev/null | wc -l | tr -d ' ')
      if [ -z "$count" ] || [ "$count" = "0" ]; then count=1; fi
      MATCHES=$((MATCHES + count))
      warn "$label $(basename "$rule") matched (${count})"
      sed 's/^/  /' "$out" | head -120
    else
      ok "$label $(basename "$rule") clean"
    fi
    rm -f "$out"
  done

  # AST rules are ideal for structural anti-patterns, but deployment-specific
  # absolute path literals are better guarded with a precise text fallback:
  # ast-grep Python string matching can miss deeper literal path variants.
  out="$(mktemp)"
  set +e
  grep -RInE --include='*.py' --include='*.pyi' --include='*.ts' --include='*.tsx' --include='*.js' --include='*.jsx' \
    --exclude-dir='.git' --exclude-dir='node_modules' --exclude-dir='__pycache__' --exclude-dir='venv' --exclude-dir='.venv' \
    '(["'"'"'`]/root/\.hermes(/[^"'"'"'`]*)?["'"'"'`])' "$target" >"$out" 2>&1
  rc=$?
  set -e
  if [ "$rc" -eq 0 ] && [ -s "$out" ]; then
    count=$(wc -l <"$out" | tr -d ' ')
    MATCHES=$((MATCHES + count))
    warn "$label hardcoded Hermes profile absolute path literal fallback matched (${count})"
    sed 's/^/  /' "$out" | head -120
  elif [ "$rc" -gt 1 ]; then
    fail "hardcoded Hermes profile absolute path fallback scan failed on $label"
    sed 's/^/  /' "$out" | head -80
  else
    ok "$label hardcoded Hermes profile absolute path literal fallback clean"
  fi
  rm -f "$out"
}

scan_target "$PATCHES_DIR" "patches"
scan_target "$HERMES_DIR" "runtime"

if [ "$MATCHES" -gt 0 ]; then
  warn "Structural audit completed with $MATCHES warning match(es)."
  if [ "$FAIL_ON_WARNINGS" = "1" ]; then
    fail "AST_GREP_FAIL_ON_WARNINGS=1 and warnings were found"
  fi
else
  ok "Structural audit found no matches"
fi

if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
