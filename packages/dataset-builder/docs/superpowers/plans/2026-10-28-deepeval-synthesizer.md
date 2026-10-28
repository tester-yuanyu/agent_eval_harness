# DeepEval Synthesizer 接入计划

目标：增加可选生成后端，按已有能力契约和覆盖槽位生成语义候选，继续走原有校验、人工审核和冻结流程。

规格来源：用户本轮“接入吧”，以及此前禁止猜测缺失预期、保护历史版本、当前会话直接执行的要求。

架构：GenerationClient → 每槽位一个 Synthesizer context → Golden(input, expected_output JSON) → 严格 Candidate → 原编译器与质量门禁。expected_output 是待审草稿，不是权威契约；禁止复制种子预期，禁止自动修复不合法 JSON。

全局约束：可选依赖、默认后端不变；显式指定模型；不调用 Agent、不自动审核/冻结、不改历史数据集、不提交或推送现有混合改动。先支持带 rule_refs 的单轮 intent 套件；不宣称已接入全工具/多轮执行器。

审查重点：SDK 真实 API、缺参/歧义不被质量重写、槽位和规则不漂移、请求来源哈希、异常快速失败、原始 Golden/版本/配置可追溯、旧流程兼容。

- [x] 任务 1：测试先行，新增可选后端及 Golden 严格适配；真实 SDK 配离线模型验证。
- [x] 任务 2：CLI 选择、可选依赖、生成来源清单、使用说明；测试命令链路。
- [x] 任务 3：全量回归、独立审查、历史文件哈希核对。

## 执行记录

- 已核对官方文档及 PyPI 4.3.2 SDK 源码。
- 决策：在现有 codex/evalcase-v2-dual-protocol 工作分支直接完成，保留全部已有未提交文件；新 worktree 无法自然包含这些工程前置改动。
- 决策：初版禁用 evolution（0 次）；通用完整性过滤阈值为 0、只评分一次，避免缺参用例被“补全”。仍执行本地校验和人工语义审核。
- 决策：从原始 Golden 的当前 input 生成对应 JSON 预期；不读取 seed_catalog。若缺少 JSON、槽位不符或规则未定义，报错，不补猜。
- 接口核对：CLI 提供已加载套件，客户端检查其 prompt/schema/coverage 与 prepared request 一致；RawGeneration 新增可选 metadata，旧记录保持可读。
- 任务 1 RED：新后端不存在；GREEN：15 项初版行为测试通过。SDK 真实实现配置离线模型完成 42 槽位编译和校验，拒绝网络连接。
- 任务 2 RED：CLI 不识别 --backend；GREEN：命令生成 42 条草稿；错误依赖给出明确安装提示。可选 SDK 已装入项目 .venv，补齐相邻 evaluator 当前所需 langfuse/inspect_ai 依赖，pip check 通过。
- 独立审查发现并修复：缺失 suite_config/policy 绑定核对、raw hash 无校验读者；新增 6 个先红后绿回归，编译前另绑定磁盘原始响应与传入对象。
- 独立复核：24 项 DeepEval 测试通过，28 项生命周期/门禁/跨 Agent 回归通过，无遗留阻塞问题。样式转换潜在语义漂移已在说明中明确，不宣称离线测试证明生成质量。
- 已安装 SDK 的全量回归：270 passed；Ruff 与 pip check 通过；历史包 806 文件无变更。
- 未安装 SDK 的附加回归发现残留 namespace 目录导致 importorskip 误判，已改为先检查 distribution metadata；最终复测 269 passed、1 skipped（仅真实 SDK 契约测试），已安装环境该项再次执行通过。全部任务完成。
