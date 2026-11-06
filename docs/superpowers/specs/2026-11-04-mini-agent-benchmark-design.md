# mini_agent 真实评测与交付

用户授权创建评测集、真实执行、完整 trace/评分/报告及 Langfuse 展示，确认沿用 deepseek-flash，先小批后完整运行，并将已有配置放当前项目忽略的 .env。配置已写入（0600），密钥不进入源码、容器或报告。

采用前轮确定的 Provider 复用方案。比较了旧 Suite 直接跑（历史 Inspect 判分，不符合当前正式 DeepEval 主线）、修改 mini_agent 迎合文件工具（改变被测对象）与薄领域扩展；选择最后一种。复用已有 Provider、SDK、领域断言、Inspect runner 和 Langfuse 导出，不复制第二套判分规则，不为 Agent 在通用 runner 增加分支。

范围由本轮执行者确定：105 条，93 条既有意图任务按来源 Hash 派生为新版本；6 条 query_user 本地合成 fixture 工具链；6 条 gift SQLite 确认/澄清/取消/状态端到端任务。固定原用例及其 Oracle，只对新版本作显式执行/断言契约转换。全新 capability bundle 绑定当前源码及测试工具，不在 v3 bundle 中加清单。既有 15 条混合 scope 数据不改动、不算本轮覆盖。所有用例为开发评测，未经独立人工审查，不声明 holdout 泛化。

Inspect 负责模型传输、Docker 子进程、预算、原生日志、重复与恢复。真实 MiniAgentProvider 在 Docker worker 中创建，OpenAI-compatible Responses 经 Inspect bridge 交给配置的模型；模型凭据仅在宿主 Inspect。SDK 独立采集 Agent 事件、SQLite 观察状态与原生模型日志共同组成 trace。禁止 Oracle/检查点进入 Sample target 或 worker。缺失/中断证据保留 INCONCLUSIVE/INVALID。

runner 增加可信 domain 对象注入，提供输入投影、评分与评分身份；默认文件领域保持原行为。领域评分以 DeepEval BaseMetric 执行已有断言，底层严格值比较显式切换为纯确定性比较；旧 Inspect 兼容语义保持不变。单 task/generation/tool/turn 分数引用实际证据节点。

执行：6 条先导验证传输与证据，再105条各1次；先导独立报告，不并入主分母。并发最多4，单任务120秒、模型输出2048 tokens、sample token limit16384、Agent max_steps4，无自动付费重试。失败不按通过条件重跑，不改 Agent；环境故障修复须记录。费用缺少返回证据保留未知。

报告保存 JSON/Markdown/HTML、Inspect View、数据来源/身份、分层通过率、失败原因、token用量与trace完整性。Langfuse使用现有项目展示本次合成任务与公开轨迹，复用稳定ID导出、精确元数据和全量回读，最后浏览器抽查并提供链接。全链路指公开请求/模型输入输出/路由/工具/轮次/状态/正式评分，不含隐藏思维链。
