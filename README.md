# Hermes Agent 社区补丁合集

> 收集了 Hermes Agent 项目中尚未合并的优质 PR，一键应用到你的本地安装。

## 快速安装

```bash
# 一行命令
bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
```

或者手动：

```bash
git clone https://github.com/Cyrene963/hermes-patches.git
cd hermes-patches
bash install.sh
```

## 包含的补丁

### 🔧 核心功能 (作者提交的 PR)

| # | 补丁 | 说明 | 状态 |
|---|------|------|------|
| 1 | Per-user session isolation | 多用户场景下 session_search 隔离 | PR #17989 |
| 2 | Per-user memory isolation | 多用户 memory 数据隔离 | PR #17989 |
| 3 | Semantic skill retrieval (FTS5) | 用 SQLite FTS5 实现语义技能检索 | PR #18316 |
| 4 | Hybrid skill selector | 混合模式：规则+模式+AI推断，节省 99.2% token | PR #18316 |
| 5 | Memory authority fix | 防止上下文压缩削弱 memory 权威性 | 已合并上游 |
| Skill enforcement | 技能执行纪律框架 | 强制 Agent 遵循技能规则 | PR #18849 |
| Skill enforcer plugin | 周期性合规检查插件 | 每8次工具调用触发合规检查 | PR #18849 |

### 🌐 社区 PR (精选 14 个 + 额外 2 个)

| PR | 说明 |
|----|------|
| #18547 | KV cache 稳定性：固定 system prompt 前缀 |
| #18582 | Gateway 重启时重载 .env 环境变量 |
| #18596 | 默认开启 secret redaction（安全加固） |
| #18600 | HERMES_HOME 未设置时抛出明确错误 |
| #18603 | summary_model 不可用时 fallback 到主模型 |
| #18607 | 紧急压缩：max_iterations 前自动压缩 |
| #18614 | Patch 幂等防护：防止重复应用 |
| #18616 | 支持 ZWJ emoji 在 context 文件中 |
| #18618 | Auxiliary client 传递 explicit_api_key |
| #18632 | /insights 显示 cache token 统计 |
| #18638 | Compressor 传递 threshold_percent 参数 |
| #18650 | 压缩时清理带图片的 tool messages |
| #18663 | 严格 API 模式下剥离 tool_calls extra_content |
| #18692 | session-search 剥离 FTS5 操作符 |
| #5447 | session_search FTS 匹配内容加载优化 |
| #7701 | 非阻塞后台 delegation（session_id 模式） |

## 使用说明

- **幂等安全**：已应用的补丁会自动跳过，可多次运行
- **hermes update 后**：更新会覆盖补丁，重新运行 `install.sh` 即可
- **回滚**：`cd ~/.hermes/hermes-agent && git reset --hard ORIG_HEAD`
- **选择性安装**：编辑 `patches/` 目录，删除不需要的 `.patch` 文件

## 与 hermes update 配合

建议在 `~/.bashrc` 中添加：

```bash
hermes() {
    if [ "$1" = "update" ]; then
        command hermes update "${@:2}"
        bash /path/to/hermes-patches/install.sh
    else
        command hermes "$@"
    fi
}
```

这样 `hermes update` 会自动重新打补丁。

## 许可

补丁来自 Hermes Agent 开源项目 (NousResearch/hermes-agent)，遵循原项目许可。
