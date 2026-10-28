# Evaluator 与 DeepEval 能力对照及迁移方案

> 历史方案：DeepEval 主引擎与源码迁移方向已被 [Inspect AI 方案](inspect_engine.md) 取代。下文记录迁移前状态，不代表当前运行架构。

核对日期：2026-10-15。Evaluator 以当前工作区实现为准；DeepEval 以本地 clone 的 `python-v4.2.9` 为准，提交为 `03ef3a25c2acbf09ef001080d2591704b9606931`。本文中的目标结构和迁移步骤尚未实施。

迁移采用 DeepEval 原生优先的统一架构。双方重叠的能力按 DeepEval 的对象、接口和执行方式改写；仅本项目具备的能力迁为扩展，公开扩展接口不足时进行源码二次开发；仅 DeepEval 具备的能力保留原生支持。业务兼容层只补缺口，不再长期维护一套重复的通用实现。

## 0. 已确定的三条迁移原则

| 分类 | 能力归属 | 必须采取的处理 |
| --- | --- | --- |
| A 双方都有 | 本项目已实现，DeepEval 也原生支持 | **按 DeepEval 的方式改写并替换**。完成切换后删除重复算法、调度或存储逻辑；旧接口只保留必要的转换和兼容导出 |
| B 仅本项目有 | 本项目已实现，DeepEval 没有对应能力 | **保留并迁为扩展**。优先采用 Metric、模型、回调等扩展接口；无法表达的通用缺口通过本地源码二次开发支持 |
| C 仅 DeepEval 有 | 本项目未实现，DeepEval 原生支持 | **保留原生支持**。不裁剪原生 API/CLI，不重复开发；需要业务数据、模型或可选依赖时，明确前置条件和项目入口接入状态 |

分类按可独立实现的子能力进行。例如工具权限匹配属于 A，独立证据完整性判断属于 B；最终组合是原生 ToolPermission 加证据扩展。不能因为一个业务模块含有 B 类规则，就把其中 A 类通用实现整体保留。

兼容工作的目标是保留业务约束和可追溯性，不要求逐行复刻旧算法。通用分数、原因或默认行为改用 DeepEval 口径时，要记录映射与变化、更新指标版本并重跑基线；证据不足、关键违规和真实状态等业务约束通过 B 类扩展表达。差异是适配或二次开发任务，不是默认保留重复实现的理由。

## 1. 当前实际接入程度

- 已使用 `EvaluationDataset`、`LLMTestCase`、`ConversationalTestCase`、`evaluate` 和本地原生 TestRun。
- 每个 Trial 的业务判断由自定义 `AgentEvaluationPolicy` Metric 在 DeepEval 调度中执行；当前 21 个注册断言仍是业务实现，不是 21 个 DeepEval 原生 Metric。
- 语义 Judge 已使用 `GEval`，通过 `DeepEvalBaseLLM` 适配 DeepSeek；保留自己的 Rubric、错误分类、重试与超时策略。
- Agent 执行、环境隔离、证据采集发生在 Metric 评分前；稳定性、比较、门禁和复核消费评分后的领域结果。
- 已 clone 本地源码，但默认虚拟环境仍导入安装包。尚未永久切换 editable 安装，也未把业务代码迁入 clone。

实现依据：[当前主引擎](../src/eval_framework/inspect_engine.py)、[Runner](../src/eval_framework/runner.py)、[业务判定](../src/eval_framework/evaluation_policy.py)、[GEval Judge](../src/eval_framework/judges/deepeval.py)。此前临时强制使用 clone 源码运行完整回归，结果为 341 passed、2 skipped；两个跳过项是付费 API 测试。该结果证明同版本源码兼容，不代表目录迁移已经完成。

## 2. 双方能力与迁移归属

下表给出目标归属，当前接入状态以第 1 节为准。A 类改写是确定方向；实施时验证原生调用、领域约束和结果兼容，不再提供“继续保留旧通用算法”的并列方案。

| 能力 | 当前 Evaluator | DeepEval 4.2.9 | 迁移决策 |
| --- | --- | --- | --- |
| 标准用例与评测调度 | 将 Trial 转为标准用例并提交评分 | Dataset、单轮/多轮 TestCase、evaluate、assert_test、pytest 集成 | **原生承担，已接入**；保留领域对象到 TestCase 的转换 |
| 数据接入与冻结 | 显式 Loader、JSONL/Manifest、能力包、路径和 Hash 校验、编译指纹 | Golden/Dataset、本地文件导入导出；另有托管数据集接口 | **A：通用数据容器和支持格式的读写改用 Dataset；B：保留领域格式转换、冻结验证和契约编译** |
| Agent 接入 | Provider 协议，内置 mini_agent | 回调、Dataset 评测迭代器、组件观测和框架集成 | **A：采用原生回调/迭代器接入方式；B：Provider 收敛为 Agent 创建、异常和资源生命周期适配** |
| 模块、链路、多轮执行 | 模块调用、单次 Agent 工具循环；按冻结输入推进多轮 | 单轮/对话评测、组件级评测、模拟对话 | **A：标准对象与评测执行按原生方式改写；B：保留冻结输入推进、作用域和终止规则** |
| 环境与状态 | 每 Trial 初始化、隔离、状态快照、清理；内置有限 SQLite 环境 | 可通过应用回调和自定义指标扩展 | **保留环境扩展**；工具 Trace 或任务完成度不能替代数据库状态证据 |
| 通用确定性指标 | 字段、工具、结构等规则 | ExactMatch、PatternMatch、ToolPermission、ToolCorrectness、JsonCorrectness 等 | **A：使用对应原生指标改写；B：只扩展原生未覆盖的 Schema、证据和业务规则**；原断言 ID 作为兼容映射 |
| 业务状态与时序指标 | 确认前不写入、无重复副作用、逐轮规则、最终状态 | BaseMetric、BaseConversationalMetric 可扩展；通用 Agent 指标可补充观察 | **保留业务 Metric**；通用语义评分不能代替精确状态判断 |
| 语义 Judge | 版本化 Rubric、维度、权重、必需/可选、独立凭据、脱敏 | GEval、ConversationalGEval、DAG 等，模型抽象 | **原生指标承担评分，保留业务 Judge 策略**；GEval 已接入 |
| 独立证据 | SDK 持久化、关联 ID、完整性、通道状态、失败不回退 | Trace/span、observe、组件评测和多种框架集成 | **保留证据扩展并桥接 Trace**；记录了 Trace 不自动证明记录完整可信 |
| Trace 分析 | 规则观察、时间线、业务事件和证据检查 | Agent/LLM/tool/retriever spans，Trace/span 评测 | **A：通用 Trace 建模、组件评价和展示改用原生；B：保留证据验证及业务时序规则** |
| 结果判定 | 加权、关键项否决、未知分数、有效性与质量分开 | Metric 分数、阈值、success/error、运行结果 | **A：指标计算与单指标阈值使用原生；B：扩展领域汇总、关键否决和未知/无效状态** |
| 重复运行与稳定性 | 每 Case 真实运行多个 Trial，pass@k、pass^k、波动、耗时 | pytest 重复、异步调度、缓存等运行能力 | **A：在支持的执行入口采用原生重复/调度机制；B：补足 Trial 身份、每次初始化清理和稳定性聚合**；必须真实重跑 Agent |
| 本地报告 | Markdown、JSON/JSONL、Case 文件、失败清单、派生重分析 | 本地 JSON/SQLite、终端查看及报告导出 | **A：通用记录、查看和报告改用原生；B：仅保留领域字段、审计附表和旧格式导出**；共用结果源 |
| 基线比较 | 数据、配置、Provider、Judge、引擎等指纹一致后配对比较 | ArenaGEval 与 compare 支持候选对比 | **保留回归比较扩展**；Arena 胜负比较不等于冻结条件下的配对回归 |
| 发布门禁 | 完成率、关键失败、稳定性、回归、证据、耗时和 token 策略 | assert_test/pytest 失败可接 CI，指标阈值 | **A：复用原生指标阈值和测试断言；B：保留跨运行、证据、回归和资源预算 Gate** |
| 人工复核 | 追加审核人、理由、决定和原结果 Hash，不修改自动结果 | annotation 接口支持向托管服务提交标注 | **保留本地复核账本**；未来托管标注可通过显式连接器同步 |
| 并发、缓存、限流 | 当前评分串行且关闭缓存，保护运行状态与重复实验 | 异步、并发限制、节流、缓存、错误处理配置 | **C：完整保留原生配置能力；B：增加业务运行模式约束**；真实稳定性实验禁用会替代实际执行的缓存，其他模式通过隔离验证后启用 |
| 全流程插件声明 | Loader/Provider 已落地；其他 Profile 未全部接通 | Metric、模型、回调等扩展接口 | **A：使用原生扩展协议；B：Suite 声明编译为原生对象和业务扩展配置**；不再自建平行的通用指标框架 |

Evaluator 依据：[契约编译](../src/eval_framework/contracts/compiler.py)、[Provider](../src/eval_framework/provider.py)、[SQLite 环境](../src/eval_framework/providers/mini_agent/state_environment.py)、[证据要求](../src/eval_framework/evidence_requirements.py)、[Trace 分析](../src/eval_framework/trace_analysis.py)、[稳定性](../src/eval_framework/stability.py)、[比较](../src/eval_framework/comparison.py)、[门禁](../src/eval_framework/gating.py)、[复核](../src/eval_framework/adjudication.py)。

DeepEval 依据：[Dataset](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/dataset/dataset.py)、[指标目录](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/metrics/__init__.py)、[执行配置](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/evaluate/configs.py)、[Trace](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/tracing)、[本地存储](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/evaluate/local_store.py)、[compare](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/evaluate/compare.py)、[annotation](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/annotation)。原生存储的使用方式见[官方本地存储文档](https://deepeval.com/docs/evaluation-local-backend-storage)。

## 3. 现有 21 个断言如何处理

下表覆盖全部注册名称，包括兼容别名。当前实现见 [assertions.py](../src/eval_framework/assertions.py) 和 [turn_assertions.py](../src/eval_framework/turn_assertions.py)。表中为确定的改写方向，尚未完成实现。复杂断言拆为原生计算与业务补充规则，不因部分语义不同而整体沿用旧算法。

| 现有断言 | 原生改写或扩展方式 | 适配要求 |
| --- | --- | --- |
| `status_match`、`intent_match`、`next_action_match` | **A：字段提取后交给 ExactMatch** | B 类适配处理字段缺失和结构非法；规范化不得把不同类型错误转换为相同文本 |
| `params_match`、`missing_params_match` | **A：投影/规范化后用原生 ExactMatch；B：扩展参数子集、集合和缺失值处理** | 投影必须保留缺失键及类型差异；不能用字符串转换掩盖结构问题 |
| `intent_envelope_schema_valid`、`output_schema_valid` | **A：按 JsonCorrectness 改写通用结构校验；B：扩展冻结 JSON Schema 支持**；后者保留别名 | 原生支持的 Pydantic Schema 使用其实现；无法无损转换的 Draft 2020-12 约束通过校验后端扩展或源码二次开发接入，不能静默丢弃约束 |
| `intent_parameters_schema_valid` | **A：复用同一 JsonCorrectness 校验路径；B：扩展按冻结意图选择 Schema** | 意图选择、动态 Schema、严格校验与来源指纹；禁止另外维护一套通用结构评分 |
| `tool_called` | **A：改用 ToolCorrectness；B：补充证据前置条件** | 将“包含指定工具”的业务目标映射为原生输入/配置；保留不完整证据下的未知状态 |
| `tool_not_called` | **A：改用 ToolPermission；B：补充证据前置条件** | 禁用表对应、缺少完整记录不能通过；已观察到违规必须失败 |
| `tool_call_count` | **B：采集和统计有效调用；A：计数值用 ExactMatch 比较** | 精确次数以及完整覆盖要求，不用“选对工具”的分数替代次数 |
| `tool_args_match` | **A：改用 ToolCorrectness 参数比较；B：适配调用选择和参数投影** | 首个匹配调用、参数子集及原生分数到断言的映射需显式定义；覆盖缺失参数和额外参数 |
| `tool_result_consistent` | 保留业务 Metric，可复用原生工具对象表示 | 调用状态、实际返回值、业务输出之间的对应关系 |
| `confirmation_requested`、`confirmation_accepted` | **B：保留确认事件存在性、别名和证据规则；通用事件名匹配复用原生匹配能力** | 当前判断来自确认事件，requested 还接受 confirmation_required 别名；不能改用回复文案或终态代替 |
| `no_state_change`、`final_state_match` | **B：保留状态采集与判定 Metric；A：其中可规范化的精确值匹配使用原生比较** | Provider 读取的前后/最终状态与 Oracle 比较，状态缺失保持未知；差异提取、状态范围和关联仍属扩展 |
| `no_duplicate_side_effect` | **B：保留副作用状态观察；A：实际计数与期望计数交给 ExactMatch** | 计数字段和证据来源仍由业务定义；不能通过统计成功文案推断副作用 |
| `no_write_before_confirmation` | **B：保留确认时序、逐轮状态及证据规则；精确值比较复用原生能力** | 真实状态、事件、确认时点与逐轮快照；工具名称和自然语言规则不足以证明 |
| `response_consistent` | **A：文本包含/禁止条件编译到 PatternMatch，期望状态用 ExactMatch；B：保留配置组合** | 处理字面量转义、多行、空条件及原生 trim/fullmatch 行为；语义维度另用 GEval，不能替代确定性规则 |
| `turns_match` | **B：BaseConversationalMetric 承载逐轮规则；A：逐轮字段和工具匹配调用原生指标** | 实际轮次、状态、工具顺序、终止条件和逐轮证据；只导出真实执行的对话 |

原生 [ToolCorrectness](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/metrics/tool_correctness/tool_correctness.py) 支持名称、参数、输出和顺序等配置；启用可用工具的最优选择判断时还涉及模型评价。[JsonCorrectness](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/metrics/json_correctness/json_correctness.py) 的 Schema 类型与原因生成策略也与现有实现不同。实施时需完成输入配置、分数映射和模型成本适配。对于原生支持范围内的规则，验收必须证明实际执行了原生计算，不能先在旧代码算好真假，再传给 ExactMatch 或包装成原生指标名称。

DeepEval 还支持自然语言 `Expectations.must/must_not`，但该路径使用模型评价，适合补充任务约束，不应替换数据库事实、精确次数或确认时序的确定性规则。见 [Expectations 定义](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/dataset/expectations.py) 与[执行实现](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/evaluate/expectations.py)。

## 4. 一个已验证的兼容差异

前次能力核对用本地源码做了不调用模型的对照：禁用工具为 `write`，证据状态为 PARTIAL。

| 输入证据 | 原生 ToolPermission | 当前 tool_not_called |
| --- | --- | --- |
| 没有观察到任何工具调用 | score=1.0，success=True | passed=None，原因是缺少完整工具调用覆盖 |
| 观察到一次有效的 write 调用 | score=0.0，success=False | passed=False，保留已观察到的违规 |

原生指标按传入的调用列表评分，空列表得 1.0 是其既定语义；它不负责证明该列表是否完整。见 [ToolPermission 源码](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/metrics/tool_permission/tool_permission.py) 和[官方说明](https://deepeval.com/docs/metrics-tool-permission)。我们的评估需要额外区分“没有发生”和“没有记录到”。

按新原则，工具权限匹配仍必须改用 ToolPermission；完整性判断作为 B 类扩展组合进来。适配器需要确定哪些事实能够由当前证据支持：有足够证据确认违规时保留 FAIL；未发现违规但缺少完整证据时保留 UNKNOWN；只有证据满足该断言要求时才能接受原生指标的通过结论。不能统一把所有 PARTIAL Trial 跳过，也不能因这项差异继续保留旧的权限匹配算法。

同样要保留以下行为：关键项失败不能被高均分抵消；必需 Judge 错误不能当零问题；评估无效与质量失败分别记录；原生 success=False 的背后必须能分辨 FAIL、INCONCLUSIVE 和 INVALID。现在单一复合 Metric 已负责这些映射，分拆指标前需要先保证一致。

## 5. DeepEval 能带来的新增能力

以下 C 类能力全部保留原生支持，不因当前项目没有使用而裁剪。支持分为三个可验证层次：**原生可用**（依赖满足后可通过 DeepEval API/CLI 使用）、**项目已接入**（具备 Suite/Provider/业务入口的数据映射）、**场景已验收**（有对应样例和结果）。迁移要求保留第一层，并逐项记录后两层的真实状态；不要求每个业务默认运行所有指标。原生指标可能需要上下文、Trace、模型或可选依赖。

| DeepEval 能力 | 对当前项目的用途 | 接入位置和条件 |
| --- | --- | --- |
| RAG 相关性、忠实度、上下文精度/召回等 | 评估检索和基于资料回答的质量 | Provider 导出 retrieval_context，再由 Suite 选择指标；当前用例没有这些字段时不能直接宣称覆盖 |
| TaskCompletion、ArgumentCorrectness、GoalAccuracy、StepEfficiency、PlanQuality/Adherence、AgentLoopDetection 等 | 补充 Agent 效率、规划和任务完成诊断 | 转换真实 Trace，作为独立维度；业务数据库断言继续决定事实是否成立 |
| 对话质量、知识保持、角色/话题遵循、MCP、图像与语音指标 | 拓展评估对象和任务类型 | 新 Provider、对应 TestCase 与样例先落地，再启用指标 |
| Synthesizer | 生成候选用例和扩展覆盖 | 放到 Builder/候选数据流程，经审核、去重、契约验证和冻结后进入正式评测 |
| ConversationSimulator | 探索澄清、确认和异常对话 | 独立探索模式；保存实际生成的输入，合格案例再冻结，不能静默改变回归输入 |
| PromptOptimizer，含 GEPA、MIPROV2、COPRO、SIMBA | 用评估反馈辅助优化 Prompt | 在训练/开发集运行；冻结的独立验收集用于最后验证，防止调优污染 |
| 分类器：拒答、澄清、升级处理、提示注入、泄漏等 | 为报告和失败聚类增加标签 | 作为可选分析，不覆盖已有确定性结果 |
| ArenaGEval 与 compare | 对候选输出做相对比较 | 保留原生候选比较入口；严格配对回归仍由 B 类扩展提供 |
| 原生本地存储及报告 | 减少通用展示、运行记录维护 | 逐步采用原生展示，同时保留领域 JSON、证据引用及历史读取 |

来源：[指标导出](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/metrics/__init__.py)、[Synthesizer](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/synthesizer)、[Simulator](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/simulator)、[Optimizer](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/optimizer)、[分类器](https://github.com/confident-ai/deepeval/blob/python-v4.2.9/deepeval/classifiers)。数据生成入口另见[官方 Synthesizer 文档](https://deepeval.com/docs/golden-synthesizer)。

Confident AI 的托管数据集、协作界面和标注服务保留原生连接能力，需要服务与凭据才能使用；clone 开源仓库不会自动获得这些服务。本地业务入口默认不上传。迁移时将现有禁用设置限定在本地业务运行模式，避免扩展包导入或全局补丁永久影响其他原生运行模式。

## 6. 扩展包如何兼容 DeepEval

目标采用本地 DeepEval 源码仓库，并把业务包迁入 `extensions/agent_evaluator`。保留 `eval_framework` 包名、CLI 和独立的 `agent_trace_sdk`；上游核心依赖保持独立。完整目录与安装问题见[源码迁移评估](superpowers/specs/2026-10-15-deepeval-source-migration-assessment.md)。

目标数据流如下。迁入扩展目录是过渡步骤，最终按 A/B/C 收敛职责，不能把整套旧框架原样包装后视为改写完成。

```text
Suite + 冻结数据 + 能力契约
    ↓ 契约扩展：校验、编译、指纹
DeepEval 原生执行入口 + Provider 生命周期扩展
    ↓ 隔离环境、真实 Trial、独立证据、逐轮快照、清理
DeepEval Dataset / TestCase / Trace + 领域上下文
    ↓ 原生 Metric / GEval + 原生缺口的自定义 Metric
领域判定：权重、关键项、UNKNOWN、有效性与质量
    ↓
DeepEval 原生 TestRun + 兼容领域结果
    ↓ 治理扩展：稳定性、比较、Gate、追加复核
```

接口适配要遵守以下约定：

1. **执行输入隔离。** Oracle 仅进入评估侧。Agent 的工厂、工具和运行参数只接收 ExecutionSpec；不要把完整用例连同参考答案传给 Agent 回调。Judge 接收经过选择和脱敏的参考信息。
2. **标准对象保留关联。** 单轮/多轮文本、工具名、参数和输出映射到原生字段；Case、Trial、Trace ID 放入 metadata。事件状态、完整性、逐轮状态快照和清理结果保留在领域上下文及产物中，用 ID/Hash 关联，不能压成一段自然语言后丢掉结构。
3. **原生计算与领域汇总分开。** 使用原生 Metric 的 score/reason，兼容层只转换结果；权重、关键项和未知规则作为扩展汇总。复合 `AgentEvaluationPolicy` 可在过渡期负责组装，但不得继续隐藏重复的通用计算。验收要检查实际调用链，并输出各原生指标身份、配置和分项结果；顶层聚合方式需确保领域结论不被默认 success 合并规则覆盖。
4. **运行职责只有一份。** 采用 DeepEval 支持的执行入口与回调方式，Provider 负责具体 Agent 和资源生命周期。旧 Runner 收敛为预检、配置与兼容入口；原生执行协议未覆盖的真实 Trial 管理通过扩展补齐，不能旧 Runner 跑一遍、原生回调再跑一遍。
5. **结果兼容。** 保留现有 results.json、Case/Trial ID、CLI 和历史读取；记录原生文件相对路径。FAIL、INCONCLUSIVE、INVALID 以及缺失分数的区别不得因原生布尔字段丢失。
6. **可比性覆盖二次开发。** 增加上游基线、实际运行源码及模板的内容指纹，覆盖未提交修改；仅记录版本号 4.2.9 无法识别本地二次开发差异。指纹变化参与 compare 的拒绝规则。
7. **扩展与二次开发都有明确入口。** 业务规则优先采用公开 Metric/模型/回调接口。公开接口不能表达的能力，形成缺口记录并在本地源码开发，不要求退回旧通用实现。Schema 校验后端、运行上下文与本地终结接口是待验证的候选缺口；每项记录原因、扩展点、改动范围、上游基线及回归测试。
8. **保留完整原生能力面。** 扩展包不能把 DeepEval 的使用范围限制成 21 个旧断言。原生 API/CLI 与业务 CLI 并存；维护 C 类能力目录和可选依赖说明。业务支持目录逐项注明原生可用、项目已接入和场景已验收，不把模块能导入当业务接入完成。

稳定性迁移需要特别保留当前定义：项目的 `pass_at_k` 表示计划的 k 次中是否至少一次通过，`pass_power_k` 表示计划的 k 次是否全部通过；它们不是代码基准中无偏 pass@k 估计公式。不能沿用名称却换成另一种统计口径。

## 7. 实施顺序与验收边界

| 阶段 | 具体工作 | 完成标准 |
| --- | --- | --- |
| 1. 拆分能力与约束 | 把模块拆为 A/B/C 子能力，登记原生实现、业务缺口、旧实现删除位置和指标口径变化 | 21 项断言全部有去向；明确必须保持的业务约束与采用原生口径的通用行为 |
| 2. 源码与包迁移 | 本地源码及业务扩展 editable 安装，迁移 SDK/资源/测试配置，保留公开入口 | 默认导入来自 clone；从新目录运行现有回归与状态型示例，旧报告仍可读 |
| 3. A 类原生改写 | 使用原生数据、执行、工具、精确匹配、结构校验、Judge、Trace 和报告能力；删除重复实现 | 调用链确实经过原生实现；兼容导出可读；通用口径变化有版本记录与新基线；业务约束不丢失 |
| 4. B 类扩展与二次开发 | 迁入契约、环境、证据、业务时序和治理扩展；补足 Schema/生命周期接口缺口 | 扩展通过正式接口参与原生流程；必要核心补丁有独立回归；不存在第二套通用评分引擎 |
| 5. C 类能力保留与入口接入 | 保留原生 API/CLI、指标/模型及可选组件；建立能力目录，逐项接入业务数据 | 原生入口无扩展包全局干扰；代表性原生能力完成可用性检查；所有能力标明三层支持状态和依赖 |
| 6. 装配与整体验收 | 接通所需 Suite Metric/Judge Profile，增加源码指纹，运行业务及受影响原生回归 | A 类重复实现已移除、B 类能力不退化、C 类能力未裁剪；配置字段均有明确可用状态 |

共同验收必须包含：关键项失败但总分高；部分证据且已观察到违规；缺少完整证据而未观察到违规；Judge 超时/必需 Judge 失败；真实重复执行与独立清理；Oracle 不泄漏给 Agent；原生与领域结果一致；报告复制后仍可读；无隐式托管上传。

当前能力边界继续保留：内置业务 Provider 只有 mini_agent；SQLite 环境只覆盖明确实现的工具；没有通用故障注入或同步调用的强制取消；Suite 的 Judge Profile 尚未接通。DeepEval 的并发配置、模拟器或模型评价都不能自动填补这些运行环境缺口。

迁移完成的判断是：**A 类已按原生方式改写并移除重复实现，B 类已通过扩展或源码二次开发接入，C 类原生能力完整保留且支持状态清楚**。原有业务有效性和结果协议必须兼容；通用指标口径采用原生方式后的差异要可追溯。clone、搬目录和把原代码包进 Metric 都不能单独作为完成标准。
