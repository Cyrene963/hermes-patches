#!/bin/bash
# hermes-patches 一键安装脚本
# 用法: bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
# 或者: git clone https://github.com/Cyrene963/hermes-patches.git && cd hermes-patches && bash install.sh

set -e

REPO_URL="https://github.com/Cyrene963/hermes-patches.git"
HERMES_DIR="${HERMES_HOME:-$HOME/.hermes/hermes-agent}"
TEMP_DIR=$(mktemp -d)

echo "╔══════════════════════════════════════════╗"
echo "║     Hermes Agent 社区补丁合集 v1.0       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check prerequisites - find hermes-agent source
find_hermes_source() {
    # 1. Check default path
    if [ -d "$HERMES_DIR/.git" ]; then
        return 0
    fi

    # 2. Try pip-installed location
    local pip_source
    pip_source=$(python3 -c "import hermes_cli; import os; print(os.path.dirname(os.path.dirname(hermes_cli.__file__)))" 2>/dev/null || true)
    if [ -n "$pip_source" ] && [ -d "$pip_source/.git" ]; then
        HERMES_DIR="$pip_source"
        echo "📂 从 pip 安装路径找到: $HERMES_DIR"
        return 0
    fi

    # 3. Try common alternative paths (including FHS root layout)
    for alt_path in "$HOME/hermes-agent" "$HOME/.hermes/hermes-agent" "/usr/local/lib/hermes-agent" "/opt/hermes-agent" "$pip_source"; do
        if [ -n "$alt_path" ] && [ -d "$alt_path" ] && [ -f "$alt_path/run_agent.py" ]; then
            HERMES_DIR="$alt_path"
            # Initialize git if needed (pip install doesn't create .git)
            if [ ! -d "$HERMES_DIR/.git" ]; then
                echo "📂 找到 Hermes 源码: $HERMES_DIR (初始化 git...)"
                cd "$HERMES_DIR"
                git init -q
                git add -A
                git commit -q -m "Initial commit (auto-initialized for patching)"
                cd - > /dev/null
            fi
            return 0
        fi
    done

    # 4. Check if hermes command exists, try to find source from it
    if command -v hermes &>/dev/null; then
        local hermes_path
        hermes_path=$(command -v hermes)
        # hermes is usually a wrapper script, check its content
        local source_dir
        source_dir=$(grep -o 'HERMES_HOME=[^ ]*' "$hermes_path" 2>/dev/null | head -1 | cut -d= -f2 | tr -d '"' || true)
        if [ -n "$source_dir" ] && [ -d "$source_dir" ]; then
            HERMES_DIR="$source_dir"
            if [ ! -d "$HERMES_DIR/.git" ]; then
                echo "📂 找到 Hermes: $HERMES_DIR (初始化 git...)"
                cd "$HERMES_DIR"
                git init -q
                git add -A
                git commit -q -m "Initial commit (auto-initialized for patching)"
                cd - > /dev/null
            fi
            return 0
        fi
    fi

    return 1
}

if ! find_hermes_source; then
    echo "❌ 未找到 Hermes Agent 安装"
    echo "   请先安装: pip install hermes-agent"
    echo "   或克隆: git clone https://github.com/NousResearch/hermes-agent.git ~/.hermes/hermes-agent"
    exit 1
fi
echo "✅ Hermes 路径: $HERMES_DIR"

if ! command -v git &>/dev/null; then
    echo "❌ 需要 git"
    exit 1
fi

# Clone or use local
if [ -d "$(dirname "$0")/patches" ]; then
    PATCHES_DIR="$(dirname "$0")/patches"
    echo "📂 使用本地补丁目录"
else
    echo "📥 下载补丁..."
    git clone --depth 1 "$REPO_URL" "$TEMP_DIR/hermes-patches" 2>/dev/null
    PATCHES_DIR="$TEMP_DIR/hermes-patches/patches"
fi

cd "$HERMES_DIR"

# Save current branch/commit for rollback
ORIGINAL_HEAD=$(git rev-parse HEAD)
BRANCH=$(git branch --show-current)
echo "📌 当前: $BRANCH @ ${ORIGINAL_HEAD:0:8}"
echo ""

# Apply patches
APPLIED=0
SKIPPED=0
FAILED=0

for patch_file in "$PATCHES_DIR"/*.patch; do
    [ -f "$patch_file" ] || continue
    patch_name=$(basename "$patch_file" .patch)

    # Extract subject
    subject=$(sed -n 's/^Subject: \[PATCH[^]]*\] //p' "$patch_file" 2>/dev/null | head -1)
    [ -z "$subject" ] && subject="$patch_name"

    # Check if already applied (match subject in recent commits)
    short_subject=$(echo "$subject" | head -c 50)
    if git log --oneline -50 HEAD 2>/dev/null | grep -qi "$short_subject"; then
        echo "  ⏭️  已应用: $subject"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Try git am first (preserves author info)
    if git am --3way "$patch_file" 2>/dev/null; then
        echo "  ✅ $subject"
        APPLIED=$((APPLIED + 1))
    else
        git am --abort 2>/dev/null || true
        # Fallback to git apply
        if git apply --check "$patch_file" 2>/dev/null; then
            git apply "$patch_file"
            git add -A
            git commit -m "Applied: $patch_name" --no-verify 2>/dev/null || true
            echo "  ✅ $subject (fallback)"
            APPLIED=$((APPLIED + 1))
        else
            echo "  ❌ 冲突: $subject"
            FAILED=$((FAILED + 1))
        fi
    fi
done

echo ""
echo "═══════════════════════════════════════════"
echo "  ✅ 已应用: $APPLIED"
echo "  ⏭️  已跳过: $SKIPPED"
echo "  ❌ 失败:   $FAILED"
echo "═══════════════════════════════════════════"

if [ "$APPLIED" -gt 0 ]; then
    echo ""
    echo "🔄 重启 Hermes Gateway..."
    for svc in hermes-gateway hermes-dashboard; do
        if systemctl --user is-active "$svc" >/dev/null 2>&1; then
            systemctl --user restart "$svc"
            echo "  ✅ $svc 已重启"
        fi
    done

    # Also try process-based restart
    if pgrep -f "hermes.*gateway" >/dev/null 2>&1; then
        echo "  💡 检测到 gateway 进程，请手动重启: hermes gateway restart"
    fi
fi

if [ "$FAILED" -gt 0 ]; then
    echo ""
    echo "⚠️  有 $FAILED 个补丁冲突，可能需要手动解决"
    echo "   回滚命令: cd $HERMES_DIR && git reset --hard $ORIGINAL_HEAD"
fi

# Cleanup
rm -rf "$TEMP_DIR"

# Install memory metacognition policy (if not already present)
POLICY_DIR="${HERMES_HOME:-$HOME/.hermes}"
if [ ! -f "$POLICY_DIR/memory_policy.yaml" ]; then
    if [ -f "$PATCHES_DIR/../memory_policy.default.yaml" ]; then
        cp "$PATCHES_DIR/../memory_policy.default.yaml" "$POLICY_DIR/memory_policy.yaml"
        echo ""
        echo "🧠 记忆元认知框架已启用 → $POLICY_DIR/memory_policy.yaml"
        echo "   自定义或删除此文件可关闭"
    elif [ -d "$(dirname "$0")" ] && [ -f "$(dirname "$0")/memory_policy.default.yaml" ]; then
        cp "$(dirname "$0")/memory_policy.default.yaml" "$POLICY_DIR/memory_policy.yaml"
        echo ""
        echo "🧠 记忆元认知框架已启用 → $POLICY_DIR/memory_policy.yaml"
        echo "   自定义或删除此文件可关闭"
    fi
else
    echo ""
    echo "🧠 记忆元认知: 已有 policy 文件，跳过"
fi

echo ""
echo "🎉 完成！"
