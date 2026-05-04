# Hermes Agent 社区补丁合集

> 一键安装，补全上游尚未合并的修复和增强。已合并的补丁会自动跳过。

## 装了有什么用？

**💰 省钱：每次对话省 99.2% token**
原版 Hermes 每次对话会把 160 个技能描述全部塞进 system prompt，白白浪费约 12000 token。打完补丁后只注入你真正需要的 1-3 个技能，token 消耗从 ~12000 降到 ~200。

**🔒 隐私：多用户不再互相泄露**
session_search 和 memory 按用户隔离，中文搜索(CJK trigram)也已修复。

**🧠 长对话不失忆**
上下文压缩不再削弱 memory 权威性，你设定的规则在整个会话期间持续生效。

**⚡ Agent 不再"跑偏"**
每 8 次工具调用自动触发合规检查，把 Agent 拉回正轨。

**🛡️ 安全防护 (16个安全补丁)**
- SSRF 防护：阻止 IPv4-mapped IPv6 绕过和 IMDS 端点访问
- 文件安全：阻止 agent 写入 config.yaml、auth.json 等敏感文件
- Secret redaction：API key 不会意外泄露到日志和调试文件
- 环境安全：.env/auth.json/state.db 恢复时强制 0600 权限

**🔧 Custom Provider 兼容性**
修复自定义 provider 的多个 bug：is_custom_provider 参数、max_tokens 默认值、base_url 环境变量、credential pool key。

**🔗 跨渠道记忆统一**
Telegram/CLI/Discord 记忆互通，`auto-setup` 一键检测 owner。

**🧠 Agent 自动获取上下文**
每轮自动搜索 hindsight + session 历史，system message 注入。

## 一行命令安装

```bash
bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
```

## 兼容性说明

**上游合并状态**（2026-05-05 测试）：

上游在最近几周合并了大量社区贡献，包括：
- Pre-flight thinking block
- Auto-context retrieval (hindsight + session_search)
- 14 community PRs (KV cache, secret redaction, emergency compression 等)
- Multi-user session/memory isolation
- Custom provider slugs
- MCP reconnect
- Backup 0600 permissions

这些功能已内置在最新版 Hermes 中。install.sh 会自动检测并跳过已合并的补丁。

**仍需本补丁集的修复**：
- IPv4-mapped IPv6 SSRF 防护
- Credential pool /model 切换保持
- CJK 搜索 user_id 隔离
- SkillDB FTS5 语义检索
- Skill Evaluation Gate
- 16 个安全补丁（文件/网络/环境防护）

## 包含的补丁

### 核心功能

| 补丁 | 说明 | PR | 状态 |
|------|------|-----|------|
| 多用户 session/memory 隔离 | session_search 和 memory 按用户隔离 | [#17989](https://github.com/NousResearch/hermes-agent/pull/17989) | ✅ 未合并 |
| 语义技能检索 (FTS5) | SQLite FTS5 全文索引 | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) | ✅ 未合并 |
| 混合技能选择器 | 3层筛选(快速规则→任务模式→FTS5) | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) | ✅ 未合并 |
| Skill Evaluation Gate | 代码强制评估skill | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) | ✅ 未合并 |
| CJK 搜索隔离 | 中文搜索也走 user_id 过滤 | 本地修复 | ✅ 未合并 |
| Credential Pool 修复 | /model 切换保持 credential pool | [#19064](https://github.com/NousResearch/hermes-agent/pull/19064) | ✅ 未合并 |
| IPv4-mapped IPv6 SSRF | 阻止 ::ffff:x.x.x.x 绕过 | 本地修复 | ✅ 未合并 |
| 技能执行纪律框架 | Agent 必须遵循已加载的技能规则 | [#18849](https://github.com/NousResearch/hermes-agent/pull/18849) | ✅ 未合并 |
| 合规检查插件 | 每 8 次工具调用触发合规检查 | [#18849](https://github.com/NousResearch/hermes-agent/pull/18849) | ✅ 未合并 |
| 跨渠道记忆统一 | 同用户多平台记忆互通 | [#19163](https://github.com/NousResearch/hermes-agent/pull/19163) | ✅ 未合并 |
| Custom Provider 修复 | is_custom_provider + max_tokens | [#19686](https://github.com/NousResearch/hermes-agent/pull/19686) | ✅ 未合并 |
| Credential Pool Key | 修复 pool key 歧义 | [#19682](https://github.com/NousResearch/hermes-agent/pull/19682) | ✅ 未合并 |
| Gateway API Key | 切换 model 时 API key 保持 | [#19683](https://github.com/NousResearch/hermes-agent/pull/19683) | ✅ 未合并 |
| CLI base_url | 环境变量查找修复 | [#19685](https://github.com/NousResearch/hermes-agent/pull/19685) | ✅ 未合并 |

### 安全补丁

| 补丁 | 说明 |
|------|------|
| 缩短 401 cooldown | 减少认证失败等待 |
| CLAUDE_CODE_OAUTH 修复 | 不再误识别 OAuth token |
| auth.json 读取安全 | 阻止相对路径读取 |
| SSRF IMDS 防护 | 阻止访问云实例元数据 |
| .env 写入安全 | 运行时阻止写入 |
| 控制面板保护 | 防止 prompt injection |
| bundled skills 保护 | 代码级阻止修改 |
| config.yaml 写入阻止 | 阻止绕过审批 |
| request_dump 脱敏 | 调试文件脱敏 |
| 低级配置键脱敏 | 终端输出脱敏 |
| ACP 环境清理 | 子进程不继承凭证 |
| WebSocket 安全 | 空主机 fail-closed |
| UUID 会话隔离 | 防止跨会话泄露 |
| 压缩消息处理 | 字符串消息修复 |
| Discord 角色限制 | 限定到发起 guild |
| snapshot_id 验证 | 防止路径遍历 |

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
