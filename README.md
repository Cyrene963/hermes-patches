# Hermes Agent — Memory OS 补丁集

> 给 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的社区补丁:一套分层的 **Memory OS** —— 结构化长期记忆、语义召回、工具前执行门控,以及一个可自主学习的写入回路。以 overlay 方式叠加在官方版本之上,**可验证、可配置、可回退**。

> ⚠️ **诚实说明**:每项能力都按**证据**标注(✅ 已验证 / ⚠️ 部分 / ⏸ 门控中),不把"文件存在"当成"功能跑通"。完整能力矩阵与验证证据见 **[docs/STATUS.md](docs/STATUS.md)**。

## 它解决什么

模型"有记忆,却不知道自己记得什么"——换个说法问同一个问题,就会重犯上次纠正过的错。本补丁把记忆做成一个工程闭环:**感知 → 召回 → 行动前门控 → 行动 → 学习(写入)**,每一环都可独立验证,而不是把所有内容粗暴塞进 prompt。

## 核心能力

- 🧠 **Memory Graph** —— 结构化长期记忆(URI 图谱、14 个 CRUD/搜索工具、版本快照、别名、术语触发),按用户做 Postgres 行级安全(RLS)隔离。
- 🔎 **语义召回** —— Hindsight 向量 embedding 召回 + 重排;Memory Graph 提供结构化事实的词法召回,且**私有记忆排序优先于共享公开区**。
- 🛡️ **工具前门控(Preflight)** —— 在工具执行前检查参数、拦截已知失败模式(防复发),默认开启、可在 `memory_policy.yaml` 配置。
- ✍️ **自主学习写入** —— LLM 事实分类器(混合集实测 precision **1.000** / 0 误报)+ readback 验证,只把干净的 durable 事实写入私有命名空间;LLM 端点不可达时 **fail-closed**(暂停写入,绝不污染)。
- 🔒 **多用户三层隔离** —— Graph namespace / Hindsight bank / per-user `MEMORY.md`。
- ⚡ **混合技能选择器** —— manifest 约束 → 轻量候选召回 → 可配置语义重排,减少无关技能注入、保证必备技能首 token 前加载。
- 🔍 **Search-as-Code / deep_research** —— 结构化证据检索管线,产出 `evidence.json`/`manifest.json` 并跑隐私扫描。
- 🔧 **稳定性修复** —— custom provider header 透传、跨渠道记忆统一、CJK 搜索隔离、cron 多用户投递隔离等。

> 这些能力分别处于"已验证 / 部分验证 / 门控中"哪一档,以及离"数字替身/外置大脑"还有多远——见 **[docs/STATUS.md](docs/STATUS.md)**。

## 安装

```bash
bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
```

installer 先运行 `scripts/hermes-patch-env-preflight.py` 做本机预检:要求 `~/.hermes/hermes-agent` 是真实 Hermes repo(含 `toolsets.py`),检查基础命令、Python 依赖、以及可选服务(PostgreSQL `5432`、Memory Graph `:8900`、Hindsight `:9177`)。缺**必需**项即停并打印修复步骤;缺**可选**项继续安装但相应能力标为 degraded。已合并进上游的补丁自动跳过;**已在运行的 gateway 需重启**才会加载 Python 变更。

- 幂等安全,可重复运行。
- 回滚:`cd ~/.hermes/hermes-agent && git reset --hard ORIG_HEAD`。
- 装了 update hook 的环境直接 `hermes update` 会自动重打 overlay。

详细安装/排查见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md);每个补丁/overlay/回滚边界见 [PATCHES.md](PATCHES.md)。

## 文档

| 想了解 | 文档 |
|---|---|
| **记忆系统怎么工作的(深入浅出)** | **[docs/MEMORY_OS_EXPLAINED.md](docs/MEMORY_OS_EXPLAINED.md)** |
| 能力矩阵 / 验证证据 / 距数字替身多远 | [docs/STATUS.md](docs/STATUS.md) |
| Memory OS 架构(技术参考) | [docs/MEMORY_ARCHITECTURE.md](docs/MEMORY_ARCHITECTURE.md) |
| 收敛方案 / 失败模式 / 验证 run-book | [docs/MEMORY_OS_CONVERGENCE_PLAN.md](docs/MEMORY_OS_CONVERGENCE_PLAN.md) |
| 三套记忆系统对比 | [docs/MEMORY_SYSTEM_COMPARISON.md](docs/MEMORY_SYSTEM_COMPARISON.md) |
| Search-as-Code / deep_research | [docs/SEARCH_AS_CODE.md](docs/SEARCH_AS_CODE.md) |
| 每个补丁 / overlay / 回滚 | [PATCHES.md](PATCHES.md) |
| 故障排查 | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |

## 项目结构

| 目录 | 内容 |
|---|---|
| `agent/` | 记忆子系统运行时模块(write pipeline、fact classifier、distiller、metacognition、`memory_graph/` 服务) |
| `tools/` | 工具实现(`memory_graph_tool` 等) |
| `tests/` | 回归测试 + 语义召回 eval(`tests/memory_os/`) |
| `hermes_cli/` | 补丁版 dashboard 运行时 bundle(`web_dist`)与 web server |
| `standalone-memory-graph-webui/` | 独立 Memory Graph WebUI(前端 + 后端) |
| `scripts/` | installer 预检、补丁链 guard、隐私 guard、审计/eval 脚本 |
| `patches/` · `individual/` · `integration-v1/` | targeted patch / 可选 patch / legacy combined patch(已不作为主发布载体) |
| `systemd/` · `cron/` · `db/` | 服务单元、定时任务、数据库迁移 |
| `docs/` · `examples/` | 文档与配置示例 |

## 配置

- `memory_policy.default.yaml` → 安装后 `~/.hermes/memory_policy.yaml`:元认知 / 门控 / 召回策略,可自定义或删除关闭。
- `memory_write_config.yaml`:写入回路模式与 LLM 分类器开关(`llm_classifier`)。
- `examples/memory_identity.example.yaml`:部署私有身份(真实姓名/项目代号)复制到 gitignore 的 `~/.hermes/memory_identity.local.yaml`,**不进公开仓库**。

## 兼容性

适配 Hermes Agent **v0.16.0 / `v2026.6.5`** 之后的官方 `upstream/main`。上游近期已合并的能力(pre-flight thinking block、auto-context retrieval、多用户 session/memory 隔离、secret redaction、MCP reconnect 等)由 installer 自动检测并跳过——本补丁只补充**尚未进入上游**的 Memory OS / Memory Graph / 检索与门控能力,不把官方已内置功能冒充为补丁成果。

## 质量保障

- `.github/workflows/patch-verification.yml` —— 在 clean upstream checkout 上跑无副作用 installer smoke + 关键 import/toolset 注册 + focused regression。
- `.github/workflows/privacy-guard.yml` —— 公开仓库隐私/密钥扫描。部署私有的人名等模式从 gitignore 的本地文件加载,公开仓库与历史均不含真实身份数据。

## 许可与致谢

补丁基于 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent),遵循其许可。Memory Graph 架构灵感来自 [nocturne_memory](https://github.com/Dataojitori/nocturne_memory)(MIT)。

友链:**[Linux Do](https://linux.do/)** —— 本项目亦在社区发布相关帖子。
