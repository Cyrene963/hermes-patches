# Hermes Agent 社区补丁合集

> 一键安装，补全上游尚未合并的修复和增强。已合并的补丁会自动跳过。
>
> **适配状态：2026-06-07：已适配 Hermes Agent v0.16.0 / `v2026.6.5` 后的官方 `upstream/main`。** 本仓库只补充尚未进入官方 Hermes 的 Memory OS / Memory Graph / 检索与安全门控相关能力；官方已内置的功能不会冒充为补丁成果。当前发布版已在 clean upstream worktree 与本机运行环境中验证：installer 可应用、关键 Python 模块可 import、Memory Graph 14 个工具已注册、focused regression 通过、Memory Graph create → search → delete canary 通过、gateway 重启后加载成功。README 按 `Verified / Partially verified / Risk` 标注证据，不把“文件存在”写成“功能已跑通”。**

## 装有什么用？

**🏗️ 借鉴成熟 Agent Harness 架构，提升 Harness 能力**
同一模型在不同 Agent 下表现差距巨大，本质原因就是 harness（任务规划、工具调用、上下文管理、错误恢复的工程架构）。本补丁吸收了成熟 coding-agent / harness 系统的通用工程模式，并以可验证、可配置、可回退的方式移植到 Hermes Agent：
- **User Context / System Prompt 分离**：记忆、技能、规则注入到 user message 而非 system prompt → 压缩后保留更高注意力权重，prefix cache 命中率更高
- **Token Budget 三层防御**：单工具 50K 上限 → 超大输出自动落盘替换为 2KB 预览 → 单轮 200K 总预算
- **Goal 系统借鉴 Codex /goal**：model-based judge（fail-closed 设计）、anti-laziness（3 轮空转自动暂停）、90% budget wrap-up steering

**🧠 借鉴腾讯/混元类分层记忆架构（架构启发，不是复制实现）**
本补丁的 Memory OS 设计吸收了成熟长期记忆系统的通用模式：把“长期事实、原始证据、运行规则、执行门控”分层，而不是把所有内容粗暴塞进 prompt。对应到本补丁的已验证/边界如下：
- **结构化长期记忆**：Memory Graph 存 canonical facts，支持 create → search → read/delete canary 验证；`core://` 是 domain，不等于共享 namespace。
- **原始证据库**：Hindsight 作为历史证据/召回后备，不把 recall 命中直接当 canonical truth。
- **运行规则层**：`MEMORY.md` / policy YAML 只放高频规则和工具门控，避免 L1 bloating。
- **工具前执行门控**：Memory Preflight Gate 在工具 dispatch 前检查参数；已验证 `web_extract linux.do`、`send_message MEDIA:`、`terminal linux.do/t` 可阻断，`.json` Discourse endpoint 例外可放行。
- **谨慎边界**：不声称存在完整“腾讯同款/混元同款”产品能力；这里只说明架构启发和当前 Hermes patch 的可验证实现面。

**🧠 记忆元认知框架**
明明上次踩过的坑记下来了，下次换个说法问同样的错再犯一遍？根本原因是模型有记忆但不知道自己记得什么。这次补丁从工程层强制约束：
- **不再失忆**：session 启动时自动注入记忆库摘要，不用等用户问才想起来
- **搜得更准**：你说"改一下配置"，它不只搜"配置"，还会自动搜 config.yaml、provider、gateway 等相关记忆
- **拦得住**：不是靠模型"自觉"，是系统在工具调用前强制检查参数（MEDIA 标签 → 阻止、gateway restart → 警告、注入模式 → 阻止）
- 默认开启，可在 `~/.hermes/memory_policy.yaml` 中自定义或关闭

**🔮 记忆检索与披露（已验证部分 + 实验部分）**
从架构层降低“有记忆但不会用”的概率：
- **已接入**：记忆摘要/策略路由、Hindsight fallback、Memory Graph 搜索、Shadow Write 日志。
- **谨慎表述**：`disclosure_router.py`、access tracker/reranker 等辅助模块可能作为 overlay 存在；只有经过 import+调用链+端到端验证的路径才算运行功能。
- **不再夸大**：不声称存在完整自动“记忆衰减引擎”或所有记忆自动注入 system prompt，除非对应运行链路被验证。

**🧠 Memory Graph 工具集（14 个工具）**
结构化长期记忆系统，替代 Hindsight 盲搜：
- `memory_graph_search` — 全文搜索记忆节点
- `memory_graph_read/create/update/delete` — CRUD 操作
- `memory_graph_list` — 列出子节点
- `memory_graph_alias` — 创建别名 URI
- `memory_graph_glossary_add/scan` — 术语管理
- `memory_graph_recall` — 记忆召回
- `memory_graph_orphans/purge` — 清理管理
- `memory_graph_diagnostics` — 系统诊断
- `memory_graph_random` — 随机记忆

**⚡ 混合技能选择器（3 层筛选）**
原版每次对话把所有技能描述塞进 system prompt，浪费大量 token。3 层筛选：
- **Layer 1 manifest/metadata 约束**：读取技能的结构化 `metadata.hermes.skill_routing`，先满足 mandatory/required_when 规则（0 token，fail-closed）
- **Layer 2 deterministic 候选召回**：用轻量 lexical overlap 只做候选集压缩，不作为最终语义判断
- **Layer 3 semantic reranker（可配置）**：候选不足或需要排序时走模型/语义 rerank；失败时保留 mandatory 技能并降级为 deterministic 结果
- 目标是减少无关技能注入，同时保证必须技能在首 token 前加载；README 不把 lexical matching 写成最终语义判定机制

**🔍 Search-as-Code / deep_research 联网研究管线**
本补丁补上了比普通 `web_search` 更强的证据构建路径：
- **Search-as-Code lane**：`deep_research(mode="code_plan")` 会生成受限 Python 检索计划，抓取/抽取来源，输出 `evidence.json`、`evidence.md`、`manifest.json`，并运行 privacy scan。
- **Unified auto lane**：`deep_research(mode="auto")` 优先跑 Search-as-Code 结构化证据侧车，同时保留 classic smart-search 作为独立补充/回退。
- **真实验证状态**：2026-06-03 CLI dogfood 中，`mode=auto` 和 `mode=code_plan` 都返回 `overall_status=Verified working`；`code_plan` 路径 privacy scan PASS。
- **边界**：reviewer lane 只有在显式 `review=true` 且 reviewer credential 可用时才算外部审查；route smoke 不等于 reviewer approval。

**🧩 官方 Kanban / multi-agent 能力说明**
Kanban 多任务板、swarm、dispatcher/worker、runs/heartbeat 等属于 Hermes Agent v0.16.0 官方上游能力，不是本补丁新增功能。本补丁仓库只保留一个维护边界：如果你用官方 Kanban 并行审计本补丁链，同一个 runtime / patch checkout 上仍建议只允许一个 writer，避免多个 agent 同时改 overlay、README 或 installer。

**🧭 安装后的加载边界**
Hermes 有多个运行进程。安装补丁后，新的 CLI/Python 进程会重新 import 已更新的文件；已经在运行的 gateway / Telegram worker 需要重启后才会加载 Python 代码变更。本文档的验证表会区分 clean install、new process smoke 与 gateway-loaded state，避免把源码存在误写成线上已生效。

**🛡️ 技能评估门控 + 合规检查（实验/未完全验证）**
- **Skill Evaluation Gate**：概念上要求 agent 在关键操作前评估相关技能；当前只能保证 `skill_view()` 可用，不能宣称已在所有路径强制生效。
- **skill-enforcer 插件**：曾用于实验性周期检查；当前 README 不再把它写成稳定已启用能力。
- **Fact Verification Gate**：属于构想/实验性策略，不应写成已部署功能。

**🧠 长对话不失忆**
上下文压缩不再削弱 memory 权威性。SUMMARY_PREFIX 重写为 ACTIVE/MANDATORY/BINDING 语言，你设定的规则在整个会话期间持续生效。

**🔒 多用户三层隔离**
- **Graph namespace**：长期事实按用户隔离
- **Hindsight bank**：原始对话证据按用户独立 bank 隔离
- **Per-user MEMORY.md**：操作规则按用户隔离
- session_search 在群/共享上下文有防泄漏限制；工具层隔离回归和 clean upstream installer smoke 已验证。DB FTS 查询级 `user_id` scope 与 chat/thread 级边界仍需按具体平台入口继续做 E2E 验证。

**🔧 Custom Provider 兼容性**
修复自定义 provider 的多个 bug：is_custom_provider 参数、max_tokens 默认值、base_url 环境变量、credential pool key。新增 `custom_providers[].default_headers` 透传：同一份 provider header 元数据会进入主聊天、auxiliary/switch/review 等运行路径，避免“直连接口可用，但 Hermes 真实路径丢 header 后 403”的体验不一致。

**🔗 跨渠道记忆统一**
Telegram/CLI 记忆路径已在本机使用；Discord 等第三方渠道取决于实际 adapter/config，未配置或未做 E2E 时只能视为 Code present only / Risk。`auto-setup` owner 检测属于安装/配置辅助能力，需按具体部署验证。

**🔍 Hindsight 增强**
- **Reranker / Access Tracker**：overlay 文件存在；是否在当前运行路径实际接入必须以 import+调用链+E2E 日志验证为准，未验证时只标为 Code present only
- **Shadow Write Logger**：已接入 conversation loop 的 post-turn shadow/limited-auto 审计路径，需通过 shadow 日志与回归测试验证


## 当前版本实测摘要（2026-06-07）

本仓库 README 只按真实 dogfood 结果宣传功能，不把“文件存在”写成“功能已跑通”：

| 功能面 | 当前证据标签 | 验证依据 |
|---|---|---|
| overlay-first installer（后端/工具） | Verified working | 在 Hermes Agent v0.16.0 / `v2026.6.5` 后的官方 `upstream/main` clean worktree 上运行 `install.sh`；py_compile/import/tool registration smoke 通过；本机 live runtime 重打 overlay 后 focused regression 通过 |
| Memory Graph 工具 | Verified working | 14 个工具注册；实际 create → search top hit → delete；删除后生成 URI 不再出现 |
| Memory Preflight Gate | Verified working | `web_extract` linux.do、`send_message` MEDIA、`terminal` linux.do 均被阻断；GitHub URL 放行 |
| Search-as-Code / deep_research | Verified working | `deep_research(mode="code_plan")` 与 `mode="auto"` 均返回 `overall_status=Verified working`，生成 run_dir/manifest/evidence |
| session_search | Verified working | 真实工具函数按 query 返回 session_id/results；继续要求按平台入口验证 user/source scope |
| 官方 Kanban CLI/DB surface | Upstream feature, not patch claim | Kanban 多任务板和 swarm/dispatcher/worker 属于 Hermes Agent v0.16.0 官方功能；本补丁 README 只说明补丁链维护时的单-writer 安全边界，不把它列为补丁成果 |
| Gateway loaded state | Verified working | 本机 gateway 已在重打 overlay 后重启并验证新进程 active；外部安装者仍需在安装后重启自己的 gateway 才能加载 Python 代码变更 |
| WebUI source / build / browser | Partially verified | 历史上曾通过 targeted patch 修复 Sessions 渠道筛选和 Models 首屏 fallback；当前 v0.16.0 官方 Dashboard 变化较大，本补丁默认不把官方 WebUI 功能宣称为补丁成果。若启用 dashboard overlay，请以 clean build、served bundle hash、浏览器 smoke 和 protected API probe 为准。|
| ReviewProposal / Memory Graph review 闭环 | Verified for current hardening slice | `/review` WebUI 已验证候选详情显示 `Approval eligibility`、`Readback`、`Rollback`；approve/reject/readback/rollback 路径有 focused tests 与 live smoke。边界：这表示 review 工作流可用，不代表所有 pending proposal 已经人工审批。|

## 一行命令安装

```bash
bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
```

### 安装前提和自动检查

`install.sh` 不是只复制文件。它会先运行 `scripts/hermes-patch-env-preflight.py` 做本机预检：

- 必须项：`HERMES_HOME` / `~/.hermes/hermes-agent` 是真实 Hermes repo，且存在 `toolsets.py`
- 基础命令：`git`、`python3`、`curl`
- Python 运行依赖：`bcrypt`、`jieba`、`asyncpg`、`ahocorasick`
- profile 配置：`~/.hermes/.env`，必要时生成 `MEMORY_GRAPH_DB_PASSWORD`
- 数据库/服务面：PostgreSQL `5432`、Memory Graph `127.0.0.1:8900/health`、Hindsight `127.0.0.1:9177/health`
- 可选能力：`psql`/`sudo` 用于自动初始化 `mg_app` 最小权限 DB role；`systemctl` 用于安装/启动 Memory Graph service/watchdog；`npm` 用于 ast-grep 或 dashboard rebuild

缺失必需项时 installer 会停止并打印修复步骤；缺失可选项时继续安装补丁文件和工具注册，但对应能力会标为 degraded/warn，需要按提示补装或手动配置。

常见全新机器流程：

```bash
# 1. 先安装官方 Hermes Agent，并完成 hermes setup / profile 配置
# 2. 如需 Memory Graph/Hindsight，先准备 PostgreSQL/Hindsight 服务和 profile .env
# 3. 运行本补丁 installer
bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
# 4. 如果已有 gateway 正在跑，重启以加载 Python 代码变更
hermes gateway restart
```

安装后可手动复查：

```bash
~/.hermes/scripts/hermes-patch-env-preflight.py
~/.hermes/scripts/hermes-patch-chain-guard.sh
curl -fsS http://127.0.0.1:8900/health
curl -fsS http://127.0.0.1:9177/health
```

## 兼容性说明

**上游合并状态**（2026-06-04 复查：官方最新 release 为 v0.15.2 / v2026.5.29.2；本补丁 installer 已在该 release tag 的 clean worktree 上验证后端/工具 overlay、WebUI build、Dashboard API/browser dogfood；陈旧 WebUI source overlays 已移除以避免覆盖官方 Dashboard 源码）：

上游在最近几周合并了大量社区贡献，包括：
- Pre-flight thinking block
- Auto-context retrieval (hindsight + session_search)
- 14 community PRs (KV cache, secret redaction, emergency compression 等)
- Multi-user session/memory isolation
- Custom provider slugs
- MCP reconnect
- Backup 0600 permissions
- Secret redaction by default
- Context compression summary redaction

这些功能已内置在最新版 Hermes 中。install.sh 会自动检测并跳过已合并的补丁。

**仍需本补丁集的修复**：
- Memory Metacognition Framework（预检门控 + 策略路由）
- 记忆检索与披露已验证部分 / 实验辅助模块
- Memory Graph 工具集（14 个工具）
- 混合技能选择器（3 层筛选）
- Skill Evaluation Gate（实验/未完全验证，不作为稳定能力宣传）
- Hindsight Reranker / Access Tracker
- Shadow Write Logger
- CJK 搜索 user_id 隔离
- Credential pool /model 切换保持
- Cron 多用户投递隔离
- Telegram 群聊 visible-but-ignored 上下文窗口（非全量历史回填）
- Telegram personal workspace 群：显式配置或 Bot API 实时验证“1 个已授权用户 + bot”的群，可像 CLI 多窗口一样免唤醒词触发；session/记忆归属授权用户，真实 Telegram 群 ID 独立保存用于回群投递
- ast-grep 结构化代码审计（补丁链 guard 集成；用于发现宽泛异常吞噬、硬编码私有路径/ID、空 catch 等高风险结构）

## 安装内容

通过 overlay-first `install.sh` 安装；旧的 monolithic combined patch 已不作为发布载体。`install.sh` 会先做环境预检，然后复制运行时 overlay、清理 `.pyc`、安装/初始化配置模板、注册 toolsets、安装 guard 脚本，并可用 `HERMES_INSTALL_SYSTEMD=0` / `HERMES_INSTALL_DB=0` 在临时 clean worktree 中做无 systemd/DB 副作用 smoke：

### 核心架构（借鉴 Claude Code）
- User Context / System Prompt 分离（prompt_builder.py）
- Token Budget 三层防御（50K/2KB/200K）
- Goal 系统增强（token budget + anti-laziness + wrap-up）

### 记忆系统
- Memory Metacognition Framework（预检门控 + 记忆注入 + 策略路由）
- 记忆检索与披露（已验证运行链路 + 实验辅助模块；不再夸大为完整衰减引擎）
- Memory Graph 模块（db/services/web/tool，14 个已注册工具）
- Memory Write Pipeline（记忆写入流水线）
- Shadow Write Logger（记忆写入审计）
- Hindsight Reranker（搜索结果重排序）
- Hindsight Access Tracker（记忆访问追踪）
- 上下文压缩保留 memory 权威性（SUMMARY_PREFIX 重写）

### 技能系统
- 混合技能选择器（metadata/manifest → deterministic 候选召回 → 可配置 semantic reranker）
- Skill Evaluation Gate（实验性/未完全验证）
- FTS5 语义技能检索

### 多用户隔离
- session_search 群/共享上下文防泄漏限制；live runtime focused tests 已通过，clean upstream installer smoke 已验证 overlay 后注册。DB FTS 查询级 `user_id` scope 与 chat/thread 级过滤仍需结合具体平台入口做 E2E 验证
- Weixin 多用户隔离
- Hindsight bank 隔离
- Memory Graph namespace 隔离

### Custom Provider 修复
- is_custom_provider 参数修复
- max_tokens 默认值修复
- Credential pool key 歧义修复
- CLI base_url 环境变量查找
- `custom_providers[].default_headers` 透传到主聊天、auxiliary client、fallback/switch 路由；这是通用 provider 元数据机制，不硬编码某个私有 host

### 工具/平台修复
- session_search 工具增强
- toolsets.py 记忆工具集定义
- ast-grep 结构化代码审计：`scripts/hermes-ast-grep-audit.sh` + `ast-grep-rules/*.yml`，安装后集成到 patch-chain guard。默认只报告 warning，不阻断安装；需要硬阻断时设置 `AST_GREP_FAIL_ON_WARNINGS=1`。
- Telegram 群聊 visible-but-ignored context window：privacy mode 关闭后，普通群消息虽被 `require_mention` 忽略，也会进入短期同群/同 topic 缓存；下一次 @bot 时通过 `MessageEvent.channel_context` 注入。不是 Bot API 全量历史回填，Telegram 未送达的消息仍无法恢复。
- Telegram personal workspace group：当群被显式配置为 personal workspace，或运行时通过 Bot API 证明群里当前只有一个已授权 sender 加 Hermes bot 时，该群作为该用户的私聊/CLI 多窗口处理。普通文本无需 `@bot`、唤醒词、回复或 slash command；`SessionSource.chat_id` 保持授权用户 ID 以复用个人 session/记忆，`thread_id=group:<chat_id>[:topic]` 用于窗口隔离，真实 Telegram 群投递目标保存在 `parent_chat_id` 并由发送层派生，避免把内部 `group:<chat_id>` 标记传给 Telegram topic 参数。

#### Telegram 群上下文配置

```yaml
telegram:
  require_mention: true
  history_backfill: true          # 开启同群/同 topic 短期上下文注入；默认 false
  history_backfill_limit: 20      # 每次触发最多注入多少条；默认 20，0=关闭注入
  context_cache_limit: 100        # 每个 chat/topic 在内存中最多保留多少条可见消息；默认 100，0=关闭缓存
```

环境变量等价项：`TELEGRAM_HISTORY_BACKFILL`、`TELEGRAM_HISTORY_BACKFILL_LIMIT`、`TELEGRAM_CONTEXT_CACHE_LIMIT`。

边界：这只缓存 Telegram 已经投递给 bot 的群消息。若 BotFather privacy mode 开着，普通群消息不会送达 bot，本补丁无法也不会伪造“历史回填”。缓存只在当前 gateway 进程内有效，并按 chat ID + topic/thread ID 隔离。

## 配置文件

- `memory_policy.default.yaml` — Memory Metacognition 策略配置模板
  安装后位于 `~/.hermes/memory_policy.yaml`，可自定义或删除关闭

## 使用说明

- **幂等安全**：已应用的补丁自动跳过，可多次运行
- **hermes update 后**：如果你的 Hermes checkout 已安装本补丁仓库的 update hook，直接运行 `hermes update` 即可；CLI 会在更新后自动执行本地 `~/.hermes/patches/install.sh`、重打 overlay，并运行关键 py_compile/health 检查。外部首次安装或未安装 hook 的环境，仍可手动运行本 installer。
- **回滚**：`cd ~/.hermes/hermes-agent && git reset --hard ORIG_HEAD`

## 更新后重新应用

### 已安装本补丁仓库 hook 的本机/维护者环境

直接运行：

```bash
hermes update
```

预期行为：Hermes 会检测本地 patch installer，必要时同步官方 upstream，然后自动重打补丁 overlay。无需再手动追加 `bash ~/.hermes/patches/install.sh`。

### 首次安装或未安装 hook 的外部环境

先安装/恢复本补丁仓库 installer：

```bash
bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
```

如果你把本仓库 clone 到本地，也可以用本地路径：

```bash
bash /path/to/hermes-patches/install.sh
```

## 友链

**[Linux Do](https://linux.do/)**
本项目亦在 Linux Do 社区中发布相关帖子。感谢佬友雪中送炭的 Token 哈哈~

## 许可

补丁来自 Hermes Agent 开源项目 (NousResearch/hermes-agent)，遵循原项目许可。
