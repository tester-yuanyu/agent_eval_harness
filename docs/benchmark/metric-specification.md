# 当前 Benchmark 指标规格

本文定义 `file-tools-v2` 当前主链路的指标与汇总口径。Inspect 负责执行调度和日志，DeepEval 承载正式确定性评分与诊断指标，Langfuse 只展示保存结果。`packages/evaluator/docs/metric_dictionary.md` 描述旧 Suite 的历史语义，不能用于解释本文指标、版本或 verdict。

## 1. 角色、记录与缺失值

一次 Trial 由 `(case_id, trial)` 唯一标识；任务级指标每次 Trial 一条，`generation`、`tool`、`turn`、`chain` 指标按对应事件或检查点各记一条。指标记录至少保留 `name`、`score`、`threshold`、`success`、`formal`、`version`、`reason`；节点级记录还保留 `scope`、`event_id`，需要多条证据时保留 `evidence_ids`。

确定性二元指标的已评分范围是 `{0, 1}`，阈值为 `1.0`。`score=None` 表示没有足够证据，不能改写为 0 或 1。诊断记录还使用以下状态：

- `SCORED`：已产生可解释分数；
- `MISSING`：适用，但证据缺失、冲突、预算未覆盖或无法评分；
- `ERROR`：评分执行失败，分数保持空；
- `NOT_APPLICABLE`：该证据不适用此指标，不进入适用分母。

`formal=True` 的记录决定正式 verdict；`formal=False` 只用于诊断。诊断高分不能抵消正式失败，诊断低分也不能单独把 Trial 判为失败。

正式 verdict 的计算顺序如下：

1. 任务结构、工具策略、执行状态分类或来源身份无效时，返回 `INVALID`，`validity=INVALID`，不生成指标分数。
2. 已完成执行缺少明确完整证据，或初态、终态、事件、轮次等关键测量缺失时，返回 `INCONCLUSIVE`，`validity=VALID`，不把缺失记为失败。
3. 证据有效时，只看正式指标：任一 `success=False` 得到 `FAIL`；没有失败但任一正式分数或成功状态为空，得到 `INCONCLUSIVE`；其余为 `PASS`。

Agent 自身的 `timeout` 或已归类的 Agent error 在终态证据可用时属于有效 Trial，通常由 `task_success=0` 得到 `FAIL`。环境、Provider、Harness 错误属于无效 Trial，不能算作 Agent 失败。

## 2. 正式任务与模型决策指标

下表中的“公式”描述单条指标记录。`I(condition)` 表示条件成立为 1，否则为 0；所有 Oracle 检查均来自私有评分输入，不进入 Agent 消息。

| 指标 | 粒度与范围 | 公式与证据 | 适用、缺失与角色 | 版本 |
| --- | --- | --- | --- | --- |
| `task_success` | Trial；0/1 | `I(execution status == completed AND evaluate_oracle(...).success)`。Oracle 要求初态与冻结 fixture 一致、终态 UTF-8 文件精确满足 `expected_files`/`absent_files`/保留与额外文件规则、轮次数正确、指定回复 token 命中；模块和隔离决策任务还包含其专用语义检查。 | 所有证据有效的 Trial；正式。关键证据在评分前缺失时整个 Trial 为 `INCONCLUSIVE`，不生成 0。 | `file-tools-deepeval-v2.2`；Oracle `file-tools-oracle-v1` |
| `workspace_policy` | Trial；0/1 | `I(no oracle policy violation AND every observed tool name in allowed_tools)`。Policy violation 只包括应缺失文件出现、应保留文件变化/删除、额外文件，以及工具 allowlist 违规。 | 所有证据有效的 Trial；正式。预期文件内容错误由 `task_success` 负责，不能用本指标替代。 | `file-tools-deepeval-v2.2` |
| `interactive_evidence` | Trial；0/1 | `I(events 中至少有一条 type=tool)`。 | 有 `required_tools` 的非 decision、非离线参考 Agent Trial；正式。无工具调用是 0，不是“无数据”。离线确定性参考不生成该指标。 | `file-tools-deepeval-v2.2` |
| `decision_call_policy` | generation；0/1 | `I(存在 decision_call_count 检查 AND 全部通过)`，检查调用数不超过私有上限，并满足是否允许不调用工具。 | `execution_mode=decision`；正式；绑定唯一非 Judge generation。 | `file-tools-deepeval-v2.2` |
| `decision_tool_selection` | generation；0/1 | `I(每个模型工具调用均属于私有 acceptable_tools)`。 | decision 输出包含工具调用时生成；正式。 | `file-tools-deepeval-v2.2` |
| `decision_arguments` | generation；0/1 | `I(每个工具调用参数以严格 JSON 类型和值满足私有语义参数子集)`。 | decision 输出包含工具调用时生成；正式。 | `file-tools-deepeval-v2.2` |
| `decision_schema` | generation；0/1 | `I(每个工具调用参数通过当次记录的 JSON Schema)`。 | decision 输出包含工具调用时生成；正式。 | `file-tools-deepeval-v2.2` |
| `tool_correctness` | Trial；0～1 | DeepEval `ToolCorrectnessMetric` 的工具名覆盖率：只匹配 `required_tools` 名称，忽略顺序，允许额外调用，不要求唯一执行路径。 | 有 `required_tools` 的非 decision 任务；**诊断**。它不检查参数语义、执行结果或终态，失败不改变 verdict。 | `file-tools-deepeval-v2.2` |

`TaskSuccessMetric`、`WorkspacePolicyMetric` 和 decision 指标把多个底层检查合并为一个二元值，不以检查数为分母做平均。因此，一个关键检查失败不会被其他检查稀释。

## 3. 轨迹与恢复指标

轨迹记录要求事件 ID 非空且唯一。ID 缺失或重复时只生成 `trajectory_evidence` 空分记录；若任务声明了任一必需 checkpoint，该空分记录为正式指标，否则为诊断。

| 指标 | 粒度与范围 | 公式与证据 | 适用、缺失与角色 | 版本 |
| --- | --- | --- | --- | --- |
| `tool_allowed` | 每次 tool；0/1 | `I(event.name in task.allowed_tools)`。 | 有工具事件时；诊断。正式 allowlist 仍由 `workspace_policy` 执行。 | `file-tools-trajectory-v1` |
| `tool_schema` | 每次 tool；0/1 | 以当次记录的本地 JSON Schema 校验 `event.input`。只判结构，不判参数语义。 | Schema 缺失、无效或含外部 `$ref` 时为 `MISSING`；诊断。 | `file-tools-trajectory-v1` |
| `checkpoint:<id>`，`turn_files` | 指定 turn；0/1 | `I(同轮 snapshot 中每个 expected_files 路径内容精确相等)`；额外路径不参与该 checkpoint。 | `required=true` 时正式，否则诊断。必须使用同轮 snapshot，不能用最终状态补齐；缺 snapshot 或链接事件为空分。 | `file-tools-trajectory-v1` |
| `checkpoint:<id>`，`tool_args` | 指定 tool/turn；0/1 | 在执行完成且非 incomplete 的候选调用中，存在一次调用使 checkpoint 参数成为 `normalized_input`（缺省回退到 `input`）的严格类型递归子集。允许额外参数及此前失败尝试。 | 完整轨迹中找不到匹配为 0；不完整轨迹为 `MISSING`。角色由 `required` 决定。 | `file-tools-trajectory-v1` |
| `checkpoint:<id>`，`tool_order` | chain；0/1 | 在已执行、带 `end_time`、非 incomplete 的事件序列中，存在 `before` 工具先于 `after` 工具。允许中间调用。 | 完整轨迹中无所需顺序为 0；不完整轨迹为空分。只证明记录顺序，不证明参数、结果或数据流。角色由 `required` 决定。 | `file-tools-trajectory-v1` |
| `checkpoint:missing-primary-recovery` | chain；0/1 | 对冻结的 `chain/recover_missing` 家族，必须依次观察到：primary read 已执行且明确报 `file not found`；fallback read 已执行且成功；对 `recovered.txt` 的 write/edit 已执行且成功。Journal 顺序与完成时间都必须证明依赖顺序。 | 仅 `file-tools-v2/chain/recover_missing/*` 的 Agent chain；正式。完整证据缺失、错误标志冲突、时间无效或私有 selector 缺失时为空分，不能推定恢复成功。 | `file-tools-recovery-policy-v2.1` |

## 4. 重复调用候选诊断

`tool_nonrepetition` 是新加入的严格范围诊断，`formal=False`，版本为 `file-tools-repetition-v1`。它只处理同一轮内的 `read_file`、`write_file`、`edit_file`、`list_dir`，不外推到远程工具、其他工具或跨轮行为。

每次可比较调用必须有规范化参数对象、明确轮次、唯一事件 ID、已执行的完整字符串结果、可排序起止时间、无冲突的布尔错误状态，以及独立的完整 `before_files`/`after_files` 快照。比较锚点是同轮最近一次“同工具名 + 规范化参数 JSON 相同”的调用；对象键顺序忽略，数组顺序和 JSON 类型保留。

| `classification` | 分数 | 含义 |
| --- | --- | --- |
| `first_call` | 1 | 本轮此前没有可比的同工具同参数调用。 |
| `state_changed` | 1 | 两次调用区间内观察到文件状态变化；即使中间写入后恢复，也归此类。 |
| `retry_after_error` | 1 | 上一次同调用有明确工具错误，单列为重试；1 只表示未归为重复候选，不表示重试必要或成功。 |
| `repeated_same_state` | 0 | 调用区间内每个本地工具的完整前后快照都与锚点调用前状态相同，记为可观察的同状态重复候选。合法验证性读取仍可能落入此类。 |
| `missing_evidence` | 空 | 当前或此前同轮证据不完整、冲突，或时间顺序不能证明；未知不能记为“无重复”。 |
| `no_tool_calls` / `unsupported_tool` | 空 | 分别为完整轨迹没有工具调用，或工具超出四个本地文件工具；状态为 `NOT_APPLICABLE`。 |

该诊断不判断调用是否必要，不自动判定 Agent 失败，也不应把 `score=1` 命名为“效率通过”。具体分类规则仍须在协调者集成时与最终实现及测试逐项校对；在新诊断对既有 chain / E2E 保存证据的离线验收见[质量检查报告](../../reports/evaluation-quality-v1/README.md)，不增加原始执行次数。完整轨迹中逐工具统计；全轨迹证据无效时产生一条任务级 MISSING，另计 `unscorable_traces`，不能据此声称已知完整工具调用数。

## 5. LLM Judge 诊断

当前批量 Judge 入口是 `judging.py` 的 `trajectory-geval-v1`。三个维度都由 DeepEval GEval 生成归一化 `0～1` 规则分，`threshold=None`、`success=None`、`formal=False`、`calibration=not_calibrated`。分数表示对 rubric 的符合程度，不是正确概率，也不参与正式 verdict。

| 维度 | 粒度与可见证据 | 适用与缺失 |
| --- | --- | --- |
| `action_appropriateness` | 每个 generation 决策；若轨迹没有 generation，则以每个 tool 请求作为可观察决策。只提供当前及此前请求、决策发生前事件和当时可用输入，评价动作、工具与参数选择。 | 决策输入/输出缺失或 incomplete 为 `MISSING`；不读取未来结果、私有 Oracle 或 checkpoint。 |
| `recovery_appropriateness` | 每个失败的 tool/generation 及其同轮下一可观察决策或回复；评价是否依据错误原因修正、澄清或如实停止。 | 完整轨迹中没有失败为 `NOT_APPLICABLE`；证据不完整时不得据此断言“无需恢复”，记 `MISSING`。错误后重试不自动等于良好恢复。 |
| `response_groundedness` | 每个 turn；比较本轮公开回复、本轮结束 snapshot、截至本轮的工具事件及此前轮次。 | 同轮 snapshot、回复或链接缺失为 `MISSING`，不能用最终状态或未来轮次替代。诚实失败报告可得高分，即使任务正式 verdict 为 FAIL。 |

Judge 调用失败记 `ERROR` 且分数为空；预算未覆盖的适用项记 `MISSING`。兼容函数 `metrics.score_response` 还保留单一最终回复诊断 `file-tools-response-diagnostic-v1`，同样不正式、未校准；它不是当前三维批量 Judge 的版本声明。

Judge 汇总公式如下。设总记录数为 `N`，`NA` 为 `NOT_APPLICABLE` 数，`S` 为合法 `SCORED` 数，分数集合为 `Q`：

- `applicable = N - NA`；`coverage = S / applicable`，适用数为 0 时为空；
- `mean = sum(Q) / S`，没有有效分数时为空；
- 分布区间为 `[0,0.25)`、`[0.25,0.5)`、`[0.5,0.75)`、`[0.75,1]`；
- `missing`、`errors`、`not_applicable` 分别保留，不并入 0 分；
- 分维度统计使用相同公式和各自分母。

### Judge 重复评分稳定性

稳定性只比较相同保存证据、相同 `metric_id` 的重复 Judge 评分。一个指标至少有两次 `SCORED` 才进入匹配集合；缺失重复不能证明稳定。对每个匹配指标的分数 `q_1...q_m`：

- `mean_i = sum(q_j)/m`；
- `range_i = max(q_j)-min(q_j)`；
- `stddev_i = sqrt(sum((q_j-mean_i)^2)/m)`，即总体标准差；
- `mean_range` 是全部匹配指标 `range_i` 的算术平均；
- `fully_scored_metrics` 只计评分次数等于请求重复数的指标。

这些数描述 Judge 对同一证据的重复波动，不是 Agent 稳定性，也不增加 Agent Trial 数。

### 人工一致性诊断

人工标签必须有 `annotation_source=human`、`independent=true` 和非空 `annotator`，分数在 `[0,1]`。阈值 `t` 只作为具名候选：`human_accept = human_score >= t`，`judge_accept = judge_score >= t`。只在人工标签和 Judge 分数都有效的 pair 上计算：

- `agreement = accept 判断相同的 pair 数 / paired`；
- `MAE = sum(abs(human_score-judge_score))/paired`；
- `false_accept_rate = 人工 reject、Judge accept 数 / human_negative`；
- `false_reject_rate = 人工 accept、Judge reject 数 / human_positive`；
- 混淆矩阵以人工 accept/reject 为参照；
- `label_coverage = 已完成人工标签数 / 本维度总记录数`；
- `paired_coverage = 有效人工-Judge 配对数 / 本维度总记录数`。

没有对应分母时比率为空。上述结果状态仍是 `diagnostic_agreement_only`，不能把候选阈值自动升级为正式门槛；操作规则见[Judge 人工标注与校准指南](judge-annotation-guide.md)。

## 6. Trial、重复执行与分组汇总

设计划任务集合大小为 `C`，每个任务计划重复 `k` 次，已保存 Trial 数为 `O`，有效 Trial 数为 `V`，各 verdict 计数为 `n_PASS` 等：

- `planned_trials = C * k`；`completed_trials = O`；`missing_trials = planned_trials - O`；
- `pass_rate_planned = n_PASS / planned_trials`；缺失与无效 Trial 留在分母中；
- `pass_rate_valid = n_PASS / V`；只用于描述有效 Trial，必须同时报告 `V`；
- `all_trials_pass_rate = 所有 k 次计划 Trial 均存在且均 PASS 的任务数 / C`；缺失或无效 Trial 不能证明任务稳定通过；
- `by_split/category/evaluation_level/execution_mode.pass_rate_observed = 组内 PASS 数 / 组内已保存 Trial 数`，它不是 planned 分母。

`all_trials_pass_rate` 是当前 Agent 重复执行的严格稳定性指标。`k=1` 时它只等于单次结果，不能宣称重复稳定性；当前没有从 Trial 分数计算方差、置信区间或统计显著性。`compare_runs` 只在数据集、评分身份、Harness 身份、执行模式、任务选择和重复数完全一致且两边 Trial 齐全时，按 `(case_id, trial)` 配对，报告 `pass_rate_planned` 差值和变化 Trial；该比较明确是描述性的。

实际作品集汇总还区分任务实例、任务族、任务实验与 Trial。程序模块通过率不等于模型成功率，不同 `evaluation_level` 或执行模式不得合并为一个模型能力结论。

## 7. 延迟、Token 与费用

### 延迟

`latency_seconds` 从 Harness 创建工作区之前的 `time.monotonic()` 开始，到 Agent/模块/决策执行、运行身份复核、异常封装和临时工作区清理之后结束；它不包含后续 DeepEval 评分或事后 Judge。事后 Judge Trace 根跨度可能跨过两阶段间隔，不能当作 Agent latency。

设已保存延迟升序为 `x[0]...x[n-1]`：

- 中位数使用 Python `statistics.median`；
- 当前 P95 的**真实实现算法**是 `x[min(n-1, floor(0.95*n))]`；`n=0` 时为空。

这是当前代码的离散索引口径，不应替换成插值百分位、nearest-rank 的另一实现或外部监控系统 P95。比较延迟前必须确认使用同一算法与同一执行范围。

### Agent / 模块用量

每个 Trial 从 `observation.usage` 读取 `input_tokens`、`output_tokens`、`total_tokens`、`cost_usd`；输入与输出分别兼容 `prompt_tokens`、`completion_tokens` 别名。报告层另按相同规则读取 `cached_tokens`。别名只取首个可用值，不重复累加；`total_tokens` 不由输入输出自动推导。

对任一字段：只有全部已保存 Trial 都有数值时，`total=sum(values)`；只要有一条未知，总数为 `None`。同时保留 `known_subtotal` 和 `known_trials`。未知费用不能按 0，也不能用公开价表猜算。

### Judge 用量

`model_requests` 是保存的 Judge generation call 数。`input_tokens`、`output_tokens`、`cost_usd` 按 call 使用同一“全已知才给总数”的规则，并保留 `known_subtotal`、`known_calls`。当前 Judge 适配器不推算价格，Provider 未返回可靠费用时 `cost_usd=None`。Agent 与 Judge 用量必须分开报告；复评保存证据不增加 Agent 用量。

## 8. 版本、身份与可追溯证据

每次运行应保存数据集 Hash、任务契约与 Oracle 版本、Harness 版本及源码 Hash、评分版本、DeepEval 库版本、配置和来源结果 Hash。评分源码身份当前覆盖 `metrics.py`、`oracle.py`、`tasks.py`、`trajectory.py`、`module_oracle.py`、`recovery_scoring.py`、`repetition.py`。v2.2 增加重复候选诊断，正式规则沿用 v2.1；新执行或复评使用新身份，不改写旧结果。

报告只聚合保存的 `results.json`，不重新执行 Agent 或指标。分数必须能通过 `event_id`/`evidence_ids` 回到原事件；Judge 还保存 `metric_id`、rubric Hash、Judge 版本、模型调用事件和来源运行 Hash。可变别名必须在正式使用前解析为固定资产身份。

## 9. 已有结果只能证明什么

`reports/file-tools-v2/summary.json` 是 `layered-portfolio-v1` 的已有汇总，不是本文新规则的验收结果。它记录 444 个任务实验、612 次原始执行，其中 PASS 556、FAIL 56；模块、隔离模型决策、chain、E2E 分开统计。已有 Agent/模块 Token 记录并不完整：612 条中 552 条有输入/输出 Token，费用 0 条已知，因此总体 Token 和费用均为空，只能报告 known subtotal。

已有 Judge 汇总包含 3,859 条记录，适用 3,412、已评分 3,411、错误 1、不适用 447，覆盖率为 `3411/3412`；69 个同证据指标各有两次稳定性评分，平均极差约 0.031884，最大极差 0.4。它明确标记 `formal=false`、人工校准待完成、阈值独立留出验证待完成。

这些保存结果尚未包含 `tool_nonrepetition`；新增诊断必须写入新报告和新来源 Hash。既有 v1 holdout 已用于历史运行，不能称为新的未见集。没有独立人工标签、独立家族/执行证据留出集和可靠费用数据时，不设定或宣称通过验收线。
