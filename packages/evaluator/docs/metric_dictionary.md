# Agent 评测指标字典

> 本文属于旧 Suite／Provider 兼容路径；其中 Inspect 评分、指标和产物约定不适用于当前任务基准。新基准由 Inspect 执行与记录、DeepEval 正式评分，入口见[包说明](../README.md)。以下包内命令在 `packages/evaluator` 目录执行。

核对日期：2026-10-28。本文定义各指标的唯一实现归属、评测对象、必要证据、计算口径、缺证据处理及 Gate 用途，并确定 DeepEval 专项指标的接入清单。选型与实现状态分开：“候选”项尚未注册、没有正式结果，也不参与发布门禁。

Inspect 负责正式执行、Scorer 和 Metric 聚合；DeepEval 定位为由 Inspect Scorer 调用的专项指标算法库；Evaluator 提供业务契约、独立证据、适配、判定政策和 Gate；Langfuse 消费已保存结果。Conversation Completeness 已作为可选诊断接入（DeepEval 4.2.9）；其余专项算法仍为候选。本轮保留指标汇总单一权威，不改变冻结样本契约。报告字段与产物见[报告规范](evaluation_report_spec.md)，证据协议见[独立证据规范](TRACE_PHASE1.md)。

## 1. 使用约定

### 1.1 状态与权威来源

| 状态 | 含义 | 使用条件 |
| --- | --- | --- |
| 已实现 | 当前代码有计算或判断路径 | 仍需满足 scope、Provider、环境和证据要求 |
| 可选 | 已实现，但必须显式配置 | 未配置不能解释为通过；Judge 接入限制见第 4 节 |
| 候选 | 仅有指标定义和采用条件 | 不得作为现有断言名、结果字段或 Gate 配置使用 |

冻结的 Oracle、Rubric 和执行配置决定评测预期；Inspect Scorer 生成 Trial 结果，Inspect Metric 生成正式汇总；`results.json` 保存不可变领域结果。报告与看板读取已有值，不根据页面筛选、可见 Trace 数或成功请求数另算同名通过率。Gate 的检查结果保存在 `gate.json`，它不修改原分数。

### 1.2 粒度与单位

- **Case**：唯一 `case_id` 对应的一条评测定义。**Trial**：一次独立执行，以 `case_id + trial_id` 标识。`CaseResult` 实际保存一个 Trial。
- 第 3 节的断言返回 `true / false / null`，不是已经聚合的“准确率”。`null` 表示无法判定，不能转成 0 分或 PASS。
- 当前百分比字段为 **0–100**；断言分数和 Judge 分数也为 **0–100**。候选项的范围另行标注，不直接套用 DeepEval 默认阈值。
- `execution_status`、`evaluation_validity`、`quality_conclusion` 分别表达执行、评测有效性与质量。已证明的业务失败可以与评测无效同时存在。
- 必需证据缺失不能通过删除适用断言或缩小分母消失。独立通道启用后，不回退使用 Agent 自报内容来证明业务状态。

### 1.3 Gate 标记

| 标记 | 含义 |
| --- | --- |
| A | 已配置的确定性断言参与 Trial 断言得分及质量结论；权重、`critical` 来自冻结 checks。可被 `zero_tolerance_assertions` 引用，但该 Gate 只统计明确失败，不能独自证明证据齐全 |
| J | 依 `oracle.judge.required` 参与最终质量结论；维度还可由显式 `required_judge_dimensions` 检查 |
| P | 仅在相应 GatePolicy 字段显式配置时参与门禁 |
| D | 诊断或展示，当前不直接作为 Gate 阈值 |
| N | 未实现，不参与 Gate |

### 1.4 唯一选型与实现边界

以下四类互斥；每项在“选型与边界”列只指定一个归属。归属指该指标的判断规则或聚合算法，不表示同一组件包办数据采集、模型传输和结果展示。

| 选型 | 判断标准 | 不属于该归属的工作 |
| --- | --- | --- |
| Inspect 原生 | 公共 Scorer、Model Grading 或 Metric 满足指标语义 | 业务字段提取、适用样本选择、冻结阈值由 Evaluator 适配 |
| DeepEval 复用 | 选定已有专项算法，Inspect 无同语义的开箱实现 | 不采用其评测 Runner、Dataset 管理、结果平台；候选状态仍需接入验收 |
| 业务自研 | 独立业务证据、契约、判定政策或经验证的原生能力缺口 | 值比较、均值、JSON Schema 等基础能力继续复用 Inspect 或标准库 |
| 暂不适用 | 尚无明确业务样本、算法语义不匹配，或公共接入方式待验证 | 不实现替代算法，不为追求指标数量启用；列出重启条件 |

不能仅因为 Inspect 能运行任意评分 Prompt，就把它视为已具备声明抽取、逐声明核验、检索排序评价等专项算法。同样，不因 DeepEval 的指标总数更多，就替换已经满足业务语义的原生评分。

## 2. 分工与去重决策

正式路径只有一条：Inspect 执行 → Inspect Scorer 调用选定算法 → Inspect Metric 聚合 → 不可变结果 → Langfuse 展示。业务 Gate 消费正式结果。每个指标 ID/版本只有一个正式实现；DeepEval 完成接入验收后可以成为正式分数来源，是否阻断发布另由冻结政策决定。

| 评测类别 | 当前能力 | 选型决策 | 去重边界 |
| --- | --- | --- | --- |
| 输出协议与任务理解 | Schema、意图、参数、状态、下一步动作 | 原生匹配；业务 Schema 选择复用 jsonschema | 不再接入 DeepEval Exact Match / JSON Correctness 生成第二套同义结果 |
| 工具选择与调用 | 工具名、禁止调用、次数、参数、逐轮顺序及结果一致性 | 保留有独立证据的业务断言，复用原生比较 | [Tool Correctness](https://deepeval.com/docs/metrics-tool-correctness) 暂不接入：其默认配置不等于检查参数、顺序及额外调用 |
| 业务闭环与操作安全 | 独立终态、确认、幂等、无状态变化 | 业务自研规则是正式依据 | [Task Completion](https://deepeval.com/docs/metrics-task-completion) 暂不接入：轨迹推断不能代替数据库终态与副作用证据 |
| 回复质量 | completeness、relevance、clarity、tool_summary_accuracy | 保留 Inspect Model Grading，逐项见第 4 节 | 不为相同业务决策并行运行 [G-Eval](https://deepeval.com/docs/metrics-llm-evals) / [Answer Relevancy](https://deepeval.com/docs/metrics-answer-relevancy)；新算法若有独立用途，另立版本、校准后替换或拆分维度 |
| RAG 检索与回答依据 | 尚无专项检索/声明级指标 | 选定 DeepEval Faithfulness、Contextual Precision、Contextual Recall | 复用专项算法，不自写一份声明链；仅在真实 RAG 样本上启用 |
| 整段对话与记忆 | 已有冻结逐轮断言；当前 Judge 不读取完整对话 | 选定 DeepEval Conversation Completeness、Knowledge Retention | 评价开放对话需求与记忆；明确参数更正仍由 turns_match 验证，不将两者合成第二条业务通过率 |
| 规划与效率 | 尚无完整可见计划及专项 Trace 接入 | 暂不适用；优先验证 DeepEval 公共 Trace 接口 | Plan Quality / Step Efficiency 当前不是普通 standalone 指标，不为接入它们重跑 Agent 或新增第二套采集平台 |
| 可靠性、性能与发布 | 多 Trial、耗时、可比性、版本化 Gate | 原生聚合 + 业务政策，逐项见第 5、6 节 | 保持唯一计算入口；新汇总使用 business-metrics-v2；旧结果保留历史口径，不由看板补算 |

## 3. 已实现的确定性断言

本节覆盖 `ASSERTION_SCOPES` 的全部 **22 个注册名称**，其中 `output_schema_valid` 是兼容别名。默认结果范围为布尔三态，Gate 均为 A。实现见 [assertions.py](../src/eval_framework/assertions.py)、[原生匹配适配](../src/eval_framework/native_scoring.py)。

选型按完整断言的责任归属标记：意图/参数等单值匹配归 Inspect；工具首次调用、覆盖、确认时序等业务规则归 Evaluator，内部比较仍调用 Inspect，不另造匹配算法。Schema 直接复用 jsonschema，不接入第二个 Schema 评分库。

缺证据说明以独立证据路径为主。历史 Provider 的内嵌记录仍可读取，但不能据此宣称具备独立完整性保证。模块结果缺失、未知断言、状态快照缺失等检查由评分入口执行；具体不适用场景应在冻结数据和预检阶段明确。

### 3.1 输出协议与任务理解

| 指标 ID 与对象 | 选型与边界 | 必要证据 | 判定口径 | 缺失或错误处理 | Gate |
| --- | --- | --- | --- | --- | --- |
| `intent_envelope_schema_valid`：module 输出结构 | 业务自研：冻结契约；复用 jsonschema | 实际 module_output、冻结模块 output_schema | JSON Schema Draft 2020-12 校验，所有约束满足才通过 | 独立路径缺输出为未知；未知模块、缺失/非法 Schema 或结构不符返回失败，不代表 Agent 语义错误 | A |
| `output_schema_valid`：历史外层结构检查 | 业务自研：同一 Schema 实现的别名 | 同上 | `intent_envelope_schema_valid` 的同一实现；不额外检查意图参数 Schema | 同上；不是另一项独立算法 | A |
| `intent_parameters_schema_valid`：module 参数合法性 | 业务自研：按实际意图选冻结 Schema | 实际 intent、parameters、该 intent 的冻结参数 Schema | 按实际意图选 Schema，校验参数结构 | 缺输出为未知；未知意图或参数不合法失败 | A |
| `intent_match`：module 意图 | Inspect 原生：pattern；适配类型/空白 | 实际 intent、Oracle 或 check.expected | 保留类型与字符串空白的精确匹配 | 完整输出中缺字段按缺失值比较；整个独立模块输出缺失为未知 | A |
| `status_match`：module/link 决策状态 | Inspect 原生：pattern；适配状态来源 | module.status 或最后一轮 status、冻结预期 | 精确比较模块状态或 Agent 最终状态 | 独立路径缺最终结果或执行未完成为未知 | A |
| `next_action_match`：module 下一步动作 | Inspect 原生：pattern | 实际 next_action、冻结预期 | 精确匹配 CALL_TOOL、ASK_USER 等声明值 | 字段不符失败；整个独立模块输出缺失为未知 | A |
| `params_match`：module 参数值 | Inspect 原生：pattern；适配键投影 | 实际 parameters、冻结参数预期 | 默认完整精确匹配；`expected_subset` 仅投影预期的顶层键后比较，保留类型差异 | 应有键缺失失败；整个独立模块输出缺失为未知 | A |
| `missing_params_match`：module 追问目标 | Inspect 原生：pattern；适配集合排序 | 实际及预期 missing_parameters | 去重、排序后的集合精确匹配；字段未提供时当前实现用空列表 | 追问目标不同失败；整个独立模块输出缺失为未知 | A |

### 3.2 工具与链路行为

| 指标 ID 与对象 | 选型与边界 | 必要证据 | 判定口径 | 缺失或错误处理 | Gate |
| --- | --- | --- | --- | --- | --- |
| `tool_called`：link 工具选择 | 业务自研：请求与覆盖规则；比较用 pattern | 有效 tool_requested、冻结目标工具 | 至少观测到一次目标工具请求 | 已观测目标可通过此项；未观测且相关记录不完整为未知，完整时失败 | A |
| `tool_not_called`：link 禁止调用 | 业务自研：禁止集合与覆盖规则；比较用 pattern | 有效 tool_requested、冻结 forbidden_tools | 没有调用任何禁止工具 | 已观测禁止调用即失败；未观测且覆盖不足为未知 | A |
| `tool_call_count`：link 调用次数 | 业务自研：计数与不完整证据规则；比较用 pattern | 目标工具请求记录、预期次数 | 实际请求次数等于预期 | 部分证据已超过预期仍失败；否则需完整覆盖才能判定 | A |
| `tool_args_match`：link 工具参数 | 业务自研：首个请求与完整性；比较用 pattern | 完整请求记录、目标工具首个调用、预期参数 | 只检查目标工具第一次调用；默认精确匹配，可配置顶层预期子集 | 覆盖不完整无法确认第一次调用，返回未知；不能用后续正确调用代替 | A |
| `tool_result_consistent`：link 结果一致性 | 业务自研：终止事件与状态一致性 | 已完成轮次、工具返回记录、对应终止事件 | 核对 SUCCESS/FAILED/TIMEOUT、output.success 与终止事件；Agent SUCCESS 不能与失败工具记录冲突 | 独立路径缺终止事件或覆盖不完整为未知；已取得的相互矛盾记录失败 | A |
| `no_state_change`：link 无副作用 | 业务自研：独立快照契约；比较用 pattern | 独立执行前后快照 | 去掉顶层 run_id 后完整精确比较 | 缺前后任一快照为未知；已知状态变化失败 | A |

`tool_called` 证明发生了请求，不证明工具执行成功。多个调用、禁止调用和每次参数都需验证时，应组合上述断言或使用 `turns_match`，不能将一次名称命中解释为完整工具正确性。

### 3.3 业务终态与确认

| 指标 ID 与对象 | 选型与边界 | 必要证据 | 判定口径 | 缺失或错误处理 | Gate |
| --- | --- | --- | --- | --- | --- |
| `final_state_match`：end_to_end 目标状态 | 业务自研：独立终态与目标投影；比较用 pattern | 独立终态快照、goal_state 或 check.expected | 对预期字典键递归投影后精确匹配；列表仍按顺序和长度比较 | 整个快照缺失为未知；快照中应有字段缺失或不同失败 | A |
| `no_duplicate_side_effect`：end_to_end 重复副作用 | 业务自研：副作用计数契约；比较用 pattern | 独立终态中配置的计数字段 | 实际 count_field 等于 expected_count，默认字段为 mock_backpack_grant_count、默认次数 1 | 整个快照缺失为未知；字段缺失或次数不符失败。只证明该计数约束，不泛化为任意工具幂等 | A |
| `confirmation_requested`：end_to_end 确认请求 | 业务自研：确认事件证据 | 有效 confirmation_requested 或 confirmation_required 事件 | 至少存在一个匹配事件 | 观测到事件可判定；未观测且覆盖不完整为未知 | A |
| `confirmation_accepted`：end_to_end 确认接受 | 业务自研：接受事件证据 | 有效 confirmation_accepted 事件 | 至少存在一个接受事件 | 观测到事件可判定；未观测且覆盖不完整为未知 | A |
| `no_write_before_confirmation`：end_to_end 确认前状态 | 业务自研：确认时序与逐轮状态 | 轮次状态、确认事件、逐轮独立计数快照及初始状态 | 等待澄清/确认，或尚未确认的轮次中，配置计数不得变化；等待状态重置确认标记 | 缺逐轮快照/计数字段为未知；能独立证明的提前变化仍失败。按轮末快照判断，不覆盖同轮内部所有事件顺序；初始字段当前默认 0，fixture 应明确提供 | A |
| `response_consistent`：end_to_end 回复约束 | 业务自研：冻结文字/状态规则；比较用 includes/pattern | 最终回复、最终状态、冻结 expected_response | contains_all 全包含、contains_any 至少一个、forbidden_contains 全不出现，可附加 expected_outcome 精确匹配 | 独立路径缺最终结果为未知；文本或状态不符失败。属于文字规则，不等同于通用事实忠实度 | A |

### 3.4 通用观测与逐轮检查

| 指标 ID 与对象 | 选型与边界 | 必要证据 | 判定口径 | 缺失或错误处理 | Gate |
| --- | --- | --- | --- | --- | --- |
| `observations_match`：module/link/end_to_end 结构化观测 | 业务自研：观测通道与谓词组合；复用匹配/Schema | 冻结 JSON Pointer 和谓词；returned observations 或 independent snapshot | 全部 equals/contains/not_contains/ends_with/schema_valid 谓词满足才通过 | 任一已知不匹配优先失败；否则缺路径为未知；执行未完成时不能从局部匹配判 PASS | A |
| `turns_match`：link/end_to_end 多轮行为 | 业务自研：逐轮契约与证据；复用原生比较 | 冻结轮次预期、实际状态/参数/工具请求及可选终态事件和逐轮状态 | 比较轮数、每轮状态、参数子集、工具顺序/数量/参数及可选状态；同时核对显式要求的逐轮独立状态 | 已知不匹配优先失败；缺轮次、缺终止事件、工具覆盖不足等为未知；部分证据已显示额外调用仍失败 | A |

`observations_match.channel=returned` 是返回内容核验，不能证明数据库写入；`independent` 必须由 Provider 的环境观测通道供给。实现见 [observation_assertions.py](../src/eval_framework/observation_assertions.py)、[turn_assertions.py](../src/eval_framework/turn_assertions.py)。

## 4. 可选语义 Judge

当前 Rubric 为 [semantic-response 1.0](../src/eval_framework/judge_rubrics/semantic_response_v1.json)，通过 [Inspect Model Grading](../src/eval_framework/judges/inspect.py) 对每个声明维度调用一次评分。所有维度是 **0–100 模型评分**，不是关键词命中率或 DeepEval 同名指标的替代分数。

| 维度 ID | 选型与边界 | 评测对象与必要证据 | 判定口径 | 缺证据处理 | Gate |
| --- | --- | --- | --- | --- | --- |
| `completeness` | Inspect 原生：model_graded_qa | 用户输入、最终回复、需要回答的信息/参考事实 | 回复是否包含用户需要的信息 | 空输入/回复、调用错误或非法分数使 Judge 非 COMPLETED；参考事实为空目前不单独拒绝，样本应明确判据 | J |
| `relevance` | Inspect 原生：model_graded_qa | 用户输入和最终回复 | 回复是否围绕用户请求 | 同上；不计算“相关语句数/总语句数” | J |
| `clarity` | Inspect 原生：model_graded_qa | 最终回复及用户任务上下文 | 回复是否清晰、可理解 | 同上；不证明业务正确性 | J |
| `tool_summary_accuracy` | Inspect 原生：model_graded_qa | 最终回复、提供给 Judge 的工具结果摘要和参考事实 | 回复是否准确概括工具结果事实 | 工具事实为空目前不单独拒绝；不能将没有事实可核对的评分解释为工具成功证据 | J |

共同口径与限制：

- `judge_result.score = Σ(维度得分 × 冻结维度权重) / Σ权重`，四舍五入至两位小数；`judge_result.passed` 要求每个维度都达到自身阈值，不只看加权平均分。
- `required=false` 时仅作辅助诊断；`required=true` 且 Judge 未完成时最终质量为 INCONCLUSIVE。确定性 FAIL 和关键失败不能被 Judge 覆盖。实现见 [judge.py](../src/eval_framework/judge.py)。
- 只有执行完成、评测有效且没有未知适用断言时，当前入口才调用 Judge；输入和回复受 Rubric 的字符上限约束。Judge 未运行、非适用与调用失败需要分别读取状态，不能统一显示为 0 分。
- 当前请求包含首个用户输入、最终回复、工具摘要及参考事实，不是完整多轮对话输入。不能把 `completeness` 当成已接通的 Conversation Completeness。
- CLI 兼容入口和显式 Python API 可用；Suite 文件中的 Judge Profile 尚未迁移，不能因字段存在就宣称可配置。参见[架构限制](architecture.md#5-当前架构与目标架构的差距)。
- Judge 重试粒度为整次多维评分，metadata.retry_scope=whole_judge_attempt；某维度临时失败后重新评整个维度组，不能混用前一尝试的局部分数。生产 Inspect 请求重试设为 0；整次尝试的共享超时与审计仍由业务适配负责。
- Judge backend、版本、Rubric、Prompt、模型和配置是可比性的一部分。不同 Judge 方法不得沿用旧阈值或直接比较历史分数。

## 5. 已实现的分数和运行指标

`summary.metric_version` 标识聚合语义；`summary.performance` 是延迟和 Judge 用量的正式快照，旧结果这两个字段可为空。

本节是当前字段口径；“业务自研”的计数、取最大值、usage 采集只是聚合/采集适配，不另建统计平台。所有正式汇总仍由 Inspect Metric 阶段调用；适用性、计划分母和别名由 Evaluator 定义。实现入口为 [scoring.py](../src/eval_framework/scoring.py)、[evaluation_policy.py](../src/eval_framework/evaluation_policy.py)、[inspect_metrics.py](../src/eval_framework/inspect_metrics.py)、[stability.py](../src/eval_framework/stability.py)。

### 5.1 Trial 与运行汇总

令 R 为实际保存的 Trial 集合；B 为 agent_benchmark 模式下 R 中 quality_conclusion 不等于 NOT_APPLICABLE 的集合。

| 字段与对象 | 选型与边界 | 必要证据 | 计算口径 | 缺失处理与边界 | Gate |
| --- | --- | --- | --- | --- | --- |
| `CaseResult.score`：Trial 断言分 | 业务自研：权重、舍入及未知规则 | 适用断言、权重、判定 | 100 × 通过断言权重之和 / 适用断言权重之和；Decimal HALF_UP 保留两位 | 无适用项、任一未知适用项或评测无效时为 null；已有失败仍保留 FAIL | A |
| `CaseResult.quality_conclusion`：Trial 最终质量 | 业务自研：结论政策与关键项否决 | 断言分、关键项、执行/有效性、可选必需 Judge | 按业务判定政策生成 PASS/FAIL/INCONCLUSIVE 等，不以平均分直接推断 | 执行未完成不能保持 PASS；有效性 INVALID 时分数为空且已证实失败保留 | A/J |
| `summary.total_cases` / `total_trials`：运行规模 | 业务自研：标识去重与记录计数适配 | R 的 case_id/trial_id | 唯一 case_id 数 / Trial 记录数 | 不表示完整数据集规模；筛选信息与计划次数另读 manifest/config | D |
| `summary.execution_status_counts` / `quality_counts` | Inspect 原生：frequency；业务状态映射 | R 的执行状态与最终质量 | 分别按状态计数，单位为 Trial | 执行异常和质量失败属于两条轴，不能混成一个错误率 | P：其他检查消费原状态 |
| `summary.framework_completion_rate`：执行完成率 | Inspect 原生：mean；适配执行状态 | R.execution_status | 100 × COMPLETED Trial 数 / R 的数量 | 执行异常保留在分母；不评价质量。空运行不能作为有效放行依据 | P：minimum_execution_rate |
| `summary.strict_assertion_pass_rate`：正式汇总通过率 | Inspect 原生：mean；冻结适用分母 | B 的最终 quality_conclusion | 100 × PASS Trial 数 / B 的数量 | B 为空或非 agent_benchmark 时为 null；FAIL/INCONCLUSIVE 保留分母。字段名虽含 assertion，实际读取最终质量，可能包含必需 Judge 的影响 | P：minimum_strict_pass_rate；core_labels 另见第 6 节 |
| `summary.agent_case_pass_rate`：历史别名 | Inspect 原生：引用同一正式率 | 同上 | 与 strict_assertion_pass_rate 使用同一计算值 | 不按唯一 Case 另算一次，不作为第二条通过率展示 | 同上 |
| `summary.core_behavior_match_rate`：诊断匹配率 | 业务自研：诊断准入规则；比例用 mean | B 的执行/有效性、质量及 diagnoses | 已完成且有效，并且 PASS，或 diagnoses 非空且全部为 PROTOCOL_NAMING_MISMATCH 的 Trial 数 / B 的数量 × 100 | B 为空为 null；这是诊断规则口径，不是另一套宽松正式 Gate | D |
| `summary.average_score`：平均断言分 | Inspect 原生：mean；选非空分数 | R 中非 null 的 score | 非空分数的算术平均，保留两位 | 无可评分 Trial 为 null；分母不同于通过率；不能独立证明全部样本合格 | D |
| `summary.by_scope` / `by_task_id` / `by_expected_intent` / `by_actual_intent`：分组诊断 | Inspect 原生：grouped / frequency / mean | R 的 scope/task/预期及实际意图、最终质量 | 每组 count、applicable_count、pass_count、pass_rate；通过率分母为组内适用 Trial，FAIL/INCONCLUSIVE 保留 | 排除 NOT_APPLICABLE，与全局率共用适用性规则；非 agent_benchmark 或全不适用时 rate 为 null。count/pass_count 保留原始记录计数；by_intent 是 by_expected_intent 的别名 | D |
| `summary.failed_assertions`：断言失败频次 | Inspect 原生：frequency；选择明确失败项 | R.assertion_results | 按断言名计数 passed=false 的记录 | 未知不计作失败；无记录不证明该维度已覆盖；不是失败率 | D |

断言得分达到阈值也必须满足关键项规则。若存在未知适用断言，得分为空；此时任一已知失败使断言结论为 FAIL，否则为 INCONCLUSIVE。完整可评分时由阈值和 critical 决定结论。参见[评分测试](../tests/test_execution_scoring.py)及[原生聚合测试](../tests/test_native_aggregation.py)。

### 5.2 重复运行与稳定性

令 k 为冻结计划的每 Case Trial 数。当前稳定性聚合对“已出现至少一条 Trial”的 Case 建组；有 NOT_APPLICABLE Trial 的 Case 不进入运行级通过率聚合。完全未进入运行的 Case 还需由运行计划和完整性检查识别，不能从缺席推断通过。

| 字段与对象 | 选型与边界 | 必要证据 | 计算口径 | 缺失处理与边界 | Gate |
| --- | --- | --- | --- | --- | --- |
| `stability.cases[].trial_pass_rate` | Inspect 原生：mean；适配计划分母 | 单 Case 的计划 k、最终质量 | 100 × PASS Trial 数 / k | 已分组 Case 的缺失 Trial 作为“未证明通过”保留分母；含 NOT_APPLICABLE 时为 null | D |
| `stability.trial_pass_rate` | Inspect 原生：mean；适配计划分母 | 所有适用 Case 的计划与结果 | PASS 总 Trial 数 / 适用 Case 的计划 Trial 总数 × 100 | 无适用 Case 为 null；不是 summary 中基于已保存记录的同名替代指标 | D |
| `stability.cases[].pass_at_k` / `pass_power_k` | Inspect 原生：pass_at / pass_k | 单 Case 的 k 次结果 | 至少一次 PASS / 全部计划 Trial 均 PASS，返回布尔值 | 缺少 Trial 不能满足全部通过；不适用 Case 当前布尔字段为 false，需结合 not_applicable_count 解读 | D |
| `stability.pass_at_k_rate` / `pass_power_k_rate` | Inspect 原生：mean；选择适用 Case | 适用 Case 的上述布尔值 | 满足条件的 Case 数 / 适用 Case 数 × 100 | 无适用 Case 为 null；不是代码生成基准的无偏 pass@k 估计量 | P：minimum_pass_power_k_rate 只使用后者 |
| `stability.cases[].quality_volatile` | 业务自研：最终质量集合变化 | 同一 Case 已观测的最终质量结论 | 结论种类大于 1 为 true | 单 Trial 或结果缺失不能证明稳定；该字段不把未出现 Trial 当作一种质量结论 | P：maximum_unstable_cases 统计 true 的 Case 数 |
| `stability.cases[].output_volatile` | 业务自研：业务输出规范化与 Hash | 规范化 module/turn/state/observations 或 Provider normalizer | 去除配置的易变字段后，输出 Hash 种类大于 1 | 文字差异也可能导致 true；不等于语义回归 | D |
| `stability.cases[].critical_failure_any` | 业务自研：已证实关键违规规则 | 各 Trial 的关键断言结果 | 任一 critical=true 且 passed=false | 未知不算已证明失败；仍需有效性与覆盖检查 | D：保留证据，Gate 另检查配置的断言 |

### 5.3 延迟与用量

| 字段与对象 | 选型与边界 | 必要证据 | 计算口径 | 缺失处理与边界 | Gate |
| --- | --- | --- | --- | --- | --- |
| `CaseResult.latency_ms`：Trial 执行耗时 | 业务自研：Provider 适配层计时边界 | Runner 单调时钟 | 从 Trial 准备开始，到执行、观测快照、清理等完成的毫秒数 | 包含环境开销；不包含后续正式 Scorer/Judge 时间，不是单次模型响应时延 | P：延迟检查的输入 |
| `summary.average_latency_ms` | Inspect 原生：mean | R.latency_ms | 所有已保存 Trial 的平均值，包含执行异常 Trial | 当前空集合序列化为 0，不能解释为真实零延迟 | D |
| `summary.max_latency_ms` | 业务自研：标准 max 聚合适配 | R.latency_ms | 所有已保存 Trial 的最大值，包含执行异常 Trial | 当前空集合序列化为 0，不能解释为真实零延迟 | D |
| `summary.median_latency_ms` | Inspect 原生：median_score | R.latency_ms | Inspect median_score；偶数样本取中间两值平均 | 当前空集合为 0；报告标签为“中位延迟”，不再称为 P50 | D |
| `summary.performance.latency_p50_ms` / `latency_p95_ms`；`stability` 对应字段 | 业务自研：唯一 nearest-rank 口径 | 已保存 Trial 延迟列表 | summary.performance 计算并保存一次；运行级 stability 复用，Case 级按自身样本计算 | 空列表为 null；latency_sample_count 保存样本数。与统计中位数是两个有明确名称的指标 | P：maximum_latency_p50_ms / maximum_latency_p95_ms；Gate 读取保存值 |
| `judge_result.token_usage` | 业务自研：采集 Inspect 返回 usage | Judge 客户端上报的 usage | Inspect 适配器记录 input_tokens、output_tokens；汇总阶段保存到 summary.performance.judge_token_totals（逐 Trial）、judge_token_total（已知值总和）和 judge_token_max（已知值最大值）；比较和 Gate 读取 | 缺 usage 为空，不是 0 成本；当前只覆盖 Judge 返回的用量，不覆盖 Agent、工具、费用及失败重试的完整账单 | P：maximum_token_usage / maximum_token_increase_percent |

P95 门禁要求 `minimum_percentile_samples`，不足时 REVIEW；默认数量见版本化 GatePolicy，不在字典中重新设阈值。当前 Gate 对有记录的 Judge token 取单 Trial 最大值；全部缺失为 REVIEW，部分缺失不会自动触发全量覆盖检查，因此不能宣称限制了整轮 Agent 总 Token 或总费用。

## 6. Gate 和证据检查的实际含义

以下检查消费已保存结果或显式比较产物，不产生第二套 Agent 评分。入口见 [gating.py](../src/eval_framework/gating.py)、[GatePolicy](../src/eval_framework/phase2_schemas.py)及[比较实现](../src/eval_framework/comparison.py)。

每份策略用 `policy_id` 和 `version` 标识；阈值与引用列表应显式保存，不从指标名称推导默认放行标准。

| 检查或策略 | 选型与边界 | 对象与必要证据 | 当前计算/判定 | 缺失处理与限制 |
| --- | --- | --- | --- | --- |
| `EVALUATION_INVALID` | 业务自研：发布政策；消费正式结果 | Trial.evaluation_validity | INVALID Trial 数必须为 0 | 一旦有无效 Trial，此检查 FAIL；质量 FAIL 证据仍保留 |
| `ONBOARDING_RELEASE_INELIGIBLE` | 业务自研：发布政策；消费正式结果 | 候选导入来源状态 | 有 onboarding 时，release_eligible 必须为 true | 草稿静态结果不能用于正式发布放行 |
| `minimum_strict_pass_rate` + `core_labels` | 业务自研：发布政策；消费正式结果 | 标签命中的 Trial 和最终质量 | core_labels 非空时选择命中任一标签的 Trial 并去重，使用同一适用性规则排除 NOT_APPLICABLE；范围等于完整新运行时直接复用 summary；无标签时读取全局正式率 | 全不适用或非 agent_benchmark 为 REVIEW；标签子集分数和命中 Trial 引用保存在 Gate 检查中，不覆盖全局率 |
| `zero_tolerance_assertions` | 业务自研：发布政策；消费正式结果 | 指定已注册断言的结果及证据 | 统计 passed=false 的断言记录，要求 0 | 未知不算明确失败；未知断言名被策略引用校验拒绝。不能仅凭此检查 PASS 宣称证据充分 |
| `zero_tolerance_labels` | 业务自研：发布政策；消费正式结果 | 命中标签的 Trial 最终质量 | quality_conclusion 不等于 PASS 的记录数必须为 0 | INCONCLUSIVE 等也阻断；未知标签被拒绝 |
| `required_judge_dimensions` | 业务自研：发布政策；消费正式结果 | 指定维度的已保存分数 | 取该维度已有分数最小值，与配置阈值比较 | 完全没有该维度时引用校验报错；部分 Trial 缺维度并不会自动证明全量覆盖，需配合冻结 required 和适用范围 |
| `require_trace_evidence` | 业务自研：发布政策；消费正式结果 | Trial.trace_analysis | 统计 trace_analysis 为 None 的 Trial，有缺失则 REVIEW | 只检查分析对象存在；空时间线、采集丢失、独立性不能靠此字段证明。应另读 evidence_status/manifest 和断言要求 |
| `maximum_regressions` | 业务自研：发布政策；消费正式结果 | COMPARABLE 的 comparison | len(newly_failed) + len(new_execution_errors) | 这是两类回归条目之和，可能同时指向一个 Trial，不是去重缺陷数 |
| `require_comparison` 及依赖比较的检查 | 业务自研：发布政策；消费正式结果 | 显式 baseline/candidate 和指纹 | 要求 COMPARABLE 且 candidate Hash 匹配 | 缺比较、不可比或身份错误为 INVALID_COMPARISON；不能选择页面中的另一基线代替 |
| `maximum_latency_p50_increase_percent` / `maximum_latency_p95_increase_percent` / `maximum_token_increase_percent` | 业务自研：发布政策；消费正式结果 | 可比的配对 Trial 差异 | 新 comparison.performance 复用两侧正式性能快照；Gate 仅计算增幅 (candidate − baseline) / baseline × 100；旧 comparison 由共享适配器从配对差异投影 | 任一侧不可算为 REVIEW；基线与候选均为 0 时增幅 0，基线 0 而候选非 0 为无穷大；缺失用量不能解释为完整成本 |

Gate 最终结论优先级是 INVALID_COMPARISON → REVIEW_REQUIRED → FAIL → PASS；各条 FAIL/REVIEW 都必须保留。未设置门禁阈值不等于该维度已经验收。Trace issues 提供调查线索，不自动成为质量分数或最终根因。

2026-10-28 去重版本：summary.metric_version = business-metrics-v2，Gate 为 gate-v2，比较为 comparison-v2，Inspect 业务适配为 inspect-domain-v3。全局、分组、标签子集共享适用性规则，但范围仍分别标识；计划 Trial 稳定性继续使用冻结计划分母。性能快照由 Inspect Metric 阶段生成一次，Gate 和比较消费已有值。旧结果没有新性能字段时只做内存投影，不改写文件或历史分组值；指标版本不同返回 METRIC_VERSION_MISMATCH，需重跑基线。

## 7. 候选指标的逐项选型

以下 ID 是**文档候选标识**，不属于当前 Assertion Registry、Judge Rubric 或 GatePolicy。10 项中，5 项选定 DeepEval 复用、1 项业务自研、4 项暂不适用；Conversation Completeness 已接入为诊断指标 `conversation_completeness`，其余为候选；**Conversation Completeness 标记 D，其余 Gate 标记 N**。接入不等于完成业务校准。

### 7.1 RAG 与答案事实

| 候选 ID 与对象 | 选型与边界 | 必要证据 | 目标计算口径 | 缺证据处理 | 接入条件 |
| --- | --- | --- | --- | --- | --- |
| `candidate.rag_faithfulness`：回答依据 | DeepEval 复用：FaithfulnessMetric | 用户问题、回答、实际检索片段及来源版本 | 0–1；声明抽取后逐条核验，严格支持配置下为有依据声明数 / 可核验声明数；保留逐声明依据 | 未记录检索上下文为未知；确认检索为空仍需判断无依据声明；无可核验声明为不适用，不能默认满分 | 批次 B2；[Faithfulness](https://deepeval.com/docs/metrics-faithfulness) 默认“无矛盾”不等于严格支持。固定支持判据、penalize_ambiguous_claims、Template 和模式，再校准 |
| `candidate.rag_context_precision`：检索排序 | DeepEval 复用：ContextualPrecisionMetric | 查询、实际有序检索片段、审核过的参考答案/相关性标注 | 0–1；相关位置的 Precision@i 加权平均：Σ(Precision@i × rel_i) / Σrel_i | 检索记录缺失为未知；已记录但无相关片段按冻结规则记 0；不混入无需检索样本 | 批次 B2；采用 [Contextual Precision](https://deepeval.com/docs/metrics-contextual-precision)，保留真实顺序，不改写为简单相关片段占比 |
| `candidate.rag_context_recall`：检索覆盖 | DeepEval 复用：ContextualRecallMetric | 查询、审核过的参考事实、实际检索片段 | 0–1；检索内容可支持的参考事实数 / 应覆盖参考事实数 | 无参考事实或无检索记录为未知；确认检索为空且有应答事实时为 0 | 批次 B2；采用 [Contextual Recall](https://deepeval.com/docs/metrics-contextual-recall)，不冒充全语料相关文档召回率 |
| `candidate.answer_fact_correctness`：答案正确性 | 暂不适用：事实 P/R/F1 算法尚未选定 | 用户问题、回答、独立审核的事实集 | 拟议 0–1；分别报告事实 precision/recall/F1，需定义事实拆分、匹配、矛盾与遗漏 | 无可信 reference 为未知 | 先验证事实级标签与确切算法。通用 G-Eval / model_graded_qa 分数不等于事实 F1；Inspect token F1 也不是语义事实 F1。暂不自研声明链 |

忠实度与正确性分开：回答复述过期文档，可能忠实但事实错误。生成模型写出的 reference 需审核后成为 Oracle。上述三个 RAG 维度分别评回答依据、检索排序和参考事实覆盖，不再额外维护一份“自研 RAG 总分”。

### 7.2 多轮、规划与风险

| 候选 ID 与对象 | 选型与边界 | 必要证据 | 目标计算口径 | 缺证据处理 | 接入条件 |
| --- | --- | --- | --- | --- | --- |
| `conversation_completeness`（已接入诊断）：整段对话需求覆盖 | DeepEval 复用：ConversationCompletenessMetric | 完整有序 user/assistant 对话；校准集标注需求取消与变更 | LLM 模式，0–1；由算法提取用户意图，计算已满足意图数 / 被评估意图数；不另算一套人工需求分数 | 缺轮次、未结束或无法形成有效意图集合为未知/不适用，不能默认通过 | 批次 B1 首项已接入，默认关闭、尚未校准；采用 [Conversation Completeness](https://deepeval.com/docs/metrics-conversation-completeness)。取消、需求变更须通过校准；业务动作成功仍由独立终态证明 |
| `candidate.knowledge_retention`：跨轮事实保持 | DeepEval 复用：KnowledgeRetentionMetric | 完整对话、用户事实及更正顺序；冻结记忆范围 | LLM 模式，0–1；未发生知识遗忘的已评估 assistant 轮次 / 已评估 assistant 轮次。按锁定版本明确无前置知识的轮次是否计入 | 缺历史轮次为未知；无可评估知识的对话不适用。不得通过丢弃评分失败轮次提高分数 | 批次 B1；采用 [Knowledge Retention](https://deepeval.com/docs/metrics-knowledge-retention)。校准用户纠正与重复追问；已冻结的参数更正继续读 turns_match |
| `candidate.plan_quality`：显式计划质量 | 暂不适用：优先验证 DeepEval PlanQualityMetric 的公共 Trace 接入 | 实际可见计划、目标、约束与完整 Trace | 未来复用库的计划质量评分，保留原生 0–1 范围及原因；并非已实现的自研多维 0–100 Rubric | 无可见计划为不适用或未知；不得照搬“未提取到计划即满分”，也不要求采集私有思维链 | [Plan Quality](https://deepeval.com/docs/metrics-plan-quality) 当前为 trace-only；官方不支持普通 standalone。先证明可从现有证据经公共接口接入且不增加执行循环 |
| `candidate.step_efficiency`：执行效率 | 暂不适用：优先验证 DeepEval StepEfficiencyMetric 的公共 Trace 接入 | 完整步骤/工具轨迹、允许的重试与澄清规则、成功证据 | 未来复用库的 0–1 轨迹效率模型评分；不是可避免步骤的确定性占比 | 轨迹缺失为未知；无步骤按任务适用性处理；效率高不改变任务失败结论 | [Step Efficiency](https://deepeval.com/docs/metrics-step-efficiency) 同为 trace-only；公共接入与业务重试语义校准通过后再选型 |
| `candidate.content_safety`：内容政策遵守 | 暂不适用：当前没有已冻结的内容风险专项清单 | 输入/输出、业务政策、审核过的风险标签 | 逐政策单独定义指标，不能把一个 Toxicity 分数当作完整安全分 | 未覆盖的风险不能声明安全；不适用政策不进分母 | 明确风险需求后优先逐项复用 [Toxicity](https://deepeval.com/docs/metrics-toxicity) 等专项算法。权限、确认、禁止副作用仍由现有证据断言负责 |
| `candidate.fault_recovery`：异常后的业务恢复 | 业务自研：故障实验契约；复用现有断言 | 可信故障注入及触发证明、重试轨迹、独立终态和副作用记录 | 0–100%；满足恢复目标且无禁止副作用的 Trial 数 / 已确认触发目标故障的 Trial 数 | 故障未触发为无效实验；缺触发/终态证据为未知；同时报告计划与实际触发数 | Provider 具备注入证明后组合 turns_match/final_state_match 等；由 Inspect 聚合，不另写恢复成功评分引擎 |

以上复用候选先固定 `eval_mode=llm` 的语义；具体参数以实施时锁定版本的公共 API 为准。hybrid/system_one 的结果不能直接套用这些公式，也不能与原模式混作同一基线。需要额外修改库模板才能满足业务时，模板及语义差异也必须版本化；若算法仍不满足，就保持候选，不用包装代码伪装成已验收。

## 8. 接入顺序与验收清单

### 8.1 接入批次

B0 已实现首项所需适配，B1 的 Conversation Completeness 已接入，人工校准与 Knowledge Retention 仍待完成。使用说明见 [Conversation Completeness](conversation_completeness.md)。已有确定性评分和四个原生 Judge 保持现有职责。先完成 B0，默认推进已有多轮业务基础的 B1；B2 按实际 RAG 需求启动，不给意图分类或礼物发放场景补造检索上下文。

| 批次 | 范围与交付物 | 进入条件 | 完成验收的证据 |
| --- | --- | --- | --- |
| B0：共用适配 | 一个供 Inspect Scorer 调用的 DeepEval 指标适配层；版本化指标配置、输入映射、状态和结果映射；只实现首批所需接口 | 选定锁定版本；确认 5 个指标的公共 standalone / async API | 使用真实库与受控模型输出验证异步调用、超时、每样本独立实例、无隐式托管上传、Oracle 隔离；每个启用指标仅产出一份正式结果 |
| B1：多轮专项 | ConversationCompletenessMetric、KnowledgeRetentionMetric | Provider 可提供完整有序 role/content 对话，不能只用当前 Judge 的首问+最终回复；有人工审核的多轮校准集 | 覆盖需求满足/遗漏/取消/更改、事实纠正、重复追问、缺轮次、无记忆需求；保存逐意图/逐轮判断、原因和证据引用；与业务关键失败共同存在时仍保留 FAIL |
| B2：RAG 专项 | FaithfulnessMetric、ContextualPrecisionMetric、ContextualRecallMetric | 实际 retrieval_context、顺序、来源版本；Precision/Recall 有可信 reference；存在真实知识问答样本 | 覆盖支持/矛盾/无依据声明、空检索、无相关片段、排序变化、参考事实遗漏与缺记录；核对分子分母、严格支持参数和空集合行为 |
| B3：待条件具备 | 事实正确性、规划、步骤效率、内容风险重新评估；故障恢复按 Provider 能力推进 | 第 7 节各项重启条件满足 | 先更新唯一选型与版本，再进入对应批次；不为这些候选预建第二套 Runner、Trace 或算法链 |

### 8.2 共用接入验收

- **唯一入口**：从 Inspect Scorer 调用公开 `a_measure` 等已验证接口；不调用 DeepEval `evaluate` / `assert_test` / 数据集执行循环。指标内部的声明抽取与多次模型判断属于一个指标算法，不再额外跑一份同名原生 Judge。
- **薄适配**：每个样本独立创建有状态的 Metric；模型接入优先使用 `DeepEvalBaseLLM` 适配现有 Inspect 模型传输、凭据与总超时预算，不恢复旧的第二套模型客户端。不得用同步嵌套事件循环或私有字段注入绕过 API 限制。
- **输入与缺失**：Oracle 只在可信评分侧解析；检索片段和对话来自实际执行证据。缺证据、未运行、不适用、评分错误分别记录；部分 verdict 生成失败时整项不得按剩余分母判通过。无有效判定、非法分数、NaN、超时均不能变成满分或普通业务失败。
- **单次保存与消费**：明确唯一领域保存字段，保留库原始分数、范围、原因、逐项证据、模型用量、状态和算法身份。分数转换如需 ×100 必须声明；报告、Gate、Langfuse 只消费已保存结果，指标内部缓存也须绑定完整输入和配置身份。
- **可比性与校准**：锁定库版本/提交、Metric 类、Template/Prompt、模型、模式、参数、阈值及适用范围。实施前在审核集上约定验收线，报告误判/漏判、关键漏判、重复评分波动和成本；当前没有这些实测数，不能宣称已校准。改变算法或模式需新版本和新基线。
- **运行边界**：普通本地评测不因导入库、已有 Confident 凭据或调用 Metric 而隐式上传/启用遥测；验证所选版本的初始化、环境加载与网络行为。模型调用按显式配置执行；托管展示继续由现有 Langfuse 导出路径负责。
- **进入正式结果与门禁分开**：接入验收后可保存正式诊断分数；升为阻断项还需明确适用范围、覆盖检查、校准阈值与版本化政策。高语义分永不覆盖独立证明的 critical 违规；缺专项评分也不能被视为通过。

### 8.3 指标定义与维护

新增指标先提供一条包含以下信息的定义，再决定是否实现：

| 必填项 | 内容 |
| --- | --- |
| 身份与状态 | 稳定 ID、版本、唯一选型、实现状态、对应业务决策；选定不等于接通 |
| 对象与粒度 | scope、适用样本、Trial/Case/Run，过滤与排除规则 |
| 证据与来源 | Oracle、观察字段、来源/时间/版本、是否要求独立性与完整性 |
| 计算与阈值 | 范围、方向、公式、分子/分母、舍入、空集合、阈值依据 |
| 未知与失败 | 不适用、缺证据、执行错误和业务违规分别怎样处理 |
| Gate 与权威结果 | 诊断或阻断、唯一计算入口、保存字段、消费方 |
| 校准与回归 | 人工标注集、误判/漏判、重复评分波动、成本、历史可比性及测试入口 |

采用顺序：Inspect 已有同语义公共实现则复用；缺少专项算法且 DeepEval 已具备时，优先接入 DeepEval；只有业务独有规则或确认的库能力缺口才自研。DeepEval 复用不局限于参考资料或临时实验，验收后由 Inspect Scorer 产出唯一正式结果；阈值和 Gate 权限仍由冻结政策指定。

一个最小验证样本组应同时包括：明确通过、明确失败、证据缺失、部分证据已证明失败，以及高语义分但有关键违规的案例。对于模型评分，用同一份人工审核样本比较业务一致性、严重漏判、重复评分波动和成本；未经校准不升为阻断项。模型调用及托管导出继续遵循显式配置和凭据边界。

### 8.4 示例：礼物发放

用户要求发放礼物后尚未确认，Agent 回复“已发放”，独立数据库计数从 0 变为 1：

1. tool_called 只能证明请求过工具；tool_args_match 通过也不代表请求时机正确。
2. no_write_before_confirmation 依据等待状态和逐轮快照失败；若冻结为 critical，其他项高分不能抵消。
3. completeness/clarity 即使高分，也不能改变确定性 FAIL。
4. 若数据库快照缺失，状态断言不能凭“已发放”判成功；已有禁止调用证据仍可证明对应违规。
5. 这一业务场景不需要 RAG 指标；只有回答依赖知识文档时，才考虑第 7 节的检索与事实指标。

### 8.5 验证入口与参考资料

- 确定性与缺证据：[执行评分测试](../tests/test_execution_scoring.py)、[原生评分测试](../tests/test_native_scoring.py)、[独立证据测试](../tests/test_independent_evidence.py)、[逐轮测试](../tests/test_multiturn_execution.py)、[外部观测测试](../tests/test_external_provider.py)。
- Judge：[Judge 政策测试](../tests/test_judge.py)、[Inspect Judge 测试](../tests/test_inspect_judge.py)。
- 分母和稳定性：[原生聚合测试](../tests/test_native_aggregation.py)、[多 Trial 测试](../tests/test_multi_trial_stability.py)。
- 指标权威性、分母、版本与历史读取：[汇总权威测试](../tests/test_metric_authority.py)。
- Gate 与可比性：[门禁测试](../tests/test_gating.py)、[比较测试](../tests/test_comparison.py)。
- 外部方法参考：[DeepEval 指标目录](https://deepeval.com/docs/metrics-introduction)。各候选行链接到对应官方定义；2026-10-28 的网页能力不代表本地保留源码版本已经接入生产。
