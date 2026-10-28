# Agent Evaluator 第二阶段设计

## 背景

当前 Agent Evaluator 已完成第一阶段的确定性评测主链路，并在原始方案基础上
增加了 Provider、Capability Bundle、结构化报告、诊断规则和人工裁决能力。
当前实现仍以单 Trial 为主，`trials_per_case` 固定为 1，并明确不包含 LLM Judge、
高级 Trace 分析、稳定性指标、基线比较和发布门禁。

第二阶段应基于现有协议和扩展边界演进，而不是恢复旧方案中已经失效的
mini_agent 专用 Runtime、SQLite 或 Shadow Tool 假设。

## 目标

本阶段完成以下能力：

1. 使用独立配置的 DeepSeek Judge 评价确定性断言不适合判断的语义质量；
2. 将跨轮原始 Trace 规范化为可检查、可引用的时间线；
3. 对同一 Case 执行多个相互隔离的 Trial，并计算稳定性指标；
4. 对可比的基线和候选运行生成可复算的差异结果；
5. 使用版本化本地 Policy 生成发布门禁结论；
6. 保持原始 Trial 结果不可变，使分析、比较和门禁都可重复执行；
7. 兼容读取当前第一阶段的单 Trial 运行产物。

## 非目标

- 不创建 GitHub Actions 或其他 CI 平台工作流；
- 不实现 Dashboard、Web 服务或 HTML 报告；
- 不让 Judge 判断工具选择、参数、终态、权限、确认、幂等或安全红线；
- 不把 Judge 分数与确定性分数混成一个不可解释的总分；
- 不记录、要求或推断模型隐藏推理；
- 不自动修改评测集、Oracle、基线结果或 Agent；
- 不将 Trace 中的相关事件表述为已经确认的根因；
- 不引入并发 Trial；本阶段优先保证隔离、复现和错误语义正确。

## 方案选择

### 采用：运行编排与纯后处理相结合

Runner 负责需要执行期保证的能力：独立 Trial 和单 Trial Judge 编排。Trace 分析、
Trial 聚合、基线比较和门禁使用纯后处理模块。派生模块读取保存后的结构化结果，
不修改原始 `CaseResult`、断言或 Trace 证据。

该方案使每个 Trial 的隔离可以在执行层得到保证，同时允许已有运行重新分析、
重新比较或应用新的门禁 Policy。

### 不采用：全部放入 Runner

这会继续扩大 Runner 的职责，使历史结果无法在不重新调用 Agent 的前提下应用
新的分析或门禁规则。

### 不采用：完全后处理

多 Trial 的 Runtime 隔离和 Judge 的单 Trial 输入必须由执行编排保证。完全后处理
无法可靠补足这些执行期语义。

## 总体架构

第二阶段的数据流如下：

```text
冻结数据集 + RunConfig
→ 对每个 Case 创建 N 个独立 Trial
→ 每个 Trial 创建独立 Provider Runtime、ModelClient 和 session
→ 执行 Agent 并运行确定性断言
→ 对显式配置 Judge 的 Trial 调用 DeepSeek Judge
→ 保存不可变的 Trial 结果和原始证据
→ 规范化 Trace 并产生派生分析
→ 按 Case 聚合稳定性指标
→ 输出运行报告
→ 可选地与基线结果比较
→ 可选地应用本地 Gate Policy
```

Runner 不执行基线比较或门禁判定。Reporting 不计算指标，只序列化和展示已经
计算完成的协议对象。

## 配置与结果协议

### RunConfig

`RunConfig` 增加：

- `trials_per_case: int`，默认 1，必须大于 0；
- `judge: JudgeRunConfig | None`，默认关闭；
- Judge 配置包括是否启用、超时、最大临时错误重试次数和 `rubric_path`。

单 Trial 且 Judge 关闭时，执行行为与当前版本保持一致。

### Oracle Judge 配置

`OracleSpec` 增加可选的 `judge: JudgeCaseSpec`。只有 Case 显式声明该字段且运行级
Judge 已启用时才调用 Judge。旧数据集没有该字段时不产生费用，也不自动得到语义
分数。

`JudgeCaseSpec` 至少声明：

- 适用的语义维度；
- 每个维度的权重和通过阈值；
- 可提供给 Judge 的参考事实；
- Rubric ID 和版本；
- Judge 是否为该 Case 质量结论的必要条件。

参考事实属于评分输入，只在 Agent 执行结束后进入 Judge，不得进入 Provider、
Runtime、ModelClient 或 Agent 请求。

### CaseResult

`CaseResult` 继续表示一个独立 Trial，并通过 `(case_id, trial_id)` 唯一标识。
初次运行在写出结果前完成一次 Trace 分析快照，并新增字段：

- `judge_result: JudgeResult | None`；
- `trace_analysis: TraceAnalysis | None`。

现有 `score` 保留确定性分数语义，并在新协议中提供含义明确的
`deterministic_score` 兼容访问或迁移字段。Judge 总分和各维度分单独保存。
后续 `analyze` 命令重新分析时写出独立 `RunAnalysis`，不回写该快照或原始
`results.json`。

### JudgeResult

Judge 结果至少包含：

- 状态：`NOT_APPLICABLE`、`COMPLETED`、`MODEL_OUTPUT_ERROR`、
  `MODEL_INVOCATION_ERROR` 或 `MODEL_TIMEOUT`；
- 模型、Prompt、Rubric 和输出 Schema 版本；
- 每个语义维度的分数、理由和证据引用；
- Judge 总分与是否达到 Judge 阈值；
- 调用尝试次数、延迟和 API 返回的 Token 使用量；
- 脱敏后的错误信息。

Judge 理由必须简短并引用可观察输入，不保存隐藏推理。

### 聚合协议

每个 Case 生成 `CaseStabilityResult`，包含：

- 计划、完成、PASS、FAIL、INCONCLUSIVE、NOT_APPLICABLE 和异常 Trial 数；
- Trial 通过率；
- `pass_at_k` 和 `pass_power_k`；
- 质量结论波动和结构化输出波动；
- 延迟 P50/P95；
- 是否在任一 Trial 中触发安全或零容忍失败。

运行级稳定性结果通过聚合 Case 结果产生，不从 Markdown 报告反向解析。

## DeepSeek Judge

### 接口与实现

核心定义可注入的 `JudgeClient` 协议。生产实现为 `DeepSeekJudgeClient`，离线测试
使用 `ScriptedJudgeClient`。Evaluator 直接使用 `openai>=2,<3` 的兼容客户端调用
DeepSeek Responses API，因此将该依赖从传递依赖改为明确的直接依赖。

生产 Judge 只读取以下独立环境变量：

- `DEEPSEEK_JUDGE_API_KEY`；
- `DEEPSEEK_JUDGE_MODEL`；
- `DEEPSEEK_JUDGE_BASE_URL`。

不得回退到被测 Agent 使用的 `DEEPSEEK_API_KEY` 或 `DEEPSEEK_MODEL`。报告只保存
模型名和非秘密配置，不保存 API Key。

### Judge 输入边界

Judge 输入允许包含：

- 用户输入；
- Agent 最终回复；
- 可公开的工具结果摘要；
- Oracle 中的 Judge 参考事实；
- 已运行的确定性断言摘要；
- 对应的版本化 Rubric。

Judge 输入不得包含：

- API Key、Authorization Header 或其他秘密；
- 模型隐藏推理；
- 完整系统 Prompt；
- 与当前 Case 无关的其他 Trial 输出；
- 要求 Judge 重判安全、权限、确认、幂等、工具调用或系统终态的指令。

Judge Prompt 明确声明这些禁止判断项。输出必须通过严格 Pydantic Schema 校验。

### Judge 与质量结论

确定性结论优先：

1. 存在确定性 critical 失败或明确违规证据时，结果保持 `FAIL`；
2. 确定性部分满足要求且 Judge 为必要条件时，Judge 未达标可判 `FAIL`；
3. 必需 Judge 调用失败或输出非法时，若没有已有确定性 FAIL，则判
   `INCONCLUSIVE`；
4. Judge 非必要时，其失败只记录为 Judge 证据缺失，不改变已成立的确定性结论；
5. Judge 高分永远不能覆盖安全、终态、权限、确认或幂等失败。

Judge 只对明确的临时调用错误执行固定次数重试。不因低分、语义结果或输出内容
重试。每次尝试都记录状态和延迟。

## 多 Trial 与稳定性

### 隔离

Runner 按 Case 顺序执行，每个 Case 内按 `trial_001` 至 `trial_NNN` 顺序执行。
每个 Trial 必须重新调用 `provider.create_runtime()`，获得新的 ModelClient、Agent、
session 和 Provider 管理的状态。禁止跨 Trial 共享可变 Runtime。

单个 Trial 的 Agent、Judge、断言或清理失败不能阻断后续 Trial 或后续 Case。
已有 Trial 结果不能被重跑覆盖。

### 指标定义

- Trial 通过率：PASS Trial 数除以计划 Trial 数；
- `pass@k`：一个 Case 的前 k 个计划 Trial 中至少一个为 PASS；
- `pass^k`：一个 Case 的前 k 个计划 Trial 全部为 PASS；
- 运行级 `pass@k`：满足 Case 级 `pass@k` 的适用 Case 比例；
- 运行级 `pass^k`：满足 Case 级 `pass^k` 的适用 Case 比例。

执行异常和 `INCONCLUSIVE` 不算 PASS，并在独立计数中展示。
`NOT_APPLICABLE` Case 不进入质量稳定性分母。任一 Trial 的安全或零容忍失败使该
Case 的稳定安全结论失败。

P50/P95 使用 nearest-rank 算法：升序排列 N 个值后，百分位 p 取索引
`ceil(p * N) - 1` 的值。P95 仅在样本数量达到 Policy 设定的最小值时作为门禁
指标；否则仍可保存观察值，但标记样本不足。

结构化输出波动使用规范化后的 Agent 可观察输出 Hash，不比较自由文本中的非语义
字段、临时时间戳或运行 ID。规范化字段由 scope 和 Provider 扩展规则显式定义。

## Trace 高级分析

### 标准化时间线

原始事件按以下层级规范化：

```text
case_id → trial_id → turn_index → agent_run_id → event
```

每个规范化事件包含事件类型、来源、可选时间戳、轮次、run_id、稳定证据引用和原始
事件索引。原始 Trace 保持不变。

### 通用检查

核心分析器只检查 Provider 无关规则：

- 每个事件能否关联到 Case、Trial、轮次和可用 run_id；
- 时间戳和序列是否明显倒序；
- event ID 是否在 Trial 内重复；
- 断言与 Judge 证据引用是否能解析到真实证据；
- 请求、工具、确认和结束等通用生命周期是否存在明显不闭合。

业务事件名、合法状态转换和输出规范化由 Provider 注册的 Trace 规则提供。没有业务
规则时仍可运行通用检查，不推断业务含义。

### 分析输出

`TraceAnalysis` 包含：

- 规范化时间线；
- 结构性违规；
- 状态迁移违规；
- 证据缺口；
- 首个可观察偏差；
- 建议排查环节。

所有定位信息使用“观察”或“建议”措辞，不声明未经验证的根因。

## 基线比较

### 可比性门槛

正式比较要求：

- 数据集 SHA-256 相同；
- Case 过滤条件和执行类型相同；
- Trial 数相同；
- Capability Bundle SHA-256 相同；
- Provider ID、断言注册表、通过阈值和工具 Profile 相同；
- 启用 Judge 时，Judge 模型、Prompt、Rubric、输出 Schema 和采样参数相同。

Agent、Provider 实现版本、被测模型和 Prompt 版本允许不同，因为这些字段可以是
比较对象。缺少必要复现字段或不满足可比性时返回 `INVALID_COMPARISON`，不计算
改善或退化结论。

### 差异结果

比较先按 `(case_id, trial_id)` 对齐 Trial，再按 `case_id` 汇总。输出：

- 新增失败、已修复和持续失败；
- 新增或消除的执行异常；
- 新增不稳定和稳定性改善；
- 安全或零容忍失败变化；
- Judge 维度变化；
- 延迟和 Token 使用量变化；
- 缺失或多余 Trial。

比较结果保存输入运行目录、两个 `results.json` 的 SHA-256 和比较器版本，使结论可
重新计算和审计。

## 本地发布门禁

### Policy

Gate Policy 是严格校验、独立版本化的 JSON 文件，至少可以声明：

- 最低执行有效率；
- 最低核心 Case 通过率和最低 `pass^k`；
- 最大新增退化 Case 数；
- 最大不稳定 Case 数；
- 安全标签、关键 Case 和指定断言的零容忍规则；
- Judge 维度最低分；
- 延迟 P50/P95 和 Token 使用量的绝对或相对上限；
- 哪些证据缺失需要 `REVIEW_REQUIRED`。

Policy 不从断言名称或标签文本猜测安全语义。零容忍标签和断言名必须显式配置，且
在应用前验证确实存在于候选结果或冻结数据集。

### 结论

门禁结论限定为：

- `PASS`：全部已配置条件满足；
- `FAIL`：存在明确的门禁违反；
- `REVIEW_REQUIRED`：证据不足、样本不足或 Policy 指定人工复核；
- `INVALID_COMPARISON`：门禁依赖基线，但比较不可用。

没有配置的业务阈值不会由框架猜测。Judge 高分、平均分或其他改善不能抵消安全和
关键断言的零容忍失败。

## 文件与职责

新增模块：

- `src/eval_framework/judge.py`：Judge 协议、编排和输出校验；
- `src/eval_framework/judges/deepseek.py`：DeepSeek Judge 客户端；
- `src/eval_framework/trace_analysis.py`：时间线和 Trace 检查；
- `src/eval_framework/stability.py`：Trial 聚合和稳定性；
- `src/eval_framework/result_loader.py`：新旧结果兼容读取；
- `src/eval_framework/comparison.py`：可比性与差异；
- `src/eval_framework/gating.py`：Policy 与门禁判定。

现有模块：

- `schemas.py`：增加或兼容导出第二阶段协议；若继续增长，按职责拆分模型；
- `runner.py`：增加 Trial 循环和单 Trial Judge 编排；
- `provider.py`：增加可选的 Trace 规则和输出规范化扩展点；
- `reporting.py`：展示已经计算好的 Judge、Trace 和稳定性结果；
- `adjudication.py`：支持新的多 Trial Case 路径并兼容旧路径；
- `cli.py`：接入新的本地命令；
- `pyproject.toml`：声明 Judge 直接使用的 OpenAI Python SDK 依赖；
- `README.md` 与 `docs/evaluation_report_spec.md`：更新第二阶段使用与报告协议。

## CLI 与 Python API

CLI 增加：

```text
agent-evaluator run ... --trials N --judge-config PATH
agent-evaluator analyze --run-dir PATH
agent-evaluator compare --baseline PATH --candidate PATH --output-dir PATH
agent-evaluator gate --candidate PATH [--comparison PATH] --policy PATH \
  --output-dir PATH
```

Python API 增加对应的稳定入口：

```python
analyze_run(result, trace_rules=None) -> RunAnalysis
compare_runs(baseline, candidate) -> ComparisonResult
evaluate_gate(candidate, policy, comparison=None) -> GateResult
```

JudgeClient 通过 Python API 注入；CLI 真实运行时根据显式 Judge 配置创建
DeepSeekJudgeClient。

CLI 保留当前 `run` 语义，并为新命令使用稳定退出码：0 表示命令成功或 Gate
`PASS`，2 表示输入、运行或比较无效，3 表示评测器内部错误，4 表示 Gate `FAIL`，
5 表示 `REVIEW_REQUIRED`。Agent 质量 FAIL 不被伪装成框架崩溃；这些退出码可供
未来任意 CI 调用。

## 产物布局

多 Trial Case 和证据使用：

```text
cases/<case_id>/<trial_id>.json
evidence/<case_id>/<trial_id>/actual.json
evidence/<case_id>/<trial_id>/assertions.json
evidence/<case_id>/<trial_id>/trace.jsonl
judge/<case_id>/<trial_id>.json
trace_analysis/<case_id>/<trial_id>.json
stability.json
```

比较和门禁分别输出：

```text
comparison.json
comparison.md
gate.json
gate.md
```

旧的 `cases/<case_id>.json` 保持可读取。人工裁决优先查找新路径，再回退旧路径。
原始 `results.json`、`results.jsonl`、断言和 Trace 证据不由 `analyze`、`compare`
或 `gate` 修改。

## 错误处理

- Agent Trial 异常沿用当前执行状态，并继续后续 Trial；
- Judge 错误使用独立 Judge 状态，不伪装成 Agent 异常；
- 必需 Judge 缺失且没有确定性 FAIL 时，质量结论为 `INCONCLUSIVE`；
- Trace 缺失产生证据缺口，不生成虚构事件；
- 派生分析失败不修改原始自动结果；
- 比较输入不兼容时返回 `INVALID_COMPARISON`；
- Policy 非法、引用不存在的指标或零容忍项时作为门禁输入错误处理；
- 单个 Case/Trial 的清理失败继续保持可见，不能由后续成功覆盖；
- 所有写入继续执行密钥脱敏与原子化策略，防止半写产物被误认为完整结果。

## 向后兼容

- `trials_per_case` 缺失时按 1 读取；
- `judge_result`、`trace_analysis` 和稳定性字段缺失时按第一阶段结果读取；
- 旧 `cases/<case_id>.json` 与新多 Trial 路径同时支持；
- 当前数据集没有 `oracle.judge` 时不调用 Judge；
- 第一阶段单 Trial报告仍可重新渲染；
- 新协议字段只在新产物中写出，旧结果不被原地迁移或覆盖。

## 测试与验收

默认测试完全离线，至少覆盖：

1. Judge 输入不含秘密、隐藏推理或禁止判断项；
2. Scripted Judge 正常、超时、调用失败、非法输出和临时错误重试；
3. Judge 模型、Prompt、Rubric 和 Schema 版本可追溯；
4. Judge 高分不能覆盖确定性 critical 或零容忍失败；
5. 每个 Trial 使用不同 Runtime、ModelClient、session 和状态；
6. Trial 异常不阻断后续 Trial 或 Case；
7. `pass@k`、`pass^k`、波动、P50/P95 在边界输入下可复算；
8. Trace 跨轮聚合不丢事件，能识别重复、倒序、非法转换和失效引用；
9. 未注册 Provider 业务规则时通用 Trace 分析仍可运行；
10. 基线比较识别新增失败、修复、持续失败、波动和不可比条件；
11. 零容忍安全失败不能被 Judge、均值或其他改善抵消；
12. 旧单 Trial结果、报告和人工裁决保持可读取；
13. CLI 退出码区分质量失败、无效运行、无效比较和门禁阻断；
14. `results.json`、派生分析、比较和门禁结果均可通过 Pydantic 重新加载；
15. Pytest 与 Ruff 全量通过；
16. 真实 DeepSeek Judge 只在显式环境开关下运行，默认测试不产生网络费用。

## 实施顺序

第二阶段按以下顺序实施，每一步都保持已有测试通过：

1. 结果协议、兼容 Loader 与多 Trial 文件布局；
2. 多 Trial 执行和稳定性聚合；
3. Judge 协议、Scripted Judge 和 DeepSeek Judge；
4. Trace 规范化、通用检查和 Provider 扩展；
5. 基线比较与可比性验证；
6. 本地 Gate Policy 和门禁命令；
7. 报告、CLI、文档和全量兼容验证。

本阶段不包含 CI 工作流；完成后的 CLI 和机器产物应能被未来 CI 直接调用。
