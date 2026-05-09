# Hermes Agent 社区补丁合集

> 一键安装，补全上游尚未合并的修复和增强。已合并的补丁会自动跳过。

## 装有什么用？

**💰 省钱：每次对话省 99.2% token**
原版 Hermes 每次对话会把 160 个技能描述全部塞进 system prompt，白白浪费约 12000 token。打完补丁后只注入你真正需要的 1-3 个技能，token 消耗从 ~12000 降到 ~200。

**🔒 隐私：多用户不再互相泄露**
session_search 和 memory 按用户隔离，中文搜索(CJK trigram)也已修复。

**🧠 长对话不失忆**
上下文压缩不再削弱 memory 权威性，你设定的规则在整个会话期间持续生效。

**⚡ Agent 不再"跑偏"**
每 8 次工具调用自动触发合规检查，把 Agent 拉回正轨。

**🛡️ 安全防护 (18 个安全补丁)**
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

**🧠 Memory Metacognition Framework (NEW)**
可配置的记忆元认知框架，包含：
- Memory Index：session 开始时注入记忆库摘要
- Query Expansion：自动扩展用户消息为更好的 hindsight 搜索词
- Preflight Gate：高风险工具调用前的结构化参数校验
- Structured Checks：field_required / field_equals / field_not_equals / field_contains / field_not_contains
- 默认 no-op，不影响现有行为

## 一行命令安装

```bash
bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
```

## 兼容性说明

**上游合并状态**（2026-05-09 测试）：

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
- 18 个安全补丁（文件/网络/环境防护）
- Skill Pre-selection Auto-context Injection
- Memory Metacognition Framework (PR #22516)

## 包含的补丁 (49 个)

### 核心功能 (15 个)

| # | 补丁文件 | 说明 | PR |
|---|---------|------|-----|
| 1 | `1_fix-preserve-memory-authority-across-context-compaction.patch` | 上下文压缩保留 memory 权威性 | [#17989](https://github.com/NousResearch/hermes-agent/pull/17989) |
| 2 | `2_feat-Add-hybrid-skill-selector-layer-A.patch` | 混合技能选择器 3 层筛选 | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) |
| 3 | `3_Apply-14-community-PRs--fix-session_search-ordering.patch` | 合并 14 个社区 PR | 社区 PR 合集 |
| 4 | `4_feat-Add-skill-enforcement-framework.patch` | 技能执行纪律框架 | [#18849](https://github.com/NousResearch/hermes-agent/pull/18849) |
| 5 | `5_featplugins-add-skill-enforcer-plugin-for-periodic-complianc.patch` | 合规检查插件 (每 8 次工具调用) | [#18849](https://github.com/NousResearch/hermes-agent/pull/18849) |
| 6 | `6_fix-preserve-credential-pool-through-_model-session-override.patch` | Credential pool /model 保持 | [#19064](https://github.com/NousResearch/hermes-agent/pull/19064) |
| 7 | `7_feat-pre-flight-thinking-block--fact-verification-gate-v2.patch` | Pre-flight thinking block | 本地实现 |
| 8 | `8_feat-auto-context-retrieval-replacing-regex-fact-verificatio.patch` | Agent 自动上下文检索 | 本地实现 |
| 9 | `9_feat-add-auto-setup-for-owner-detection--cross-channel-memor.patch` | 跨渠道记忆统一 + auto-setup | [#19163](https://github.com/NousResearch/hermes-agent/pull/19163) |
| 40 | `40_fix-enforce-user_id-filtering-in-session_search.patch` | 多用户 session_search 隔离 | [#17989](https://github.com/NousResearch/hermes-agent/pull/17989) |
| 41 | `41_feat-implement-skill-db-FTS5.patch` | SQLite FTS5 语义技能检索 | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) |
| 42 | `42_feat-skill-eval-gate-complete.patch` | Skill Evaluation Gate 完整版 | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) |
| 43 | `43_fix-cjk-user_id-and-switch_model-credential_pool.patch` | CJK 搜索隔离 + credential pool | 本地修复 |
| 44 | `44_feat-skill-eval-gate-integration.patch` | Skill Eval Gate 集成到 run_agent | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) |
| 45 | `45_overnight-evolution-bundle.patch` | Overnight evolution 综合补丁 | 夜间自动扫描合并 |
| mc | `memory-metacognition-framework.patch` | Memory Metacognition Framework | [#22516](https://github.com/NousResearch/hermes-agent/pull/22516) |

### Custom Provider 修复 (7 个)

| # | 补丁文件 | 说明 | PR |
|---|---------|------|-----|
| 10 | `10_fixauth-shorten-credential-401-cooldown.patch` | 缩短 401 认证失败冷却 | 本地修复 |
| 12 | `12_fixauth-stop-treating-CLAUDE_CODE_OAUTH_TOKEN-as-Anthropic-A.patch` | 不再误识别 OAuth token | 本地修复 |
| 14 | `14_fixcli-allow-custom-provider-slugs-in-model-validation.patch` | 允许 custom provider slugs | 本地修复 |
| 35 | `35_fix-extract-is_custom_provider-from-params.patch` | is_custom_provider 参数修复 | [#19686](https://github.com/NousResearch/hermes-agent/pull/19686) |
| 36 | `36_fix-transport-default-max_tokens-for-custom-providers.patch` | max_tokens 默认值修复 | [#19686](https://github.com/NousResearch/hermes-agent/pull/19686) |
| pr19682 | `pr19682-fix-credential-pool-key-ambiguity.patch` | Credential pool key 歧义修复 | [#19682](https://github.com/NousResearch/hermes-agent/pull/19682) |
| pr19685 | `pr19685-fix-cli-base_url-env-lookup.patch` | CLI base_url 环境变量查找 | [#19685](https://github.com/NousResearch/hermes-agent/pull/19685) |

### Gateway / 平台修复 (3 个)

| # | 补丁文件 | 说明 | PR |
|---|---------|------|-----|
| 21 | `21_fix-correct-indentation-in-webhook-auth-validation.patch` | Webhook 认证缩进修复 | 本地修复 |
| 31 | `31_fixagent-handle-string-context-compression-messages.patch` | 压缩消息字符串处理 | 本地修复 |
| pr19683 | `pr19683-fix-gateway-model-api-key.patch` | Gateway model API key 保持 | [#19683](https://github.com/NousResearch/hermes-agent/pull/19683) |

### 安全补丁 (18 个)

| # | 补丁文件 | 说明 |
|---|---------|------|
| 15 | `15_fix-validate-provider-credentials-before-auto-detection-1928.patch` | Provider 凭证验证 |
| 16 | `16_fixfile-safety-block-authjson-read-via-TERMINAL_CWD-relative.patch` | auth.json 相对路径读取阻止 |
| 17 | `17_fixsecurity-prevent-SSRF-bypass-for-IMDS-endpoints-in-browse.patch` | SSRF IMDS 防护 |
| 18 | `18_securityfile-safety-also-write-deny-root_env-when-running-un.patch` | .env 写入安全 |
| 19 | `19_fixsecurity-protect-Hermes-control-plane-files-from-prompt-i.patch` | 控制面板 prompt injection 防护 |
| 20 | `20_fixsecurity-add-code-level-guard-against-modifying-bundled_h.patch` | bundled skills 保护 |
| 22 | `22_fixurl_safety-block-IPv4-mapped-IPv6-addresses-to-prevent-SS.patch` | IPv4-mapped IPv6 SSRF 阻止 |
| 23 | `23_fixfile_tools-block-agent-writes-to-_hermes_configyaml-to-pr.patch` | config.yaml 写入阻止 |
| 24 | `24_test-use-realistic-fake-keys-to-exercise-mask-format-verific.patch` | Key mask 格式测试 |
| 25 | `25_fixagent-redact-secrets-in-request_dump_json-files.patch` | request_dump 脱敏 |
| 26 | `26_fixagent-redact-lowercase_dotted-config-keys-in-terminal-out.patch` | 低级配置键终端脱敏 |
| 27 | `27_fixsecurity-restore-env_authjson_statedb-with-0600-perms.patch` | 恢复文件 0600 权限 |
| 28 | `28_hermes-agent-Scrub-provider-creds-from-ACP-child-env.patch` | ACP 子进程凭证清理 |
| 29 | `29_fixsecurity-fail-closed-WebSocket-localhost-check-when-clien.patch` | WebSocket 空主机 fail-closed |
| 30 | `30_fixapproval-use-per-process-UUID-as-default-session-key-to-p.patch` | UUID 会话隔离 |
| 32 | `32_testgateway-add-unit-tests-for-_is_authorized_media_path-sec.patch` | 媒体路径安全测试 |
| 33 | `33_fixdiscord-scope-DISCORD_ALLOWED_ROLES-to-originating-guild-.patch` | Discord 角色限制到 guild |
| 34 | `34_fixsecurity-validate-snapshot_id-and-file-paths-in-restore_q.patch` | snapshot_id 路径遍历防护 |

### 其他 (6 个)

| # | 补丁文件 | 说明 |
|---|---------|------|
| 11 | `11_fixfile-strip-leaked-terminal-fences-from-reads.patch` | 终端 fence 泄露清理 |
| 13 | `13_fixmcp-reconnect-on-terminated-sessions.patch` | MCP 会话重连 |
| session-filter | `session-filter.patch` | Session 平台过滤器 |
| community-prs | `community-prs-combined.patch` | 社区 PR 合集 (旧版) |
| pr20758 | `pr20758-skill-pre-selection-auto-context.patch` | 技能预选自动上下文注入 |
| pr19064 | 包含在 #6 | /model credential pool 保持 |

## 配置文件

- `examples/memory_policy.example.yaml` — Memory Metacognition 脱敏配置模板
  复制到 `~/.hermes/memory_policy.yaml` 并自定义

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
