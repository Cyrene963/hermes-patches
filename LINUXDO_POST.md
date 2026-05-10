# Hermes Agent 社区补丁合集 — 一键应用 20 个未合并 PR

## 背景

Hermes Agent 是 NousResearch 开源的 AI Agent 框架（127k+ star），功能强大但社区 PR 合并速度较慢。

我从 4860+ 个开放 PR 中筛选了 14 个实用的社区 PR，加上自己提交的 3 个 PR（多用户隔离 + 混合技能检索 + 技能执行纪律），一共打包了 **20 个补丁**，写了个一键安装脚本分享给大家。

## 亮点功能

### 🧠 混合技能检索（PR #18316）— 节省 99.2% Token

原版 Hermes 会把所有技能描述注入 system prompt（124 个技能 × 每条消息），浪费大量 token。

混合模式三层检索：
1. **规则层**：正则匹配明确指令（"用 spotify 播放..."）
2. **模式层**：SQLite FTS5 关键词匹配
3. **AI 推断层**：仅在前两层无结果时调用

实测：平均每个消息只注入 1.03 个技能，token 消耗从 ~12000 降到 ~800。

### 🔒 多用户隔离（PR #17989）

多个用户共享一个 Hermes 实例时，session_search 和 memory 会互相串数据。这个补丁彻底隔离了用户数据。

### ⚡ 社区精选 16 个 PR

包括：
- KV cache 稳定性优化
- Gateway 重启时重载 .env
- 默认开启 secret redaction（安全加固）
- 紧急压缩防止 agent 中途崩溃
- session_search FTS5 修复
- 非阻塞后台 delegation
- 等等...

## 一行命令安装

```bash
bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
```

## 仓库地址

https://github.com/Cyrene963/hermes-patches

## 使用说明

- 幂等安全，已应用的补丁自动跳过
- `hermes update` 后重新运行即可恢复
- 可选择性安装，删除 `patches/` 目录下不需要的 `.patch` 文件
- 回滚：`cd ~/.hermes/hermes-agent && git reset --hard ORIG_HEAD`

## 与 hermes update 配合

`hermes update` 会把本地源码更新到上游最新版本，可能覆盖本补丁集。建议给 `hermes update` 加一个 shell wrapper：先正常更新，再自动重新运行补丁安装脚本。

### 临时使用（无需本地克隆）

如果你是直接用一行命令安装补丁，可以把下面内容加入 `~/.bashrc` 或 `~/.zshrc`：

```bash
hermes() {
    if [ "$1" = "update" ]; then
        command hermes update "${@:2}"
        bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
    else
        command hermes "$@"
    fi
}
```

### 本地克隆使用（可选择性删补丁）

如果你已经把仓库克隆到 `~/hermes-patches`，想保留/删除某些 `.patch` 后再安装，用这个版本：

```bash
hermes() {
    if [ "$1" = "update" ]; then
        command hermes update "${@:2}"
        git -C ~/hermes-patches pull --ff-only
        bash ~/hermes-patches/install.sh
    else
        command hermes "$@"
    fi
}
```

添加后执行 `source ~/.bashrc` 或 `source ~/.zshrc` 生效。以后运行 `hermes update` 时，会自动在更新完成后重新打补丁。

## 补丁列表

| 补丁 | 说明 |
|------|------|
| #17989 | 多用户 session/memory 隔离 |
| #18316 | 混合技能检索（FTS5 + AI 推断） |
| #18849 | 技能执行纪律框架 + 插件 |
| #18547 | KV cache 稳定性 |
| #18582 | Gateway 重启重载 .env |
| #18596 | 默认开启 secret redaction |
| #18600 | HERMES_HOME 未设置报错 |
| #18603 | summary_model fallback |
| #18607 | 紧急压缩 |
| #18614 | Patch 幂等防护 |
| #18616 | ZWJ emoji 支持 |
| #18618 | Auxiliary api_key 传递 |
| #18632 | /insights cache token |
| #18638 | Compressor threshold |
| #18650 | 压缩清理 tool messages |
| #18663 | tool_calls extra_content |
| #18692 | session-search FTS5 操作符 |
| #5447 | session_search FTS 内容加载 |
| #7701 | 非阻塞后台 delegation |
| Memory fix | memory 权威性保护 |

欢迎试用反馈 🎉
