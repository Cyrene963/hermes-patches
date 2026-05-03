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

# Check prerequisites
if [ ! -d "$HERMES_DIR/.git" ]; then
    echo "❌ 未找到 hermes-agent 仓库: $HERMES_DIR"
    echo "   请先安装 Hermes Agent: pip install hermes-agent"
    exit 1
fi

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

echo ""
echo "🎉 完成！"
