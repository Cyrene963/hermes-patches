#!/usr/bin/env bash
# Fail-closed privacy guard for public Hermes patch repositories.
# Scans current tree and reachable Git history for private/deployment markers
# before allowing publication. Keep patterns generic; deployment-specific extra
# patterns can be supplied through HERMES_PRIVACY_EXTRA_PATTERNS_FILE.
set -euo pipefail

# In normal CLI use the first argument may be a repo path. In Git pre-push hooks,
# Git passes <remote-name> <remote-url>, so ignore non-directory first args.
if [ "${1:-}" != "" ] && [ -d "${1:-}" ]; then
  REPO_DIR="$1"
else
  REPO_DIR="${PATCHES_DIR:-$HOME/.hermes/patches}"
fi
cd "$REPO_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "❌ Not a git worktree: $REPO_DIR" >&2
  exit 2
fi

# Built-in high-risk generic patterns. These intentionally include secret
# shapes and absolute local deployment paths; they must not appear in public
# reusable patch repos except in this guard's own pattern definitions.
PATTERN_FILE="$(mktemp)"
trap 'rm -f "$PATTERN_FILE" "${CURRENT_RAW:-}" "${UNTRACKED_RAW:-}" "$CURRENT_OUT" "$UNTRACKED_OUT" "$HISTORY_OUT"' EXIT
cat >"$PATTERN_FILE" <<'PATTERNS'
ghp_[A-Za-z0-9_]{20,}
github_pat_[A-Za-z0-9_]{20,}
sk-[A-Za-z0-9_-]{20,}
xox[baprs]-[A-Za-z0-9-]{20,}
AKIA[0-9A-Z]{16}
AIza[0-9A-Za-z_-]{20,}
/root/\.hermes
~/projects
telegram:[0-9]{7,}
PATTERNS

# Deployment-specific personal-name patterns are kept OUT of this public file
# (so the guard itself contains no real names). They load from a gitignored local
# extras file — default path below, or override via HERMES_PRIVACY_EXTRA_PATTERNS_FILE.
_DEFAULT_EXTRA="${HERMES_PRIVACY_EXTRA_PATTERNS_FILE:-$HOME/.hermes/privacy-extra-patterns.local}"
if [ -f "$_DEFAULT_EXTRA" ]; then
  cat "$_DEFAULT_EXTRA" >>"$PATTERN_FILE"
fi

if [ -n "${HERMES_PRIVACY_EXTRA_PATTERNS_FILE:-}" ] && [ -f "$HERMES_PRIVACY_EXTRA_PATTERNS_FILE" ]; then
  cat "$HERMES_PRIVACY_EXTRA_PATTERNS_FILE" >>"$PATTERN_FILE"
fi

CURRENT_RAW="$(mktemp)"
UNTRACKED_RAW="$(mktemp)"
CURRENT_OUT="$(mktemp)"
UNTRACKED_OUT="$(mktemp)"
HISTORY_OUT="$(mktemp)"

filter_known_false_positives() {
  # Keep the guard fail-closed while allowing known generated CSS utility names
  # in minified dashboard bundles. Example: Tailwind emits mask-image-* tokens,
  # which contain the substring "sk-ima" and can match broad sk-* secret regexes.
  # Do not suppress real sk-/ghp_/telegram:/absolute-path findings.
  awk '
    /sk-ima/ && /mask-image/ { next }
    { print }
  '
}

# Exclude this guard and structural audit rules: they need to contain the
# generic pattern text they are designed to detect.
set +e
git grep -I -n -E -f "$PATTERN_FILE" -- \
  . \
  ':(exclude).git/**' \
  ':(exclude)scripts/hermes-public-patch-privacy-guard.sh' \
  ':(exclude)ast-grep-rules/**' \
  ':(exclude)scripts/hermes-ast-grep-audit.sh' \
  >"$CURRENT_RAW" 2>/dev/null
current_scan_rc=$?
filter_known_false_positives <"$CURRENT_RAW" >"$CURRENT_OUT"
if [ "$current_scan_rc" -eq 0 ] && [ ! -s "$CURRENT_OUT" ]; then
  current_rc=1
else
  current_rc=$current_scan_rc
fi

untracked_files="$(git ls-files --others --exclude-standard 2>/dev/null | grep -v '^scripts/hermes-public-patch-privacy-guard\.sh$' | grep -v '^ast-grep-rules/' | grep -v '^scripts/hermes-ast-grep-audit\.sh$' || true)"
if [ -n "$untracked_files" ]; then
  # shellcheck disable=SC2086
  grep -I -n -E -f "$PATTERN_FILE" $untracked_files >"$UNTRACKED_RAW" 2>/dev/null
  untracked_scan_rc=$?
  filter_known_false_positives <"$UNTRACKED_RAW" >"$UNTRACKED_OUT"
  if [ "$untracked_scan_rc" -eq 0 ] && [ ! -s "$UNTRACKED_OUT" ]; then
    untracked_rc=1
  else
    untracked_rc=$untracked_scan_rc
  fi
else
  untracked_rc=1
fi

COMMITS="$(git rev-list --all 2>/dev/null)"
if [ -n "$COMMITS" ]; then
  git grep -I -n -f "$PATTERN_FILE" $COMMITS -- \
    . \
    ':(exclude)scripts/hermes-public-patch-privacy-guard.sh' \
    ':(exclude)ast-grep-rules/**' \
    ':(exclude)scripts/hermes-ast-grep-audit.sh' \
    >"$HISTORY_OUT" 2>/dev/null
  history_rc=$?
else
  history_rc=1
fi
set -e

fail=0
if [ "$current_rc" -eq 0 ] && [ -s "$CURRENT_OUT" ]; then
  echo "❌ Privacy guard: tracked current tree contains high-risk private/deployment/secret-shaped markers:" >&2
  sed 's/^/  /' "$CURRENT_OUT" | head -80 >&2
  fail=1
elif [ "$current_rc" -gt 1 ]; then
  echo "❌ Privacy guard current-tree scan failed" >&2
  fail=1
fi

if [ "$untracked_rc" -eq 0 ] && [ -s "$UNTRACKED_OUT" ]; then
  echo "❌ Privacy guard: untracked files contain high-risk private/deployment/secret-shaped markers:" >&2
  sed 's/^/  /' "$UNTRACKED_OUT" | head -80 >&2
  fail=1
elif [ "$untracked_rc" -gt 1 ]; then
  echo "❌ Privacy guard untracked-file scan failed" >&2
  fail=1
fi

if [ "$history_rc" -eq 0 ] && [ -s "$HISTORY_OUT" ]; then
  echo "❌ Privacy guard: Git history contains high-risk private/deployment/secret-shaped markers:" >&2
  sed 's/^/  /' "$HISTORY_OUT" | head -80 >&2
  fail=1
elif [ "$history_rc" -gt 1 ]; then
  echo "❌ Privacy guard history scan failed" >&2
  fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "❌ Push blocked. Clean current tree AND history, then fresh-clone remote and rescan." >&2
  exit 1
fi

echo "✅ Privacy guard passed: tracked tree, untracked files, and reachable Git history clean."
