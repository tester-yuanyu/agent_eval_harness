# Agent 自动化评测报告规范

2026-10-20 更新：Inspect 负责正式调度、判分和指标；Evaluator 保留业务扩展；Langfuse 接管展示和人工标注。DeepEval 已删除。最新单一职责、权威数据与验收限制见 [接入说明](langfuse.md)。

## 1. 文档目的

本文规定 Agent 自动化评测报告的结构、指标口径、结论判定和证据组织方式，作为报告生成器、评测使用者和 Agent 优化人员之间的共同约定。

逐项指标定义见[评测指标字典](metric_dictionary.md)，包括证据要求、计算粒度、缺失处理、Gate 用途与候选能力。2026-10-28 核对后，下文摘要口径区分唯一 Case 与 Trial，并保留当前实现的分母和百分位差异。

报告需要同时满足三个目标：

- **快速判断**：读者可以在第一屏确认本次评测是否通过，以及阻断原因；
- **便于定位**：失败 Case 能展示第一处偏差、预期值、实际值和建议排查环节；
- **可以复现**：每个结论都能追溯到评测集版本、Agent 输出、断言结果、Trace 和系统终态。

本文描述第二阶段评测报告。确定性断言仍是安全、工具、权限、确认、幂等和系统终态的
权威判据；Inspect Model Grading（独立 Judge 模型） 只评价显式声明的语义维度，不能覆盖确定性关键失败。
多次 Trial、Trace 观察、基线比较和本地发布门禁均使用独立、可重放的结构化产物。

## 2. 报告使用对象

| 使用者 | 主要关注内容 |
|---|---|
| Agent 开发人员 | 失败类型、失败 Case、预期与实际、原始证据 |
| 评测框架开发人员 | 执行异常、断言结果、运行配置和复现信息 |
| 质量负责人 | 总体结论、通过率、安全问题和发布阻断原因 |
| 本地门禁或其他程序 | 机器可读的结论、指标、失败列表和运行清单 |

## 3. 报告产物

每次运行创建独立的 `eval_run_*` 目录，包含以下文件：

| 文件 | 用途 |
|---|---|
| `report.md` | 面向人的主报告，展示结论、指标、问题和失败详情 |
| `summary.json` | 面向程序的运行结论和汇总指标 |
| `failures.json` | 执行异常、质量失败及问题分类 |
| `results.json` | 完整运行结果，可重新加载 |
| `results.jsonl` | 每行一个 Case 结果，便于流式处理 |
| `run_manifest.json` | 数据集、模型、Agent、断言版本和执行限制 |
| `cases/<case_id>/<trial_id>.json` | 单个 Trial 的完整结果 |
| `evidence/<case_id>/<trial_id>/actual.json` | Agent 的实际输出、轮次结果和工具调用 |
| `evidence/<case_id>/<trial_id>/assertions.json` | 每条断言的预期、实际和判断结果 |
| `evidence/<case_id>/<trial_id>/trace.jsonl` | Agent Trace；有 Trace 时生成 |
| `evidence/<case_id>/<trial_id>/model_error.json` | 脱敏后的模型原始输出、校验错误和异常因果链；发生模型错误时生成 |
| `evidence/<case_id>/<trial_id>/state.json` | 系统终态；执行终态核验时生成 |
| `langfuse_reviews.jsonl` | 人工复核来源修订快照；只从 Langfuse 导入，不修改自动结果 |
| `stability.json` | Case/Run 级 `pass@k`、`pass^k`、波动与百分位 |
| `judge/<case_id>/<trial_id>.json` | 适用 Trial 的独立 Judge 结果 |
| `trace_analysis/<case_id>/<trial_id>.json` | 规范化时间线与观察项 |
| `analysis.json` | 对不可变运行结果重新分析得到的派生索引 |
| `comparison.json` / `comparison.md` | 严格可比性与基线差异 |
| `gate.json` / `gate.md` | 版本化 Policy 的门禁检查与结论 |

`report.md` 负责解释结果，不作为下游程序的稳定数据接口。程序应读取对应的 JSON 或 JSONL 文件。

`results.json` 和 `run_manifest.json` 使用通用字段 `agent_version`。历史
`results.json` 若只有 `mini_agent_version`，读取时迁移为 `agent_version`；两字段同时
存在但值不一致时必须拒绝读取。新产物不得继续写出 `mini_agent_version`。

若运行在创建 Case 之前的预检阶段失败，则只生成最小失败目录，其中包含
`invalid_run.json` 和 `report.md`。该目录不得伪造 `results.json`、Case 结果或 Agent
通过率；命令行以非零状态退出。

## 4. 运行结论

主报告必须在顶部展示唯一的运行结论，并用一句话说明判断依据。

### 4.1 结论类型

| 结论 | 含义 |
|---|---|
| `PASSED` | 所有 Case 均完成执行，且没有质量失败或无法判定的 Case |
| `FAILED` | 所有 Case 均完成执行，但至少一个 Case 的质量结论为 `FAIL` |
| `MANUAL_REVIEW_REQUIRED` | 所有 Case 均完成执行，但至少一个 Case 为 `INCONCLUSIVE`，需要人工判断 |
| `INVALID_RUN` | 运行前校验失败，或至少一个 Trial 未正常完成或评测有效性为 INVALID；当前结果不能完整代表 Agent 质量 |

### 4.2 判定优先级

结论按以下顺序判断：

1. 运行前数据集、能力契约或 Provider 校验失败，存在执行异常，或任一 Trial 的 evaluation_validity 为 INVALID，结论为 `INVALID_RUN`；
2. 不存在执行异常，但存在 `INCONCLUSIVE`，结论为 `MANUAL_REVIEW_REQUIRED`；
3. 不存在以上情况，但存在 `FAIL`，结论为 `FAILED`；
4. 其他情况为 `PASSED`。

执行异常与 Agent 质量失败必须分开。模型调用失败、初始化失败或评测器异常不能记为 Agent 质量失败，也不能用降低通过率代替说明。执行异常至少区分：

- `MODEL_OUTPUT_ERROR`：模型返回内容无法通过输出协议校验；
- `MODEL_INVOCATION_ERROR`：模型 API 调用失败；
- `MODEL_TIMEOUT`：模型 API 调用超时；
- `AGENT_EXCEPTION`：Agent 自身出现未归入模型错误的异常；
- `INITIALIZATION_ERROR`：Runtime 或依赖初始化失败；
- `EVALUATOR_ERROR`：断言、评分、证据写入或清理发生异常；
- `OUTER_TIMEOUT`：调用完成后发现超过 Case 时间预算。

运行前失败至少使用稳定错误代码区分：能力 Bundle 缺失或损坏、能力契约不兼容、
数据集校验失败。此类失败发生在模型客户端创建之前，不产生任何 CaseResult。

## 5. 主报告结构

`report.md` 按以下顺序组织：

1. 评测结论；
2. 执行摘要；
3. 主要问题；
4. Inspect Model Grading（独立 Judge 模型）、Trace 观察和 Trial 稳定性；
5. Case/Trial 结果；
6. 失败与异常详情；
7. 分组指标，仅在存在多个分组值时显示；
8. 运行与复现信息。

阅读路径应保持为：

> 结论 → 总体指标 → 主要问题 → Case 列表 → 失败证据 → 复现信息

主报告不重复展示已经可以从上层表格继承的信息。失败详情只补充失败断言和证据，不再重复执行状态、得分等基础字段。

## 6. 执行摘要

### 6.1 必须展示的指标

本节状态计数和通过率的粒度为 Trial；总 Case 数按唯一 case_id 去重。每 Case 仅运行一次时两者相等，多 Trial 时不能混用。正式摘要只读取已保存的 SummaryStats，不由报告或看板重新计算。

| 指标 | 定义 |
|---|---|
| 总 Case 数 / 总 Trial 数 | 本次实际进入运行的唯一 Case 数 / 已保存 Trial 记录数 |
| 数据集状态 | 从与数据集 SHA-256 匹配的 Manifest 读取；无法确认时为 `UNKNOWN` |
| 执行案例 | 本次执行 Case 数与数据集完整 Case 数，例如 `5/42` |
| 执行类型 | 完整评测、定向冒烟或筛选子集 |
| 每 Case Trial 数 | 每个 Case 的计划独立运行次数 |
| 执行完成 | `execution_status=COMPLETED` 的 Trial 数与已保存 Trial 总数 |
| PASS | 最终质量结论为 `PASS` 的 Trial 数 |
| FAIL | 最终质量结论为 `FAIL` 的 Trial 数 |
| ERROR | 未正常完成执行的 Trial 数；评测有效性另行读取 |
| INCONCLUSIVE | 证据不足等原因导致无法自动判断的 Trial 数 |
| 严格断言通过率 | agent_benchmark 模式下，最终质量为 PASS 的 Trial 数除以非 NOT_APPLICABLE 的已保存 Trial 数；包含必需 Judge 对最终质量的影响，不是逐条断言命中率 |
| 核心行为匹配率 | 使用同一适用 Trial 分母；分子要求执行完成、评测有效，且质量为 PASS，或 diagnoses 非空且全部为 PROTOCOL_NAMING_MISMATCH；仅用于诊断 |
| 模型输出错误 | `MODEL_OUTPUT_ERROR` Trial 数 |
| 模型调用错误 | `MODEL_INVOCATION_ERROR` Trial 数 |
| 模型超时 | `MODEL_TIMEOUT` Trial 数 |
| Agent 异常 | `AGENT_EXCEPTION` Trial 数 |
| 初始化错误 | `INITIALIZATION_ERROR` Trial 数 |
| Evaluator 错误 | `EVALUATOR_ERROR` Trial 数；独立的 evaluation_issues 仍需查看 |
| 外层超时 | `OUTER_TIMEOUT` Trial 数 |
| 平均断言得分 | 所有非空 Trial 断言分数的平均值，仅用于辅助定位 |
| 单 Case 通过条件 | 通过阈值以及关键断言要求 |
| 中位延迟 | summary.median_latency_ms，Trial 延迟的统计中位数，偶数样本取中间两值平均；不称为 P50 |
| 平均延迟 | 所有已保存 Trial 延迟的算术平均值 |
| 最大延迟 | 已保存 Trial 中的最大延迟 |
| 评测范围 | 本次涉及的 scope、intent 和 task |

### 6.2 指标解释规则

- 不使用“框架完成率”作为主报告字段，避免与框架建设进度或 Agent 通过率混淆；
- 不使用含义宽泛的“Agent 通过率”或“基础设施错误”；
- 严格断言通过率用于正式契约判断，核心行为匹配率只用于定位协议命名差异，不能替代严格结论；
- 核心行为匹配当前按执行状态、有效性、最终质量及诊断代码判断，具体口径见 6.1；协议命名诊断只解释 `missing_params_match` 的纯命名差异，不改变安全、权限、写确认和系统终态的正式断言结论；
- 子集运行不能只展示子集数量，必须同时展示完整数据集 Case 数；
- Trial 通过率是 PASS Trial 数除以计划 Trial 数；`pass@k` 表示至少一次 PASS，
  `pass^k` 表示全部计划 Trial 均 PASS；
- summary.performance 保存唯一的运行级 nearest-rank P50/P95，稳定性与 Gate 读取该快照；摘要 median_latency_ms 是单独命名的统计中位数，两者在偶数样本时可能不同。样本不足时 P95 只能作为观察值，门禁必须给出
  `REVIEW_REQUIRED`，不能假装满足阈值；
- 平均断言得分是诊断指标，不代表评测通过；
- 当通过条件为 100 分且关键断言全部通过时，必须在报告中明确写出；
- 只有少量 Case 时展示 P50、平均值和最大值，不强调统计意义有限的 P95；
- 没有可参与计算的数据时显示“不适用”，不能用 `0` 代替缺失结果。

当前空集合的历史摘要延迟字段仍序列化为 0，不能据此声称实测零延迟；新 performance 分位数为空。business-metrics-v2 的分组和 Gate 标签子集均排除 NOT_APPLICABLE，保留 FAIL/INCONCLUSIVE；全不适用或非 agent_benchmark 时不提供质量通过率。分组展示 applicable_count 作为通过率分母，并保留总 Trial 数；Gate 标签并集不会重复计数。不同范围仍不能互替。旧结果保留历史值，不自动改写；新旧指标版本不可直接比较。细节与 Judge Token 边界见[指标字典](metric_dictionary.md#5-已实现的分数和运行指标)。

## 7. 主要问题

“主要问题”用于聚合可观察到的失败现象，不直接宣称最终根因。

| 字段 | 说明 |
|---|---|
| 问题类型 | 业务可读的问题名称，例如“用户 ID 类型错误” |
| 影响 Case 数 | 命中该问题的 Case 数 |
| 失败 Case 占比 | 影响 Case 数除以失败 Case 总数 |
| 代表 Case | 第一条命中该问题的 Case |
| 建议排查环节 | 建议检查的模块，不表示已经确定根因 |

同一个 Case 可以命中多个问题，因此问题次数之和可以大于失败 Case 数。

问题分类应尽量具体，避免把不同修复方式的问题都归为“参数不匹配”。建议优先使用：

- 参数类型错误；
- 参数值非法；
- 参数缺失；
- 参数冲突或歧义；
- 多余参数；
- 参数名称错误；
- 协议命名不一致；
- 意图或决策状态错误；
- 工具选择或工具参数错误；
- 安全确认错误；
- 系统终态错误；
- 最终回复与执行结果不一致。

问题名称应面向业务阅读。内部规则名可以保留在 JSON 中，但不应直接作为主报告标题。

### 7.1 “协议命名不一致”的判定边界

`PROTOCOL_NAMING_MISMATCH` 只用于预期和实际都返回了非空的澄清目标，
但使用了不同字段名称表达同一目标的情况。它表示 Agent 核心行为可能正确，
差异集中在评测集与 Agent 的字段命名协议。

以下情况不能归为“协议命名不一致”：

- 预期不需要澄清，但实际新增了澄清目标；
- 预期需要澄清，但实际没有返回澄清目标；
- 状态、下一步动作或参数值本身不符合预期；
- 更正、否定、冲突或歧义处理导致 Agent 选择了错误业务决策。

这类情况应根据实际偏差记录为“澄清目标不匹配”“决策状态不匹配”、
“参数缺失”或更具体的问题。即使同一 Case 同时出现字段命名差异和核心行为错误，
也不能计入核心行为匹配。

## 8. Case 结果

Case 汇总表必须保持紧凑，包含：

| 字段 | 说明 |
|---|---|
| Case | Case ID，并链接到完整 Case JSON |
| 场景 | 用户输入或简短场景描述 |
| 场景类型 | 直接读取评测集的 `scenario_type`，转换成中文名称展示 |
| 预期行为 | 根据 Oracle 和断言生成的简短行为摘要 |
| 实际行为 | 根据 Agent 输出、工具调用或最终回复生成的简短行为摘要 |
| 结论 | `PASS`、`FAIL`、`INCONCLUSIVE` 等质量结论 |
| 首个偏差 | 按断言执行顺序出现的第一项失败 |
| 延迟 | Case 总耗时 |

行为摘要必须由结构化字段确定，不使用 LLM 生成。Module 评测中的
`CALL_TOOL` 表示“准备调用工具”，不能写成工具已经执行；只有存在真实
`tool_calls` 证据时，才能写“调用工具”。常见动作统一展示为：

- `CALL_TOOL`：准备调用工具，并显示 intent 和关键参数；
- `ASK_USER`：追问，并将缺失字段转换成业务可读描述；
- `ASK_CONFIRMATION`：请求用户确认；
- `REJECT`：拒绝请求；
- 已产生 Tool Call：调用具体工具，并显示关键参数；
- 只有最终回复：显示限长后的回复摘要；
- 执行异常：显示结构化异常分类。

单 Case 得分不在汇总表重复展示，仍完整保存在 Case JSON 和机器结果中。
主表用于扫描全局情况，不在其中展开全部断言或完整模型输出。

## 8.1 Judge、Trace、比较与门禁边界

2026-10-20 起，语义 Judge 使用 Inspect 原生 Model Grading。`judge_metadata` 记录后端、依赖版本、适配语义版本、指标、评分模式和 Rubric 身份。不一致的历史结果继续可读，但禁止直接比较；基线必须重跑。详见 [迁移说明](langfuse.md)。

- Judge 输入必须脱敏，输出按版本化 Pydantic 协议校验；模型超时、调用错误和输出错误
  分开记录。Judge 分数必须与确定性得分分栏展示。
- Trace 只报告 `OBSERVED_*`、`EVIDENCE_*` 和 `SUGGESTED_*` 现象，不将时间顺序或缺失
  事件直接写成最终原因。
- 比较仅接受冻结、数据集/筛选/Trial/能力/断言/工具 Profile/Judge 指纹一致的运行。
  Agent 版本、Provider 实现版本和 Agent 模型/Prompt 可作为允许变化的实验变量。
- Gate 优先级固定为：无效比较、证据不足需复核、明确阈值失败、通过。安全标签和指定
  断言的零容忍失败不能被平均值、Judge 高分或其他修复抵消。
- 非冻结运行必须明确标为临时观察，不具备正式基线或发布 PASS 资格。

场景类型必须来自评测集，报告不得根据用户输入、Oracle、断言结果或普通
`labels` 推断。机器结果保留稳定的英文枚举，`report.md` 使用以下中文名称：

| `scenario_type` | 报告名称 |
|---|---|
| `normal` | 正常指令 |
| `valid_boundary` | 合法边界 |
| `invalid_parameter` | 非法参数 |
| `missing_parameter` | 缺少参数 |
| `ambiguous_expression` | 表达歧义 |
| `multi_condition` | 多条件指令 |
| `expression_variant` | 表达变体 |
| `correction_conflict` | 更正／参数冲突 |
| `unsupported_batch` | 不支持批量 |

## 9. 失败与异常详情

每个失败或异常 Case 单独展示，格式如下：

```markdown
### <Case ID>：<业务可读的问题名称>

> <用户输入>

| 检查项 | 预期 | 实际 |
|---|---|---|
| <失败断言> | <预期值> | <实际值> |

第一处失败检查：<检查项>

证据：完整 Case JSON / 原始输出 / 断言结果 / Trace / 系统终态
```

具体要求：

- 只列出失败断言，不重复列出已经通过的断言；
- 预期和实际使用紧凑 JSON，保留数值与字符串等类型差异；
- “第一处失败检查”表示最早观察到的偏差，不等同于最终根因；
- 执行异常应展示异常类型和经过脱敏的错误信息；
- 模型输出错误应链接 `model_error.json`，其中保存脱敏、限长后的原始输出、结构化校验错误、异常 cause、Prompt 版本和 Schema 版本或哈希；
- 证据必须是实际可打开的相对链接，不能只写“查看证据”；
- 有 Trace 时链接 Trace，有系统终态时链接系统终态；不存在的证据不展示空入口。

## 10. 分组指标

支持按评测范围、预期意图、实际意图和任务分组。

- 某一维度只有一个分组值时，不展示该维度的独立分组表；
- 至少存在两个分组值时，才展示各分组的 Trial 总数、适用 Trial 数、通过数和通过率；
- 单一范围运行时，在执行摘要中用一行展示，例如：`module / query_user / intent-query-user`；
- 分组通过率必须使用与总体通过率一致的分母定义。
- 无有效输出时，预期意图仍从 Oracle 参与目标能力分组，实际意图单独标记为 `unknown`；不得用预期意图覆盖实际意图。

## 11. 运行与复现信息

主报告使用普通 Markdown 表格展示以下信息，不使用 `<details>`、
`<summary>` 等 HTML 折叠标签：

- Run ID；
- 运行模式；
- 模型；
- 数据集文件名；
- 数据集版本；
- 数据集状态；
- Agent 版本；
- Provider ID 和 Provider 版本；
- Capability Bundle SHA-256；
- 断言注册表版本；
- 通过阈值；
- 开始和结束时间。

主报告提供指向 `run_manifest.json` 的相对链接。以下详细信息只写入
`run_manifest.json`，不在主报告重复展示：

- 数据集路径和 SHA-256；
- 数据集 Manifest 路径；
- 模型客户端；
- Case 过滤条件和执行限制。

Provider 和 Capability Bundle 字段属于复现依据，而不是展示性信息。Bundle hash
必须来自已校验的冻结 Manifest；报告不得用当前 Agent 目录中的实时文件替代。

报告及其机器文件不得记录 API Key、访问令牌或其他密钥。异常信息在输出前也需要遵循同一原则。

## 12. 人类报告与机器文件的职责边界

| 内容 | `report.md` | JSON/JSONL |
|---|---|---|
| 一句话结论 | 必须 | 必须提供结构化结论 |
| 核心指标 | 精简展示 | 保存完整精确值 |
| 问题分类 | 使用业务可读名称 | 同时保存稳定的问题代码 |
| Case 全量字段 | 不展示 | 完整保存 |
| 原始输出和 Trace | 只提供链接 | 完整保存到证据文件 |
| 复现配置 | 常用字段直接展示，其余折叠 | 完整保存 |

主报告的文字和布局可以迭代；机器字段、状态枚举和问题代码需要保持稳定，发生不兼容变更时应升级相应协议版本。

## 13. 意图输出断言

Module 评测将意图输出校验拆成两层：

| 断言 | 作用 |
|---|---|
| `intent_envelope_schema_valid` | 校验 `IntentResult` 外层字段、枚举和状态组合 |
| `intent_parameters_schema_valid` | 根据 intent 校验参数名称、类型和取值范围 |

旧名称 `output_schema_valid` 暂时保留为
`intent_envelope_schema_valid` 的兼容别名，用于读取已经冻结的旧评测集。新生成的评测集应使用两个新断言；兼容别名不替代参数 Schema 校验。

参数 Schema 校验属于结构和取值范围校验，不负责判断 AND、OR、否定、指代等自然语言语义。此类问题由确定性的场景标签、预期决策和诊断规则共同判断。

第一阶段 `intent_parameters_schema_valid` 已接入 `query_user` 对应的
`QueryUserInfoArguments`。后续接入其他 intent 时，应先在 Adapter 中增加对应参数契约，再允许评测集使用该断言。断言注册表版本为 `phase1-v2`。

## 14. Module Trace 与模型错误证据

Module Adapter 调用 `run_intent_only()` 后必须读取
`intent_trace_snapshot()`，并把事件写入 Case 的 `trace_events` 和
`trace.jsonl`。Trace 至少覆盖可观察的候选接收、意图定义解析、参数规范化、参数校验、语义约束和最终决策事件，不记录隐藏推理。

Agent 必须在成功和异常路径都保存本次调用的 Trace；Evaluator 在 Adapter 抛出异常后也必须读取失败快照。模型输出在进入 Agent 意图契约前失败时，Trace 可以只包含请求或阶段事件，但必须通过 `model_error.json` 保留模型边界证据。

模型原始输出只能由模型客户端在收到响应时采集。mini_agent 负责产生脱敏的结构化诊断，evaluator 负责保存，不允许 evaluator 从异常字符串猜测或重建原始输出。任何诊断文件不得包含 API Key、访问令牌、Authorization Header 或完整 Prompt 正文。

## 15. 人工复核审计

人工复核仅在 Langfuse Annotation 编辑。Evaluator 按 `review.decision.v1` 从 Scores API 完整分页导入，校验 ANNOTATION 来源、Trace 关联、审核人、有限结论与版本化归因标签。

`langfuse_reviews.jsonl` 追加保存 Case/Trial、自动/人工结论、details、审核人、来源项目/score ID、修订时间/Hash、结果 Hash、taxonomy 版本/Hash。`langfuse_review_sync.json` 是完整同步后的有效修订清单；Cloud 删除不会抹掉历史审计，但会从有效清单移除。

不得修改 `results.json`、`results.jsonl` 或 Case 原始自动结论。人工覆盖意见不自动改变 Gate；需要修正问题并重新运行。结构与操作约定见 [Langfuse 接入](langfuse.md)。

## 16. 非冻结数据集

正式 `agent_benchmark` 默认只接受 `FROZEN` 数据集。使用 `DRAFT`、
`VALIDATED`、`APPROVED` 或 `UNKNOWN` 数据集时，调用方必须显式允许非冻结运行；报告顶部必须显示“临时评测结果，不可作为基线、发布门禁或正式 Agent 质量结论”。

非冻结运行仍保存全部自动指标与证据，但所有通过率必须标记为“临时观测值”。数据集状态不能根据文件名推断，只采信 SHA-256 匹配的 Manifest。

## 17. 报告质量检查

报告生成后至少检查：

- 顶部结论与 `summary.json` 的 `run_verdict` 一致；
- PASS、FAIL、ERROR 和 INCONCLUSIVE 数量与 Case 结果一致；
- 各异常类型分别统计，模型错误不计入 Agent 异常或基础设施错误；
- 严格断言通过率和核心行为匹配率使用已定义且版本化的断言集合；
- 问题聚合数量可以追溯到具体 Case；
- 每个失败 Case 都有预期值、实际值和第一处失败检查；
- 所有 Markdown 证据链接指向真实文件；
- 单分组运行没有重复展示无区分度的分组表；
- 数据集版本、SHA-256、模型和 Agent 版本可以支持复现；
- 数据集生命周期只采信 SHA-256 匹配的 Manifest，不能根据文件名猜测；
- 子集报告明确显示执行 Case 数与数据集总 Case 数；
- 单 Trial 报告明确提示结果不代表稳定性；
- Module Case 在成功路径保存 Trace，模型错误 Case 保存可用的失败证据；
- 预期意图和实际意图分别聚合，无输出 Case 不被错误移出目标能力分组；
- 非冻结数据集带有显著的临时结果警告；
- 人工复核不修改原始自动结果，并可通过结果哈希审计；
- 报告及证据文件中不包含密钥；
- 报告没有把观察到的偏差直接写成未经验证的根因。

## 18. 第二阶段有意不包含

以下能力不属于当前阶段，后续引入时应扩展本文：

- CI workflow、PR Smoke 或 Nightly 调度；
- HTML 报告与托管服务；
- 自动修改原始运行结果或用人工复核覆盖自动结论；
- 将 Trace 观察自动宣称为最终原因；
- 未达到 Policy 最小样本量时使用 P95 作发布通过依据。

## 19. 当前实现对应关系

| 规范内容 | 当前实现 |
|---|---|
| 主报告及机器文件生成 | `src/eval_framework/reporting.py` |
| 问题分类 | `src/eval_framework/diagnostics.py` |
| 报告及结果数据结构 | `src/eval_framework/schemas.py` |
| Judge 协议与 Inspect 客户端 | `src/eval_framework/judge.py`、`src/eval_framework/judges/inspect.py` |
| Trial 稳定性 | `src/eval_framework/stability.py` |
| Trace 派生分析 | `src/eval_framework/trace_analysis.py` |
| 基线比较 | `src/eval_framework/comparison.py` |
| 本地发布门禁 | `src/eval_framework/gating.py` |
| 报告行为测试 | `tests/test_reporting_cli.py` |
| 第二阶段端到端测试 | `tests/test_phase2_end_to_end.py` |
| 问题分类测试 | `tests/test_diagnostics.py` |

当前可参考的真实报告样例位于：

`artifacts/query_user_candidate_d97bb17_report_v2/eval_run_4c152fb2e8c04fb4ab146007a4f4035e/report.md`
