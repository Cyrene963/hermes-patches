# Hermes Agent 社区补丁合集

> 43 个精选未合并 PR，一键安装。装完立刻能感受到的变化：

## 装了有什么用？

**💰 省钱：每次对话省 99.2% token**
原版 Hermes 每次对话会把 160 个技能描述全部塞进 system prompt，白白浪费约 12000 token。打完补丁后只注入你真正需要的 1-3 个技能，token 消耗从 ~12000 降到 ~200。按 OpenRouter 价格算，一天聊 100 次能省几美元。

**🔒 隐私：多用户不再互相泄露**
你和朋友共用一个 Hermes bot？原版 session_search 会搜到所有人的对话，memory 也会互相污染。打完补丁后每个用户的数据完全隔离，搜"我的密码"只返回自己的记录。中文搜索(CJK trigram)也已修复隔离。

**🧠 长对话不失忆**
原版 Hermes 聊久了之后上下文压缩会把你的偏好和规则标记为"后台参考"，LLM 就开始忽略它们。打完补丁后 memory 权威性受到保护，你设定的规则在整个会话期间持续生效。

**⚡ Agent 不再"跑偏"**
原版 Agent 执行长任务时容易忘记之前的规则，开始幻觉或违规操作。打完补丁后每 8 次工具调用自动触发一次合规检查，把 Agent 拉回正轨。

**🛡️ 安全和稳定性 (16个安全补丁)**
- 默认开启 secret redaction，API key 不会意外泄露到日志
- KV cache 稳定性优化，减少偶发崩溃
- 紧急压缩机制，max_iterations 前自动瘦身防止中途挂掉
- Gateway 重启时自动重载 .env，不用手动重启整个服务
- SSRF 防护：阻止 IPv4-mapped IPv6 绕过和 IMDS 端点访问
- 文件安全：阻止 agent 写入 config.yaml、auth.json 等敏感文件
- 环境安全：.env/auth.json/state.db 恢复时强制 0600 权限

**🔧 后台任务不阻塞**
原版派 Agent 去干重活时你得干等。打完补丁后后台 delegation 不阻塞主对话，你可以继续聊别的。

**🔗 跨渠道记忆统一**
你在 Telegram 和 CLI 上跟 Hermes 聊天，原版两边的记忆是分裂的。打完补丁后同用户的记忆自动互通，`auto-setup` 一键检测 owner 并设置好 symlink。

**🧠 Agent 自动获取上下文**
原版 Agent 需要自己决定要不要搜索历史记忆——它经常不搜，直接凭上下文瞎答。打完补丁后系统每轮自动搜索 hindsight + session 历史，把相关上下文以 system message 注入（注意力权重更高，不容易忽略），模型不再需要"记得去查"。

**🔧 Custom Provider 兼容性**
原版 Hermes 对自定义 provider 的参数处理有多个 bug：is_custom_provider 被错误消费、max_tokens 缺少默认值、base_url 环境变量查找失败、credential pool key 冲突。打完补丁后自定义 provider 稳定工作。

## 一行命令安装

```bash
bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
```

或者手动：

```bash
git clone https://github.com/Cyrene963/hermes-patches.git
cd hermes-patches
bash install.sh
```

## 包含的补丁

### 核心功能 (14个)

| 补丁 | 说明 | PR |
|------|------|-----|
| 多用户 session/memory 隔离 | session_search 和 memory 按用户隔离，含 CJK trigram 修复 | [#17989](https://github.com/NousResearch/hermes-agent/pull/17989) |
| 语义技能检索 (FTS5) | SQLite FTS5 全文索引替代暴力注入，160个skill索引 | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) |
| 混合技能选择器 | 3层筛选(快速规则→任务模式→FTS5)，25种任务类型，零关键词匹配 | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) |
| Skill Evaluation Gate | 代码强制agent在第一次action前评估skill，pre_tool_call hook阻断 | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) |
| CJK 搜索 user_id 隔离 | 中文搜索(trigram/LIKE)路径也走 user_id 过滤，修复安全漏洞 | 本地修复 |
| 修复轮换池丢弃 | /model 切换不再丢弃 credential pool，轮换机制正常工作 | [#19064](https://github.com/NousResearch/hermes-agent/pull/19064) |
| Memory 权威性保护 | 防止上下文压缩削弱 memory | 上游已合并 |
| 技能执行纪律框架 | Agent 必须遵循已加载的技能规则 | [#18849](https://github.com/NousResearch/hermes-agent/pull/18849) |
| 合规检查插件 | 每 8 次工具调用触发合规检查 | [#18849](https://github.com/NousResearch/hermes-agent/pull/18849) |
| 跨渠道记忆统一 | 同用户 Telegram/CLI/Discord 记忆互通，支持自动检测 owner | [#19163](https://github.com/NousResearch/hermes-agent/pull/19163) |
| 自动上下文检索 | 每轮自动搜索 hindsight + session 历史，system message 注入 | [#19200](https://github.com/NousResearch/hermes-agent/pull/19200) |
| Custom Provider 参数修复 | is_custom_provider 提取 + max_tokens 默认值 | [#19686](https://github.com/NousResearch/hermes-agent/pull/19686) |
| Credential Pool Key 修复 | 修复 credential pool key 歧义导致的轮换失败 | [#19682](https://github.com/NousResearch/hermes-agent/pull/19682) |
| Gateway Model API Key | 修复 gateway 切换 model 时 API key 丢失 | [#19683](https://github.com/NousResearch/hermes-agent/pull/19683) |
| CLI base_url 环境变量 | 修复 CLI 自定义 base_url 环境变量查找失败 | [#19685](https://github.com/NousResearch/hermes-agent/pull/19685) |

### 社区精选 16 个 PR（保持不变）

| PR | 说明 |
|----|------|
| [#18547](https://github.com/NousResearch/hermes-agent/pull/18547) | KV cache 稳定性：固定 system prompt 前缀 |
| [#18582](https://github.com/NousResearch/hermes-agent/pull/18582) | Gateway 重启时重载 .env 环境变量 |
| [#18596](https://github.com/NousResearch/hermes-agent/pull/18596) | 默认开启 secret redaction |
| [#18600](https://github.com/NousResearch/hermes-agent/pull/18600) | HERMES_HOME 未设置时抛出明确错误 |
| [#18603](https://github.com/NousResearch/hermes-agent/pull/18603) | summary_model 不可用时 fallback 到主模型 |
| [#18607](https://github.com/NousResearch/hermes-agent/pull/18607) | 紧急压缩：max_iterations 前自动压缩 |
| [#18614](https://github.com/NousResearch/hermes-agent/pull/18614) | Patch 幂等防护：防止重复应用 |
| [#18616](https://github.com/NousResearch/hermes-agent/pull/18616) | 支持 ZWJ emoji 在 context 文件中 |
| [#18618](https://github.com/NousResearch/hermes-agent/pull/18618) | Auxiliary client 传递 explicit_api_key |
| [#18632](https://github.com/NousResearch/hermes-agent/pull/18632) | /insights 显示 cache token 统计 |
| [#18638](https://github.com/NousResearch/hermes-agent/pull/18638) | Compressor 传递 threshold_percent 参数 |
| [#18650](https://github.com/NousResearch/hermes-agent/pull/18650) | 压缩时清理带图片的 tool messages |
| [#18663](https://github.com/NousResearch/hermes-agent/pull/18663) | 严格 API 模式下剥离 tool_calls extra_content |
| [#18692](https://github.com/NousResearch/hermes-agent/pull/18692) | session-search 剥离 FTS5 操作符 |
| [#5447](https://github.com/NousResearch/hermes-agent/pull/5447) | session_search FTS 匹配内容加载优化 |
| [#7701](https://github.com/NousResearch/hermes-agent/pull/7701) | 非阻塞后台 delegation（session_id 模式） |

### 安全补丁 (13个)

| 补丁 | 说明 |
|------|------|
| 缩短 401 cooldown | 减少认证失败后的等待时间 |
| 剥离 read_file 泄露的 terminal fences | 防止文件读取结果泄露终端标记 |
| 修复 CLAUDE_CODE_OAUTH_TOKEN 识别 | 不再错误地把 OAuth token 当 Anthropic key |
| MCP 会话过期重连 | MCP 工具会话过期时自动重连 |
| CLI 自定义 provider slugs | 允许 CLI 使用自定义 provider 别名 |
| Provider 凭证预验证 | 自动检测前先验证凭证有效性 |
| auth.json 读取安全 | 阻止通过 TERMINAL_CWD 相对路径读取 |
| SSRF IMDS 防护 | 阻止访问云实例元数据端点 |
| .env 写入安全 | 运行时阻止写入 root_env |
| 控制面板文件保护 | 防止 prompt injection 修改 dashboard 文件 |
| bundled_helms 保护 | 代码级阻止修改内置技能 |
| Webhook 验证缩进修复 | 修复 webhook 认证的缩进错误 |
| IPv4-mapped IPv6 SSRF | 阻止通过 IPv6 映射地址绕过 SSRF 防护 |
| config.yaml 写入阻止 | 阻止 agent 写入 config.yaml 绕过审批 |
| 真实假密钥测试 | 使用真实格式的假密钥验证脱敏逻辑 |
| request_dump 脱敏 | 调试 dump 文件中脱敏 API keys |
| 低级配置键脱敏 | 终端输出中脱敏 dotted config keys |
| .env 权限恢复 | 恢复 .env/auth.json 时强制 0600 权限 |
| ACP 子进程环境清理 | ACP 子进程不再继承 provider 凭证 |
| WebSocket 空主机检查 | 空 client_host 时 fail-closed |
| UUID 会话隔离 | approval 使用 per-process UUID 防止跨会话泄露 |
| 字符串压缩消息处理 | 修复 context compressor 的字符串消息处理 |
| Gateway 媒体路径安全测试 | 针对媒体路径安全边界的单元测试 |
| Discord 角色范围限制 | DISCORD_ALLOWED_ROLES 限定到发起 guild |
| snapshot_id 路径遍历 | 验证 snapshot_id 和文件路径防止遍历攻击 |

## 兼容性说明

**补丁对最新 upstream 的适用性**（2026-05-05 测试）：
- 23/43 个补丁可直接 apply 到最新 upstream/main
- 10/43 个补丁因上游代码更新而有冲突（需要重新生成）
- 其余为本地修复或新增功能补丁

如果你的 hermes-agent 版本较新，部分补丁可能已合并或冲突。install.sh 会自动跳过已应用的补丁，并报告冲突。

## 使用说明

- **幂等安全**：已应用的补丁自动跳过，可多次运行
- **hermes update 后**：更新会覆盖补丁，重新运行 `install.sh` 即可
- **回滚**：`cd ~/.hermes/hermes-agent && git reset --hard ORIG_HEAD`
- **选择性安装**：删除 `patches/` 目录下不需要的 `.patch` 文件

## 与 hermes update 配合

在 `~/.bashrc` 中添加：

```bash
hermes() {
    if [ "$1" = "update" ]; then
        command hermes update "${@:2}"
        bash ~/hermes-patches/install.sh
    else
        command hermes "$@"
    fi
}
```

## 许可

补丁来自 Hermes Agent 开源项目 (NousResearch/hermes-agent)，遵循原项目许可。
- - - -
友链：**[Linux Do](https://linux.do/)**
本项目亦在Linux Do社区中发布相关帖子。感谢佬友雪中送炭的Token哈哈~
