     1|# Hermes Agent 社区补丁合集
     2|
     3|> 20 个精选未合并 PR，一键安装。装完立刻能感受到的变化：
     4|
     5|## 装了有什么用？
     6|
     7|**💰 省钱：每次对话省 99.2% token**
     8|原版 Hermes 每次对话会把 124 个技能描述全部塞进 system prompt，白白浪费约 12000 token。打完补丁后只注入你真正需要的 1 个技能，token 消耗从 ~12000 降到 ~800。按 OpenRouter 价格算，一天聊 100 次能省几美元。
     9|
    10|**🔒 隐私：多用户不再互相泄露**
    11|你和朋友共用一个 Hermes bot？原版 session_search 会搜到所有人的对话，memory 也会互相污染。打完补丁后每个用户的数据完全隔离，搜"我的密码"只返回自己的记录。
    12|
    13|**🧠 长对话不失忆**
    14|原版 Hermes 聊久了之后上下文压缩会把你的偏好和规则标记为"后台参考"，LLM 就开始忽略它们。打完补丁后 memory 权威性受到保护，你设定的规则在整个会话期间持续生效。
    15|
    16|**⚡ Agent 不再"跑偏"**
    17|原版 Agent 执行长任务时容易忘记之前的规则，开始幻觉或违规操作。打完补丁后每 8 次工具调用自动触发一次合规检查，把 Agent 拉回正轨。
    18|
    19|**🛡️ 安全和稳定性**
    20|- 默认开启 secret redaction，API key 不会意外泄露到日志
    21|- KV cache 稳定性优化，减少偶发崩溃
    22|- 紧急压缩机制，max_iterations 前自动瘦身防止中途挂掉
    23|- Gateway 重启时自动重载 .env，不用手动重启整个服务
    24|
    25|**🔧 后台任务不阻塞**
    26|原版派 Agent 去干重活时你得干等。打完补丁后后台 delegation 不阻塞主对话，你可以继续聊别的。
    27|
    28|## 一行命令安装
    29|
    30|```bash
    31|bash <(curl -sL https://raw.githubusercontent.com/Cyrene963/hermes-patches/main/install.sh)
    32|```
    33|
    34|或者手动：
    35|
    36|```bash
    37|git clone https://github.com/Cyrene963/hermes-patches.git
    38|cd hermes-patches
    39|bash install.sh
    40|```
    41|
    42|## 包含的补丁
    43|
    44|### 核心功能
    45|
    46|| 补丁 | 说明 | PR |
    47||------|------|-----|
    48|| 多用户 session/memory 隔离 | session_search 和 memory 按用户隔离 | [#17989](https://github.com/NousResearch/hermes-agent/pull/17989) |
    49|| 语义技能检索 (FTS5) | SQLite FTS5 全文索引替代暴力注入 | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) |
    50|| 混合技能选择器 | 规则+关键词+AI推断三层检索 | [#18316](https://github.com/NousResearch/hermes-agent/pull/18316) |
    51|| 修复轮换池丢弃 | /model 切换不再丢弃 credential pool，轮换机制正常工作 | [#19064](https://github.com/NousResearch/hermes-agent/pull/19064) |
    52|| Memory 权威性保护 | 防止上下文压缩削弱 memory | 上游已合并 |
    53|| 技能执行纪律框架 | Agent 必须遵循已加载的技能规则 | [#18849](https://github.com/NousResearch/hermes-agent/pull/18849) |
    54|| 合规检查插件 | 每 8 次工具调用触发合规检查 | [#18849](https://github.com/NousResearch/hermes-agent/pull/18849) |
    55|
    56|### 社区精选 16 个 PR
    57|
    58|| PR | 说明 |
    59||----|------|
    60|| [#18547](https://github.com/NousResearch/hermes-agent/pull/18547) | KV cache 稳定性：固定 system prompt 前缀 |
    61|| [#18582](https://github.com/NousResearch/hermes-agent/pull/18582) | Gateway 重启时重载 .env 环境变量 |
    62|| [#18596](https://github.com/NousResearch/hermes-agent/pull/18596) | 默认开启 secret redaction |
    63|| [#18600](https://github.com/NousResearch/hermes-agent/pull/18600) | HERMES_HOME 未设置时抛出明确错误 |
    64|| [#18603](https://github.com/NousResearch/hermes-agent/pull/18603) | summary_model 不可用时 fallback 到主模型 |
    65|| [#18607](https://github.com/NousResearch/hermes-agent/pull/18607) | 紧急压缩：max_iterations 前自动压缩 |
    66|| [#18614](https://github.com/NousResearch/hermes-agent/pull/18614) | Patch 幂等防护：防止重复应用 |
    67|| [#18616](https://github.com/NousResearch/hermes-agent/pull/18616) | 支持 ZWJ emoji 在 context 文件中 |
    68|| [#18618](https://github.com/NousResearch/hermes-agent/pull/18618) | Auxiliary client 传递 explicit_api_key |
    69|| [#18632](https://github.com/NousResearch/hermes-agent/pull/18632) | /insights 显示 cache token 统计 |
    70|| [#18638](https://github.com/NousResearch/hermes-agent/pull/18638) | Compressor 传递 threshold_percent 参数 |
    71|| [#18650](https://github.com/NousResearch/hermes-agent/pull/18650) | 压缩时清理带图片的 tool messages |
    72|| [#18663](https://github.com/NousResearch/hermes-agent/pull/18663) | 严格 API 模式下剥离 tool_calls extra_content |
    73|| [#18692](https://github.com/NousResearch/hermes-agent/pull/18692) | session-search 剥离 FTS5 操作符 |
    74|| [#5447](https://github.com/NousResearch/hermes-agent/pull/5447) | session_search FTS 匹配内容加载优化 |
    75|| [#7701](https://github.com/NousResearch/hermes-agent/pull/7701) | 非阻塞后台 delegation（session_id 模式） |
    76|
    77|## 使用说明
    78|
    79|- **幂等安全**：已应用的补丁自动跳过，可多次运行
    80|- **hermes update 后**：更新会覆盖补丁，重新运行 `install.sh` 即可
    81|- **回滚**：`cd ~/.hermes/hermes-agent && git reset --hard ORIG_HEAD`
    82|- **选择性安装**：删除 `patches/` 目录下不需要的 `.patch` 文件
    83|
    84|## 与 hermes update 配合
    85|
    86|在 `~/.bashrc` 中添加：
    87|
    88|```bash
    89|hermes() {
    90|    if [ "$1" = "update" ]; then
    91|        command hermes update "${@:2}"
    92|        bash ~/hermes-patches/install.sh
    93|    else
    94|        command hermes "$@"
    95|    fi
    96|}
    97|```
    98|
    99|## 许可
   100|
   101|补丁来自 Hermes Agent 开源项目 (NousResearch/hermes-agent)，遵循原项目许可。
   102|- - - -
   103|友链：**[Linux Do](https://linux.do/)**
   104|本项目亦在Linux Do社区中发布相关帖子。感谢佬友雪中送炭的Token哈哈~
   105|