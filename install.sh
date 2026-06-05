#!/bin/bash
# Hermes Agent 社区补丁合集 — 一键安装脚本
# 适配版本：v0.14.0+ (v2026.5.16+)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PATCHES_DIR="$SCRIPT_DIR"
DEFAULT_HERMES_DIR="$HOME/.hermes/hermes-agent"
HERMES_DIR="${HERMES_HOME:-$DEFAULT_HERMES_DIR}"
# When hermes update calls this script from the profile root (~/.hermes),
# HERMES_HOME may point at the profile directory instead of the repo root.
# Detect that case and fall back to the real repo if it exists.
if [ -d "$HERMES_DIR/hermes-agent" ] && [ ! -e "$HERMES_DIR/toolsets.py" ]; then
    HERMES_DIR="$HERMES_DIR/hermes-agent"
fi
if [ ! -e "$HERMES_DIR/toolsets.py" ] && [ -d "$DEFAULT_HERMES_DIR" ]; then
    HERMES_DIR="$DEFAULT_HERMES_DIR"
fi
PROFILE_DIR="${HERMES_PROFILE_DIR:-$HOME/.hermes}"
mkdir -p "$PROFILE_DIR"

# Safety: installer smoke tests often run against throwaway clones under
# ~/.hermes/tasks or /tmp.  Those runs must never rewrite persistent systemd
# units to point at the disposable checkout; doing so breaks the live Memory
# Graph service after the temp tree is removed.  Allow callers to override, but
# default to no systemd side effects for obvious non-production checkouts.
case "$HERMES_DIR" in
    "$HOME/.hermes/tasks"/*|/tmp/*|/var/tmp/*)
        if [ -z "${HERMES_INSTALL_SYSTEMD+x}" ]; then
            HERMES_INSTALL_SYSTEMD=0
            echo "   ⏭️ detected temporary/smoke checkout; skipping systemd installation (set HERMES_INSTALL_SYSTEMD=1 to override)"
        fi
        if [ -z "${HERMES_INSTALL_DB+x}" ]; then
            HERMES_INSTALL_DB=0
            echo "   ⏭️ detected temporary/smoke checkout; skipping live DB role initialization (set HERMES_INSTALL_DB=1 to override)"
        fi
        ;;
esac

# 0. Environment preflight. On a new machine this must do more than copy files:
# it verifies the Hermes repo path, basic commands, Python deps, profile env,
# PostgreSQL/Hindsight/Memory Graph service surfaces, and prints exact fixes.
# Run this after temporary-checkout detection so smoke installs do not pretend to
# configure live DB/systemd surfaces.
if [ -f "$PATCHES_DIR/scripts/hermes-patch-env-preflight.py" ]; then
    python3 "$PATCHES_DIR/scripts/hermes-patch-env-preflight.py" --hermes-dir "$HERMES_DIR" --profile-dir "$PROFILE_DIR" || {
        echo "❌ 环境预检失败：请按上面的 fix 提示修复后重跑 install.sh"
        exit 1
    }
fi

# 0b. Ensure Python runtime dependencies for Memory Graph are present.
# The Memory Graph backend imports bcrypt, jieba, and asyncpg at startup.
# If `hermes update` or a fresh system image omits them, the web UI can look
# "installed" but fail immediately on launch. Install the Debian packages when
# possible so the runtime is self-healing instead of silently degraded.
if command -v python3 >/dev/null 2>&1; then
    missing_deps=()
    for mod in bcrypt jieba asyncpg ahocorasick; do
        if ! python3 - <<PY >/dev/null 2>&1
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("$mod") else 1)
PY
        then
            missing_deps+=("$mod")
        fi
    done
    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo "📦 检测到缺失 Python 运行依赖: ${missing_deps[*]}"
        if command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
            apt_packages=()
            for mod in "${missing_deps[@]}"; do
                case "$mod" in
                    bcrypt) apt_packages+=(python3-bcrypt) ;;
                    jieba) apt_packages+=(python3-jieba) ;;
                    asyncpg) apt_packages+=(python3-asyncpg) ;;
                    ahocorasick) apt_packages+=(python3-ahocorasick) ;;
                esac
            done
            if [ ${#apt_packages[@]} -gt 0 ]; then
                DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null 2>&1 || true
                DEBIAN_FRONTEND=noninteractive apt-get install -y "${apt_packages[@]}"
                echo "   ✅ Python 运行依赖已安装: ${apt_packages[*]}"
            fi
        else
            echo "   ⚠️ 无法自动安装依赖，请手动安装: python3-bcrypt python3-jieba python3-asyncpg python3-ahocorasick"
        fi
    fi
fi


# Overlay copies below are authoritative because upstream moves quickly and large
# git patches are brittle after `hermes update`.
PATCH_FILE="${HERMES_COMBINED_PATCH_FILE:-$PATCHES_DIR/combined-final-v18.patch}"
if [ "${HERMES_APPLY_COMBINED_PATCH:-0}" = "1" ] && [ -s "$PATCH_FILE" ]; then
    echo "📦 尝试应用 $(basename "$PATCH_FILE")..."
    cd "$HERMES_DIR"
    if git apply --check "$PATCH_FILE" 2>/dev/null; then
        git apply "$PATCH_FILE"
        echo "   ✅ combined patch 已应用"
    else
        echo "   ⏭️ combined patch 不兼容，使用 overlay 文件复制"
    fi
else
    echo "   ⏭️ combined patch 默认跳过；使用 overlay 文件复制（设置 HERMES_APPLY_COMBINED_PATCH=1 可启用）"
fi

# Apply targeted local hotfix patches that are safer than whole-file public overlays.
for targeted_patch in "$PATCHES_DIR"/patches/*.patch; do
    [ -e "$targeted_patch" ] || continue
    echo "📦 尝试应用 targeted patch $(basename "$targeted_patch")..."
    cd "$HERMES_DIR"
    if git apply --check "$targeted_patch" 2>/dev/null; then
        git apply "$targeted_patch"
        echo "   ✅ targeted patch $(basename "$targeted_patch") 已应用"
    else
        echo "   ⏭️ targeted patch $(basename "$targeted_patch") 不兼容或已应用"
    fi
done

# 2. Copy verified Memory OS modules / surgically rebased core hooks.
# Avoid broad stale full-file overlays (agent_init, auxiliary_client, dashboard,
# gateway, etc.) unless they have been surgically rebased onto this upstream.
for module in memory_metacognition.py memory_semantic_classifier.py memory_write_pipeline.py shadow_write_logger.py hindsight_access_tracker.py hindsight_reranker.py request_context.py skill_router.py agent_runtime_helpers.py conversation_loop.py tool_executor.py system_prompt.py agent_init.py auxiliary_client.py auto_store_heuristic.py memory_auto_hooks.py; do
    if [ -f "$PATCHES_DIR/agent/$module" ]; then
        cp "$PATCHES_DIR/agent/$module" "$HERMES_DIR/agent/"
        echo "   ✅ agent/$module 已复制"
    fi
done

# 2a. Copy surgically rebased Hermes CLI runtime helpers.
for cli_file in runtime_provider.py; do
    if [ -f "$PATCHES_DIR/hermes_cli/$cli_file" ]; then
        mkdir -p "$HERMES_DIR/hermes_cli"
        cp "$PATCHES_DIR/hermes_cli/$cli_file" "$HERMES_DIR/hermes_cli/"
        echo "   ✅ hermes_cli/$cli_file 已复制"
    fi
done

# 2b. Copy Memory Graph package (keeps DB/RLS hardening in sync with patch repo)
if [ -d "$PATCHES_DIR/agent/memory_graph" ]; then
    mkdir -p "$HERMES_DIR/agent"
    rm -rf "$HERMES_DIR/agent/memory_graph"
    cp -R "$PATCHES_DIR/agent/memory_graph" "$HERMES_DIR/agent/"
    echo "   ✅ agent/memory_graph 已复制"
fi

# 3. Copy tools and DB/session state files
if [ -d "$PATCHES_DIR/cron" ]; then
    mkdir -p "$HERMES_DIR/cron"
    for cron_file in jobs.py scheduler.py __init__.py; do
        if [ -f "$PATCHES_DIR/cron/$cron_file" ]; then
            cp "$PATCHES_DIR/cron/$cron_file" "$HERMES_DIR/cron/"
            echo "   ✅ cron/$cron_file 已复制"
        fi
    done
fi

for tool_file in memory_graph_tool.py session_search_tool.py image_generation_tool.py cronjob_tools.py deep_research_tool.py web_tools.py thread_context.py managed_tool_gateway.py; do
    if [ -f "$PATCHES_DIR/tools/$tool_file" ]; then
        cp "$PATCHES_DIR/tools/$tool_file" "$HERMES_DIR/tools/"
        echo "   ✅ tools/$tool_file 已复制"
    fi
done
if [ -f "$PATCHES_DIR/hermes_state.py" ]; then
    cp "$PATCHES_DIR/hermes_state.py" "$HERMES_DIR/hermes_state.py"
    echo "   ✅ hermes_state.py 已复制"
fi
if [ -f "$PATCHES_DIR/toolsets.py" ]; then
    cp "$PATCHES_DIR/toolsets.py" "$HERMES_DIR/toolsets.py"
    echo "   ✅ toolsets.py 已复制"
fi

# Gateway full-file overlays are stale against latest upstream f019a9c49+ and
# can overwrite structured stream/media/session fixes. Keep them opt-in until
# surgically rebased.
if [ "${HERMES_APPLY_STALE_GATEWAY_OVERLAYS:-0}" = "1" ]; then
    if [ -f "$PATCHES_DIR/gateway/config.py" ]; then
        mkdir -p "$HERMES_DIR/gateway"
        cp "$PATCHES_DIR/gateway/config.py" "$HERMES_DIR/gateway/config.py"
        echo "   ⚠️ stale opt-in gateway/config.py 已复制"
    fi
    if [ -f "$PATCHES_DIR/gateway/session.py" ]; then
        mkdir -p "$HERMES_DIR/gateway"
        cp "$PATCHES_DIR/gateway/session.py" "$HERMES_DIR/gateway/session.py"
        echo "   ⚠️ stale opt-in gateway/session.py 已复制"
    fi
    if [ -f "$PATCHES_DIR/gateway/platforms/base.py" ]; then
        mkdir -p "$HERMES_DIR/gateway/platforms"
        cp "$PATCHES_DIR/gateway/platforms/base.py" "$HERMES_DIR/gateway/platforms/base.py"
        echo "   ⚠️ stale opt-in gateway/platforms/base.py 已复制"
    fi
    if [ -f "$PATCHES_DIR/gateway/platforms/telegram.py" ]; then
        mkdir -p "$HERMES_DIR/gateway/platforms"
        cp "$PATCHES_DIR/gateway/platforms/telegram.py" "$HERMES_DIR/gateway/platforms/telegram.py"
        echo "   ⚠️ stale opt-in gateway/platforms/telegram.py 已复制"
    fi
else
    echo "   ⏭️ stale gateway overlays skipped (set HERMES_APPLY_STALE_GATEWAY_OVERLAYS=1 to force)"
fi
if [ -f "$PATCHES_DIR/plugins/image_gen/openai/__init__.py" ]; then
    mkdir -p "$HERMES_DIR/plugins/image_gen/openai"
    cp "$PATCHES_DIR/plugins/image_gen/openai/__init__.py" "$HERMES_DIR/plugins/image_gen/openai/__init__.py"
    echo "   ✅ OpenAI image_gen provider 已复制"
fi

# Optional memory-tencentdb provider overlay. Keep it explicit: the provider can
# spawn a Node.js Gateway sidecar and perform automatic memory extraction, so a
# normal hermes update should copy the code only when the operator opts in.
if [ -d "$PATCHES_DIR/plugins/memory/memory_tencentdb" ]; then
    if [ "${HERMES_INSTALL_MEMORY_TENCENTDB:-0}" = "1" ]; then
        mkdir -p "$HERMES_DIR/plugins/memory"
        rm -rf "$HERMES_DIR/plugins/memory/memory_tencentdb"
        cp -R "$PATCHES_DIR/plugins/memory/memory_tencentdb" "$HERMES_DIR/plugins/memory/"
        echo "   ✅ memory_tencentdb provider 已复制（显式启用）"
    else
        echo "   ⏭️ memory_tencentdb provider skipped (set HERMES_INSTALL_MEMORY_TENCENTDB=1 to install)"
    fi
fi

# 3a. Dashboard/WebUI source overlays were removed after the v0.15.2 audit.
# The old full-file web/src and hermes_cli/web_server.py overlays were stale and
# could silently overwrite upstream dashboard auth/session/plugin fixes. Keep the
# served prebuilt bundle path below, but do not copy stale source by default.
# Always copy the prebuilt dashboard bundle when the patch repo carries one.
# Source overlays are intentionally opt-in because they can drift against
# upstream TypeScript, but web_dist is the runtime artifact actually served by
# hermes_cli.web_server. Without this copy, a bare hermes update can leave the
# dashboard serving an old bundle even when the runtime source/API fixes are
# present.
if [ -d "$PATCHES_DIR/hermes_cli/web_dist" ]; then
    rm -rf "$HERMES_DIR/hermes_cli/web_dist"
    mkdir -p "$HERMES_DIR/hermes_cli"
    cp -R "$PATCHES_DIR/hermes_cli/web_dist" "$HERMES_DIR/hermes_cli/web_dist"
    echo "   ✅ patched hermes_cli/web_dist bundle 已复制"
fi
if [ "${HERMES_BUILD_WEB:-0}" = "1" ] && [ -f "$HERMES_DIR/web/package.json" ] && command -v npm >/dev/null 2>&1; then
    if [ ! -x "$HERMES_DIR/web/node_modules/.bin/tsc" ] || [ ! -x "$HERMES_DIR/web/node_modules/.bin/vite" ]; then
        if [ -f "$HERMES_DIR/web/package-lock.json" ]; then
            echo "   📦 Hermes dashboard dependencies missing/incomplete; running npm ci"
            (cd "$HERMES_DIR/web" && npm ci --prefer-offline --no-audit --no-fund)
        else
            echo "   📦 Hermes dashboard dependencies missing; running npm install"
            (cd "$HERMES_DIR/web" && npm install --no-audit --no-fund)
        fi
    fi
    (cd "$HERMES_DIR/web" && npm run build)
    echo "   ✅ Hermes dashboard web_dist 已重建"
else
    echo "   ⏭️ Hermes dashboard web build 默认跳过；使用 overlay web_dist（设置 HERMES_BUILD_WEB=1 可重建）"
fi

# 3b. Copy patched Hindsight provider and site-package hotfixes
if [ -f "$PATCHES_DIR/plugins/memory/hindsight/__init__.py" ]; then
    mkdir -p "$HERMES_DIR/plugins/memory/hindsight"
    cp "$PATCHES_DIR/plugins/memory/hindsight/__init__.py" "$HERMES_DIR/plugins/memory/hindsight/__init__.py"
    echo "   ✅ Hindsight provider fallback 已复制"
fi
if [ -f "$PATCHES_DIR/site-packages/hindsight_api/engine/embeddings.py" ]; then
    SITE_DIR="$HERMES_DIR/venv/lib/python3.11/site-packages/hindsight_api/engine"
    if [ -d "$SITE_DIR" ]; then
        cp "$PATCHES_DIR/site-packages/hindsight_api/engine/embeddings.py" "$SITE_DIR/embeddings.py"
        echo "   ✅ Hindsight embeddings known-dimension hotfix 已复制"
    fi
fi

# 3c. Ensure least-privileged Memory Graph DB role exists (superuser bypasses RLS)
if [ "${HERMES_INSTALL_DB:-1}" != "0" ] && command -v psql >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
    ENV_FILE="$PROFILE_DIR/.env"
    mkdir -p "$PROFILE_DIR"
    if grep -q '^MEMORY_GRAPH_DB_PASSWORD=' "$ENV_FILE" 2>/dev/null; then
        MG_DB_PASSWORD="$(grep '^MEMORY_GRAPH_DB_PASSWORD=' "$ENV_FILE" | tail -1 | cut -d= -f2- | sed 's/^\"//;s/\"$//;s/^'\''//;s/'\''$//')"
    else
        MG_DB_PASSWORD="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
        printf '\nMEMORY_GRAPH_DB_PASSWORD=%s\n' "$MG_DB_PASSWORD" >> "$ENV_FILE"
    fi
    if [ -n "$MG_DB_PASSWORD" ]; then
        sudo -u postgres psql -d hindsight -v ON_ERROR_STOP=1 >/dev/null <<SQL || echo "   ⚠️ mg_app DB role 初始化失败，请手动检查 PostgreSQL"
DO \$\$ BEGIN
   IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'mg_app') THEN
      CREATE ROLE mg_app LOGIN PASSWORD '$MG_DB_PASSWORD';
   ELSE
      ALTER ROLE mg_app LOGIN PASSWORD '$MG_DB_PASSWORD';
   END IF;
END \$\$;
GRANT CONNECT ON DATABASE hindsight TO mg_app;
GRANT USAGE ON SCHEMA public TO mg_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON mg_nodes, mg_memories, mg_edges, mg_paths, mg_glossary_keywords, mg_search_documents, mg_access_log, mg_snapshots, mg_access_logs TO mg_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO mg_app;
ALTER TABLE mg_edges ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS mg_edges_isolation ON mg_edges;
CREATE POLICY mg_edges_isolation ON mg_edges
    FOR ALL
    USING (
        current_setting('app.is_admin', true) = 'true'
        OR parent_uuid = '00000000-0000-0000-0000-000000000000'
        OR parent_uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    )
    WITH CHECK (
        current_setting('app.is_admin', true) = 'true'
        OR parent_uuid = '00000000-0000-0000-0000-000000000000'
        OR parent_uuid IN (
            SELECT node_uuid FROM mg_paths
            WHERE namespace = current_setting('app.current_namespace', true)
               OR namespace = ''
               OR namespace IS NULL
        )
    );
SQL
        echo "   ✅ mg_app least-privileged DB role 已确认"
    fi
fi

# 4. Copy config
if [ -f "$PATCHES_DIR/memory_write_config.yaml" ]; then
    cp "$PATCHES_DIR/memory_write_config.yaml" "$PROFILE_DIR/"
    echo "   ✅ memory_write_config.yaml 已复制"
fi
if [ -f "$PATCHES_DIR/examples/academic_identity_guard.example.json" ] && [ ! -f "$PROFILE_DIR/academic_identity_guard.json" ]; then
    cp "$PATCHES_DIR/examples/academic_identity_guard.example.json" "$PROFILE_DIR/academic_identity_guard.json"
    echo "   ✅ academic_identity_guard.json example 已初始化（请按实际用户科目修改）"
fi

# 5. Copy default memory policy
if [ -f "$PATCHES_DIR/memory_policy.default.yaml" ] && [ ! -f "$PROFILE_DIR/memory_policy.yaml" ]; then
    cp "$PATCHES_DIR/memory_policy.default.yaml" "$PROFILE_DIR/memory_policy.yaml"
    echo "   ✅ memory_policy.yaml 已初始化"
fi

# 6. Clean .pyc caches
find "$HERMES_DIR/agent" -name "memory_metacognition*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "memory_semantic_classifier*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "memory_write_pipeline*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "shadow_write_logger*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "hindsight_access_tracker*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "hindsight_reranker*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "skill_router*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "auto_store_heuristic*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "memory_auto_hooks*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/tools" -name "memory_graph_tool*.pyc" -delete 2>/dev/null
if [ -d "$HERMES_DIR/plugins/memory/hindsight" ]; then
    find "$HERMES_DIR/plugins/memory/hindsight" -name "*.pyc" -delete 2>/dev/null
fi
if [ -d "$HERMES_DIR/plugins/memory/memory_tencentdb" ]; then
    find "$HERMES_DIR/plugins/memory/memory_tencentdb" -name "*.pyc" -delete 2>/dev/null
fi
if [ -d "$HERMES_DIR/venv/lib/python3.11/site-packages/hindsight_api" ]; then
    find "$HERMES_DIR/venv/lib/python3.11/site-packages/hindsight_api" -name "embeddings*.pyc" -delete 2>/dev/null
fi
find "$HERMES_DIR/agent" -name "conversation_loop*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "chat_completion_helpers*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "agent_init*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "auxiliary_client*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "agent_runtime_helpers*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "tool_executor*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/agent" -name "system_prompt*.pyc" -delete 2>/dev/null
find "$HERMES_DIR" -maxdepth 2 -name "hermes_state*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/hermes_cli" -name "config*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/hermes_cli" -name "runtime_provider*.pyc" -delete 2>/dev/null
find "$HERMES_DIR/hermes_cli" -name "main*.pyc" -delete 2>/dev/null
echo "   ✅ .pyc 缓存已清理"

# 6a. Compile critical patched/runtime files so update-time regressions fail
# inside the one command the user actually runs (`hermes update`) instead of
# requiring a memorized follow-up py_compile command.
PYTHON_BIN="$HERMES_DIR/venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [ -n "$PYTHON_BIN" ]; then
    compile_files=()
    for rel in \
        agent/system_prompt.py \
        agent/agent_runtime_helpers.py \
        agent/agent_init.py \
        agent/auxiliary_client.py \
        agent/conversation_loop.py \
        agent/auto_store_heuristic.py \
        agent/memory_auto_hooks.py \
        hermes_cli/config.py \
        hermes_cli/runtime_provider.py \
        hermes_cli/main.py \
        gateway/platforms/telegram.py \
        tools/memory_graph_tool.py \
        tools/session_search_tool.py; do
        if [ -f "$HERMES_DIR/$rel" ]; then
            compile_files+=("$HERMES_DIR/$rel")
        fi
    done
    if [ ${#compile_files[@]} -gt 0 ]; then
        "$PYTHON_BIN" -m py_compile "${compile_files[@]}"
        echo "   ✅ 关键 Python 文件 py_compile 通过"
    fi
fi

# 6b. Install patch-chain guard and structural audit helpers so future updates verify
# GitHub/local patch tree, installed Hermes code, Memory Graph health, dashboard
# protected APIs, and AST-level high-risk code patterns together.
if [ -f "$PATCHES_DIR/scripts/hermes-patch-env-preflight.py" ]; then
    mkdir -p "$PROFILE_DIR/scripts"
    cp "$PATCHES_DIR/scripts/hermes-patch-env-preflight.py" "$PROFILE_DIR/scripts/hermes-patch-env-preflight.py"
    chmod +x "$PROFILE_DIR/scripts/hermes-patch-env-preflight.py"
    echo "   ✅ hermes-patch-env-preflight.py 已安装"
fi
if [ -f "$PATCHES_DIR/scripts/hermes-patch-chain-guard.sh" ]; then
    mkdir -p "$PROFILE_DIR/scripts"
    cp "$PATCHES_DIR/scripts/hermes-patch-chain-guard.sh" "$PROFILE_DIR/scripts/hermes-patch-chain-guard.sh"
    chmod +x "$PROFILE_DIR/scripts/hermes-patch-chain-guard.sh"
    echo "   ✅ hermes-patch-chain-guard.sh 已安装"
fi
if [ -f "$PATCHES_DIR/scripts/memory_os_shadow_namespace_watchdog.py" ]; then
    mkdir -p "$PROFILE_DIR/scripts"
    cp "$PATCHES_DIR/scripts/memory_os_shadow_namespace_watchdog.py" "$PROFILE_DIR/scripts/memory_os_shadow_namespace_watchdog.py"
    chmod +x "$PROFILE_DIR/scripts/memory_os_shadow_namespace_watchdog.py"
    echo "   ✅ memory_os_shadow_namespace_watchdog.py 已安装"
fi
if [ -f "$PATCHES_DIR/scripts/hermes-ast-grep-audit.sh" ]; then
    mkdir -p "$PROFILE_DIR/scripts"
    cp "$PATCHES_DIR/scripts/hermes-ast-grep-audit.sh" "$PROFILE_DIR/scripts/hermes-ast-grep-audit.sh"
    chmod +x "$PROFILE_DIR/scripts/hermes-ast-grep-audit.sh"
    echo "   ✅ hermes-ast-grep-audit.sh 已安装"
fi
if [ -f "$PATCHES_DIR/scripts/hermes-public-patch-privacy-guard.sh" ]; then
    mkdir -p "$PROFILE_DIR/scripts"
    cp "$PATCHES_DIR/scripts/hermes-public-patch-privacy-guard.sh" "$PROFILE_DIR/scripts/hermes-public-patch-privacy-guard.sh"
    chmod +x "$PROFILE_DIR/scripts/hermes-public-patch-privacy-guard.sh"
    if [ -d "$PATCHES_DIR/.git/hooks" ]; then
        cp "$PATCHES_DIR/scripts/hermes-public-patch-privacy-guard.sh" "$PATCHES_DIR/.git/hooks/pre-push"
        chmod +x "$PATCHES_DIR/.git/hooks/pre-push"
        echo "   ✅ patch repo pre-push privacy guard 已安装"
    fi
    echo "   ✅ hermes-public-patch-privacy-guard.sh 已安装"
fi
if [ -d "$PATCHES_DIR/ast-grep-rules" ]; then
    mkdir -p "$PROFILE_DIR/ast-grep-rules"
    cp -R "$PATCHES_DIR/ast-grep-rules/." "$PROFILE_DIR/ast-grep-rules/"
    echo "   ✅ ast-grep structural audit rules 已安装"
fi
if ! command -v ast-grep >/dev/null 2>&1; then
    if command -v npm >/dev/null 2>&1; then
        npm install -g @ast-grep/cli >/dev/null 2>&1 || echo "   ⚠️ ast-grep 自动安装失败，可手动运行: npm install -g @ast-grep/cli"
    else
        echo "   ⚠️ npm 不存在，跳过 ast-grep 安装；可手动安装 @ast-grep/cli"
    fi
fi
if [ -f "$PATCHES_DIR/scripts/hermes_deep_research_orchestrator.py" ]; then
    mkdir -p "$PROFILE_DIR/scripts"
    cp "$PATCHES_DIR/scripts/hermes_deep_research_orchestrator.py" "$PROFILE_DIR/scripts/hermes_deep_research_orchestrator.py"
    chmod +x "$PROFILE_DIR/scripts/hermes_deep_research_orchestrator.py"
    echo "   ✅ hermes_deep_research_orchestrator.py 已安装"
fi
if [ -f "$PATCHES_DIR/scripts/hermes_search_as_code_research.py" ]; then
    mkdir -p "$PROFILE_DIR/scripts"
    cp "$PATCHES_DIR/scripts/hermes_search_as_code_research.py" "$PROFILE_DIR/scripts/hermes_search_as_code_research.py"
    chmod +x "$PROFILE_DIR/scripts/hermes_search_as_code_research.py"
    echo "   ✅ hermes_search_as_code_research.py 已安装"
fi
if [ -f "$PATCHES_DIR/scripts/deploy-standalone-memory-graph-webui.sh" ]; then
    mkdir -p "$PROFILE_DIR/scripts"
    cp "$PATCHES_DIR/scripts/deploy-standalone-memory-graph-webui.sh" "$PROFILE_DIR/scripts/deploy-standalone-memory-graph-webui.sh"
    chmod +x "$PROFILE_DIR/scripts/deploy-standalone-memory-graph-webui.sh"
    echo "   ✅ deploy-standalone-memory-graph-webui.sh 已安装"
    if [ "${HERMES_DEPLOY_STANDALONE_MG_WEBUI:-0}" = "1" ] && [ -n "${MG_PROJECT_DIR:-}" ] && [ "$(id -u)" -eq 0 ]; then
        "$PROFILE_DIR/scripts/deploy-standalone-memory-graph-webui.sh" || echo "   ⚠️ standalone Memory Graph WebUI 部署失败，请手动运行 $PROFILE_DIR/scripts/deploy-standalone-memory-graph-webui.sh"
    fi
fi

# 7. Register memory_graph tools in toolsets.py without replacing upstream's file.
# Tool discovery needs BOTH registry.register(...) in tools/memory_graph_tool.py
# and explicit toolset/core entries here; otherwise tools silently never load.
python3 - "$HERMES_DIR/toolsets.py" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text()
mg_tools = [
    "memory_graph_read", "memory_graph_create", "memory_graph_update",
    "memory_graph_delete", "memory_graph_list", "memory_graph_search",
    "memory_graph_alias", "memory_graph_glossary_add", "memory_graph_glossary_scan",
    "memory_graph_recall", "memory_graph_orphans", "memory_graph_random",
    "memory_graph_diagnostics", "memory_graph_purge",
]
# Older patch overlays added deep_research to core/web. On newer upstream this
# tool is not upstream-native, so make its registration deterministic without
# replacing the whole drifting toolsets.py file.
deep_research_core_marker = '    "web_search", "web_extract",'
if '"deep_research"' not in text.split("# Terminal", 1)[0]:
    if deep_research_core_marker in text:
        text = text.replace(deep_research_core_marker, '    "web_search", "web_extract", "deep_research",', 1)
    else:
        raise SystemExit("toolsets.py web core marker not found; cannot insert deep_research safely")
text = re.sub(
    r'("web"\s*:\s*\{[^{}]*?"tools"\s*:\s*\[\s*"web_search",\s*"web_extract")\s*(\])',
    lambda m: m.group(1) + ', "deep_research"' + m.group(2) if 'deep_research' not in m.group(0) else m.group(0),
    text,
    count=1,
    flags=re.S,
)
core_marker = '    # Session history search\n    "session_search",'
if "memory_graph_search" not in text.split("# Session history search", 1)[0]:
    insert = (
        '    # Memory Graph (URI-tree structured memory)\n'
        '    "memory_graph_read", "memory_graph_create", "memory_graph_update",\n'
        '    "memory_graph_delete", "memory_graph_list", "memory_graph_search",\n'
        '    "memory_graph_alias", "memory_graph_glossary_add", "memory_graph_glossary_scan",\n'
        '    "memory_graph_recall", "memory_graph_orphans", "memory_graph_random",\n'
        '    "memory_graph_diagnostics", "memory_graph_purge",\n'
    )
    if core_marker not in text:
        raise SystemExit("toolsets.py core marker not found; cannot insert memory_graph core tools safely")
    text = text.replace(core_marker, insert + core_marker, 1)

if '"memory_graph": {' not in text:
    entry = '''    "memory_graph": {
        "description": "URI-tree structured memory graph (search, create, update, delete, list, alias, glossary)",
        "tools": [
            "memory_graph_read", "memory_graph_create", "memory_graph_update",
            "memory_graph_delete", "memory_graph_list", "memory_graph_search",
            "memory_graph_alias", "memory_graph_glossary_add", "memory_graph_glossary_scan",
            "memory_graph_recall", "memory_graph_orphans", "memory_graph_random",
            "memory_graph_diagnostics", "memory_graph_purge"
        ],
        "includes": []
    },

'''
    marker = '    "session_search": {'
    if marker not in text:
        raise SystemExit("toolsets.py TOOLSETS session_search marker not found; cannot insert memory_graph toolset safely")
    text = text.replace(marker, entry + marker, 1)

path.write_text(text)
PY

if grep -q "memory_graph_search" "$HERMES_DIR/toolsets.py" 2>/dev/null; then
    echo "   ✅ memory_graph tools 已在 toolsets.py 注册"
else
    echo "   ⚠️ memory_graph tools 未在 toolsets.py 中注册，请手动添加"
fi

echo ""
echo "✅ 补丁文件、配置模板、工具注册和本机环境检查已完成。"
echo "   若这是正在运行的 Hermes gateway，请重启以加载 Python 代码变更: hermes gateway restart"


# 8. Install resident Memory Stack scripts and systemd units when available.
# This keeps the HTTP dashboard/API on 127.0.0.1:8900 alive after reboot and
# after `hermes update`. The watchdog catches "process up but API unhealthy"
# failures that Restart=always cannot see.
if [ -f "$PATCHES_DIR/scripts/hermes-memory-stack-watchdog.sh" ]; then
    mkdir -p "$PROFILE_DIR/scripts"
    cp "$PATCHES_DIR/scripts/hermes-memory-stack-watchdog.sh" "$PROFILE_DIR/scripts/hermes-memory-stack-watchdog.sh"
    chmod +x "$PROFILE_DIR/scripts/hermes-memory-stack-watchdog.sh"
    echo "   ✅ hermes-memory-stack-watchdog.sh 已复制"
fi

if [ "${HERMES_INSTALL_SYSTEMD:-1}" != "0" ] && command -v systemctl >/dev/null 2>&1 && [ -d "$PATCHES_DIR/systemd" ]; then
    if [ "$(id -u)" -eq 0 ] && [ -d /etc/systemd/system ]; then
        sed -e "s#__HERMES_HOME__#$PROFILE_DIR#g" -e "s#__HERMES_REPO__#$HERMES_DIR#g" "$PATCHES_DIR/systemd/hermes-memory-graph.system.service" > /etc/systemd/system/hermes-memory-graph.service
        cp "$PATCHES_DIR/systemd/hermes-memory-stack.system.target" /etc/systemd/system/hermes-memory-stack.target
        if [ -f "$PATCHES_DIR/systemd/hermes-memory-stack-watchdog.system.service" ]; then
            sed -e "s#__HERMES_HOME__#$PROFILE_DIR#g" -e "s#__HERMES_REPO__#$HERMES_DIR#g" "$PATCHES_DIR/systemd/hermes-memory-stack-watchdog.system.service" > /etc/systemd/system/hermes-memory-stack-watchdog.service
        fi
        if [ -f "$PATCHES_DIR/systemd/hermes-memory-stack-watchdog.system.timer" ]; then
            cp "$PATCHES_DIR/systemd/hermes-memory-stack-watchdog.system.timer" /etc/systemd/system/hermes-memory-stack-watchdog.timer
        fi
        systemctl daemon-reload || true
        systemctl enable hermes-memory-graph.service hermes-memory-stack.target >/dev/null 2>&1 || true
        systemctl restart hermes-memory-graph.service >/dev/null 2>&1 || true
        for _i in $(seq 1 15); do
            curl -fsS -m 2 http://127.0.0.1:8900/health >/dev/null 2>&1 && break
            sleep 1
        done
        if [ -f /etc/systemd/system/hermes-memory-stack-watchdog.timer ]; then
            systemctl enable --now hermes-memory-stack-watchdog.timer >/dev/null 2>&1 || true
        fi
        echo "   ✅ hermes-memory-graph systemd service/watchdog 已安装/启动"
    else
        USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
        mkdir -p "$USER_SYSTEMD_DIR"
        cp "$PATCHES_DIR/systemd/hermes-memory-graph.service" "$USER_SYSTEMD_DIR/hermes-memory-graph.service"
        cp "$PATCHES_DIR/systemd/hermes-memory-stack.target" "$USER_SYSTEMD_DIR/hermes-memory-stack.target"
        if [ -f "$PATCHES_DIR/systemd/hermes-memory-stack-watchdog.service" ]; then
            cp "$PATCHES_DIR/systemd/hermes-memory-stack-watchdog.service" "$USER_SYSTEMD_DIR/hermes-memory-stack-watchdog.service"
        fi
        if [ -f "$PATCHES_DIR/systemd/hermes-memory-stack-watchdog.timer" ]; then
            cp "$PATCHES_DIR/systemd/hermes-memory-stack-watchdog.timer" "$USER_SYSTEMD_DIR/hermes-memory-stack-watchdog.timer"
        fi
        systemctl --user daemon-reload || true
        systemctl --user enable hermes-memory-graph.service hermes-memory-stack.target >/dev/null 2>&1 || true
        systemctl --user restart hermes-memory-graph.service >/dev/null 2>&1 || true
        for _i in $(seq 1 15); do
            curl -fsS -m 2 http://127.0.0.1:8900/health >/dev/null 2>&1 && break
            sleep 1
        done
        if [ -f "$USER_SYSTEMD_DIR/hermes-memory-stack-watchdog.timer" ]; then
            systemctl --user enable --now hermes-memory-stack-watchdog.timer >/dev/null 2>&1 || true
        fi
        echo "   ✅ hermes-memory-graph user systemd service/watchdog 已安装/启动"
    fi
fi

# 9. Copy memory-graph plugin
if [ -d "$PATCHES_DIR/plugins/memory-graph" ]; then
    mkdir -p "$PROFILE_DIR/plugins/memory-graph"
    cp -R "$PATCHES_DIR/plugins/memory-graph/." "$PROFILE_DIR/plugins/memory-graph/"
    echo "   ✅ memory-graph plugin overlay 已复制"
elif [ -d "$PROFILE_DIR/plugins/memory-graph" ]; then
    echo "   ✅ memory-graph plugin 已存在"
else
    echo "   ⚠️ memory-graph plugin 不存在，请手动安装"
fi

# 10. Copy regression tests when present (non-runtime, but protects future updates)
if [ -d "$PATCHES_DIR/tests" ]; then
    mkdir -p "$HERMES_DIR/tests"
    cp -R "$PATCHES_DIR/tests/." "$HERMES_DIR/tests/"
    echo "   ✅ tests overlay 已复制"
fi
