# 第一阶段自动化评测框架搭建约束

你需要新建一个独立的 Python 工程，实现 Agent 自动化评测框架的第一阶段。本阶段的目标是完成一条确定性、可重复、可追溯的评测全链路：

```text
加载冻结评测集
→ 校验与拆分执行数据和标准答案
→ 创建独立被测 Agent Runtime
→ 执行 Module、Link 或 End to End 案例
→ 收集结构化输出、工具调用、原始 Trace 和 SQLite 终态
→ 执行程序断言
→ 计算确定性得分和质量结论
→ 输出 results.json 和 summary.md
```

本阶段建设的是评测执行框架，不是被测 Agent，不是评测集生成器，也不是生产级评测平台。请严格遵守本文的工程边界、协议和交付范围，不提前实现第二阶段功能。

## 一 项目和资料地址

### 1 新建评测工程

在以下路径新建独立项目：

```text
/Users/yuanyu/Documents/ChatGPT/agent_evaluator
```

评测框架不得创建在 `mini_agent` 项目内部。依赖方向必须保持为：

```text
agent_evaluator → mini_agent
```

`mini_agent` 不得反向依赖评测框架。

如果目标目录已经存在，先阅读现有文件并保留无关实现，不得直接覆盖或删除。不要擅自初始化 Git 仓库、创建远端仓库或提交代码。

### 2 被测 Agent 项目

被测 Agent 位于：

```text
/Users/yuanyu/Documents/ChatGPT/mini_agent
```

开始实现前必须完整阅读：

```text
/Users/yuanyu/Documents/ChatGPT/mini_agent/PROJECT_SPEC.md
/Users/yuanyu/Documents/ChatGPT/mini_agent/README.md
/Users/yuanyu/Documents/ChatGPT/mini_agent/pyproject.toml
/Users/yuanyu/Documents/ChatGPT/mini_agent/AUTOMATED_EVALUATION_TECHNICAL_PLAN.md
/Users/yuanyu/Documents/ChatGPT/mini_agent/src/minimal_agent/
/Users/yuanyu/Documents/ChatGPT/mini_agent/tests/
```

允许读取 mini_agent 的代码、协议、测试和本地 Mock 数据，以确认公开接口、参数模型、工具 Schema、状态枚举、Trace 事件和 SQLite snapshot 结构。

除非用户另行明确授权，本阶段不得修改 mini_agent 的任何文件。发现被测 Agent 缺陷时，应在最终报告中记录缺陷、复现条件和影响，不得在评测 Adapter 中修正，也不得为了让评测通过而修改被测 Agent。

### 3 评测技术方案

本项目的总体技术方案以以下文件为准：

```text
/Users/yuanyu/Documents/ChatGPT/mini_agent/AUTOMATED_EVALUATION_TECHNICAL_PLAN.md
```

本文是第一阶段的实施约束。总体方案与本文冲突时，本阶段以本文明确限定的范围为准；仍不确定时停止实现并报告具体冲突，不得自行扩展范围。

## 二 建设目标

第一阶段必须实现以下完整能力：

1. 加载和校验冻结后的 JSONL 评测集；
2. 使用 Pydantic v2 定义全部评测输入输出协议；
3. 将评测样本拆分为只供执行使用的 `ExecutionSpec` 和只供评分使用的 `OracleSpec`；
4. 为每个 Case 创建独立 mini_agent、ModelClient、ToolRegistry、Controller、session_id 和 SQLite 临时文件；
5. 支持 module、link、end_to_end 三种评测范围；
6. 保存 Agent 原始输出、所有轮次、ToolCallRecord、原始 Trace、异常和 snapshot；
7. 按注册的程序断言评分；
8. 输出确定性数值得分与 PASS、FAIL、INCONCLUSIVE、NOT_APPLICABLE 结论；
9. 单案例失败不影响后续案例；
10. 输出可重新校验的 `results.json` 和便于阅读的 `summary.md`；
11. 使用 Pytest 完成框架自身的正向、反向、异常和隔离测试；
12. 提供 CLI 和 Python 两种执行入口。

第一阶段的验收重点是框架全链路能够稳定运行，不要求被测 Agent 的案例通过率达到 100%。Agent 返回错误结果并被断言正确判定为 FAIL，属于评测框架成功工作。

## 三 技术栈和依赖约束

必须使用：

- Python 3.11 或更高版本；
- Pydantic v2；
- Pytest；
- Ruff；
- Python 标准库 `argparse` 实现 CLI；
- Python 标准库 `json` 处理 JSON 和 JSONL；
- Python 标准库 `tempfile` 和 `pathlib` 管理临时运行目录；
- Python 标准库 `hashlib` 计算数据集和配置摘要；
- `pyproject.toml` 管理工程和依赖。

可以把 mini_agent 作为本地 editable dependency 安装到评测项目的虚拟环境，但不得复制 mini_agent 的源码到评测项目中。

不得擅自引入：

- LangChain、AgentLite、CrewAI 等 Agent 框架；
- 数据库 ORM；
- Web 框架；
- 前端框架；
- 消息队列；
- 分布式任务框架；
- Pandas，仅为生成简单统计不应引入重型依赖；
- YAML 解析依赖，第一阶段统一使用 JSON 和 JSONL；
- 第三方报告框架；
- LLM Judge SDK 或额外模型依赖。

如确有新增依赖的必要，先说明用途、不可替代性和影响，获得用户确认后再添加。

## 四 工程结构约束

建议创建以下最小结构，可在不改变职责边界的前提下微调文件名，但不得增加无关目录和功能：

```text
agent_evaluator/
├── pyproject.toml
├── README.md
├── .env.example
├── src/
│   └── eval_framework/
│       ├── __init__.py
│       ├── schemas.py
│       ├── dataset_loader.py
│       ├── dataset_validator.py
│       ├── runtime_factory.py
│       ├── mini_agent_adapter.py
│       ├── assertions.py
│       ├── scoring.py
│       ├── runner.py
│       ├── reporting.py
│       └── cli.py
├── schemas/
│   └── eval_case.schema.json
├── datasets/
│   └── fixtures/
└── tests/
```

`datasets/fixtures/` 只保存评测框架自身测试所需的少量手写 Fixture，不得在本阶段生成或伪装成正式 mini_agent Benchmark。

不要在本阶段创建 `dataset_authoring`、Judge、CI、Dashboard、HTML 报告或 Web 服务目录。

## 五 评测集职责边界

正式评测集由独立流程生成：

```text
能力契约和生成约束
→ 模型生成候选 JSONL
→ 自动校验
→ 人工审核
→ 冻结版本和文件 hash
→ 评测框架加载
```

本阶段评测框架只负责：

- 加载冻结 JSONL；
- 进行结构和语义校验；
- 计算数据集 hash；
- 按 scope、task_id 和 labels 筛选；
- 执行和评分。

本阶段不得实现：

- 调用模型生成评测集；
- 根据 Agent 运行结果修改 expected；
- 自动补全无效评测样本；
- 边生成评测集边执行；
- 根据历史结果优化评测集；
- 把 ScriptedModelClient 响应从正式样本 expected 动态生成。

框架测试中的 Scripted 响应必须作为独立测试 Fixture 编写，只用于证明 Runner、断言和报告行为正确，不计入 Agent 能力评分。

## 六 核心数据协议

所有协议使用 Pydantic v2，统一继承一个 `extra="forbid"` 的基础模型。字段缺失、额外字段、错误枚举和非法类型必须明确失败，禁止静默忽略。

### 1 EvalCase

至少包含：

```text
schema_version
case_id
task_id
test_scope
target
execution
oracle
labels
cleanup
```

`test_scope` 只允许：

```text
module
link
end_to_end
```

### 2 ExecutionSpec

这是唯一允许传入 AgentAdapter 的样本协议，至少包含：

```text
user_input: str
user_responses: list[str]
tool_profile: shadow_read | shadow_full | legacy
allowed_tools: list[str] | null
fault_injection: dict[str, str]
max_steps: int
timeout_seconds: float
```

ExecutionSpec 中严禁出现：

- expected；
- expected intent；
- expected tool；
- goal_state；
- 标准答案；
- 断言名称；
- 评分权重；
- Judge Rubric；
- 对 Agent 的答案提示。

### 3 OracleSpec

只供断言和评分层使用，至少能够表达：

```text
expected_module_output
expected_agent_status
expected_tool_calls
forbidden_tools
goal_state
process_constraints
expected_response
evaluation
```

AgentAdapter、RuntimeFactory 和 ModelClientFactory 不得接收 OracleSpec。

### 4 AssertionSpec

至少包含：

```text
name
weight
critical
config
```

约束：

- `weight` 必须大于 0；
- 同一案例断言名不得重复，除非协议显式支持唯一 assertion_id；
- `critical=true` 的断言失败时案例必须 FAIL；
- 不支持的断言名必须在数据集校验阶段明确失败。

### 5 CaseResult

至少包含：

```text
evaluator_run_id
case_id
trial_id
run_mode
session_id
agent_run_ids
execution_status
quality_conclusion
score
module_output
turn_results
tool_calls
trace_events
system_snapshot
assertion_results
first_failed_assertion
latency_ms
evidence_refs
cleanup_status
```

`execution_status` 至少支持：

```text
COMPLETED
AGENT_EXCEPTION
OUTER_TIMEOUT
INITIALIZATION_ERROR
EVALUATOR_ERROR
```

`quality_conclusion` 只支持：

```text
PASS
FAIL
INCONCLUSIVE
NOT_APPLICABLE
```

不使用 `PARTIAL`。

### 6 EvaluationRunResult

至少包含：

- 运行标识；
- 开始和结束时间；
- 数据集路径、版本和 hash；
- mini_agent 版本和模型元数据；
- 断言注册表版本；
- 运行配置；
- 所有 CaseResult；
- 汇总统计；
- 框架执行完成率；
- Agent 用例通过率；
- 平均得分；
- 总耗时。

### 7 JSON Schema

从 Pydantic EvalCase 模型生成并提交：

```text
schemas/eval_case.schema.json
```

Pydantic 模型是协议的单一事实来源，JSON Schema 不得手工维护出另一套不一致定义。测试必须验证导出的 Schema 与当前模型一致。

## 七 数据集加载和校验

### 1 JSONL 加载

DatasetLoader 必须：

- 逐行读取 UTF-8 JSONL；
- 忽略纯空行；
- 为每条错误保留文件名和行号；
- 使用 EvalCase 进行 Pydantic 校验；
- 检查重复 `case_id`；
- 保持文件中的案例顺序；
- 计算原始文件 SHA-256；
- 支持按 scope、task_id 和 labels 筛选；
- 不自动修改原始样本。

错误信息至少包含：

```text
dataset path
line number
case_id（如果可解析）
field path
error message
```

### 2 语义校验

DatasetValidator 至少检查：

- module 必须配置 `expected_module_output`；
- link 必须配置预期工具或禁止工具约束；
- end_to_end 必须配置 `goal_state`；
- 写操作必须提供 `user_responses` 和 cleanup；
- intent、status、next_action 和工具名属于 mini_agent 公共枚举；
- status 与 next_action 组合有效；
- 完整写意图的预期为 NEED_CONFIRMATION 和 ASK_CONFIRMATION；
- allowed_tools 属于对应 Tool Profile；
- 读工具不能使用 commit_then_timeout；
- 写工具不能使用 empty_result；
- max_steps 和 timeout_seconds 大于 0；
- 断言名称已注册；
- assertion weight 大于 0；
- 当前 scope 支持所配置的断言。

不要在第一阶段硬编码 `case_id` 对应的特殊规则。

## 八 Runtime 和 Agent 适配

### 1 每案例独立 Runtime

每个 Case 都必须创建新的：

- 临时目录；
- SQLite 文件；
- SQLiteStore；
- ShadowExecutionController（需要时）；
- ToolRegistry；
- ModelClient；
- MinimalAgent；
- session_id。

禁止跨 Case 共享 Agent、OpenAIModelClient、ScriptedModelClient、Controller 或 SQLite 数据库。

禁止使用普通 SQLite `:memory:`。当前 mini_agent 的 SQLiteStore 每次操作会创建新连接，普通 `:memory:` 不能保证跨连接保留状态。必须使用临时目录中的真实 SQLite 文件。

### 2 Tool Profile

RuntimeFactory 至少支持：

```text
legacy       → ToolRegistry.with_mock_tools
shadow_read  → ToolRegistry.with_shadow_read_tools
shadow_full  → ShadowExecutionController + ToolRegistry.with_shadow_tools
```

构建 shadow_full 时 Controller 和 Registry 必须绑定同一个 SQLiteStore。

### 3 ModelClient

支持通过工厂注入 ModelClient：

- 测试默认使用 ScriptedModelClient；
- 真实 Benchmark 使用 OpenAIModelClient.from_env()；
- 默认 Pytest 不调用真实 API；
- 真实 API 测试必须显式 opt-in；
- 不允许从 CLI 参数传入 API Key；
- 模型名沿用 mini_agent 的 OPENAI_MODEL 环境变量约束；
- 不得硬编码模型名或密钥。

ScriptedModelClient 只能用于 `framework_self_test`。OpenAIModelClient 运行标记为 `agent_benchmark`。

### 4 Module 执行

module 必须直接调用：

```python
agent.run_intent_only(execution.user_input)
```

不得使用“完整 Agent + max_steps=1”等替代方式。module 没有 Agent run_id 和 Agent Trace，使用 evaluator_run_id 关联，`agent_run_ids=[]`、`trace_events=[]`。

### 5 Link 执行

link 调用完整：

```python
agent.run(
    execution.user_input,
    fault_config=fault_config,
    allowed_tools=allowed_tools,
)
```

当前 mini_agent 没有“工具返回后立即停止”的公开接口，因此允许完整运行到最终回复。Link 评分只聚焦 IntentResult、ToolCallRecord、工具参数、工具结果和原始 Trace，不默认评价自然语言回复。

### 6 End to End 执行

end_to_end 必须：

1. 生成稳定、非空的 session_id；
2. 首轮调用 `agent.run()`；
3. 保存首轮 AgentResult；
4. 如果返回 NEED_CONFIRMATION，按 `user_responses` 继续调用；
5. 每一轮都传递相同的 session_id、fault_config 和 allowed_tools；
6. 保存全部轮次，不得只保留最后一个 AgentResult；
7. 聚合全部 run_id、tool_calls 和 events；
8. 在任务结束后调用 `store.snapshot()`；
9. 即使 Agent 返回 FAILED 或工具 TIMEOUT，也尽量读取 snapshot；
10. 序列化结果和证据后再清理临时数据库。

### 7 超时和异常

区分：

- Agent 正常返回工具 TIMEOUT：execution_status 仍为 COMPLETED；
- Agent 接口抛出未封装异常：AGENT_EXCEPTION；
- 整个案例超过评测框架时间预算：OUTER_TIMEOUT；
- Runtime 构建失败：INITIALIZATION_ERROR；
- 断言或报告代码自身错误：EVALUATOR_ERROR。

第一阶段可以使用明确、可测试的外层超时实现，但不得通过无法安全终止的后台线程制造资源泄漏。若硬超时需要进程隔离且实现代价过大，先提供受控接口和明确限制，并在最终风险中说明，不得伪装为已完成的硬超时。

## 九 程序断言

使用断言注册表，不得在 Runner 中编写大量 case-specific `if/else`。

### 1 Module 断言

至少实现：

```text
output_schema_valid
intent_match
status_match
next_action_match
params_match
missing_params_match
```

规则：

- intent、status、next_action 类型敏感且精确匹配；
- params 默认完整精确匹配；
- 可以通过 assertion config 显式使用 `expected_subset`，但不得静默采用子集匹配；
- missing_parameters 默认忽略顺序按集合比较；
- reason 第一阶段不评分。

### 2 Link 断言

至少实现：

```text
tool_called
tool_not_called
tool_call_count
tool_args_match
tool_result_consistent
no_state_change
```

`tool_result_consistent` 必须检查 ToolResult、ToolCallRecord、Trace 终态事件和 AgentResult 是否存在明显矛盾。Adapter 不得替 Agent 修正矛盾。

### 3 End to End 断言

至少实现：

```text
final_state_match
no_duplicate_side_effect
confirmation_requested
confirmation_accepted
no_write_before_confirmation
response_consistent
```

确认类断言必须查询所有轮次的聚合 Trace，不能只检查最后一轮。

`response_consistent` 第一阶段只支持确定性约束，例如：

```text
contains_all
contains_any
forbidden_contains
expected_outcome
```

不得在第一阶段实现语义 Judge。

### 4 Evidence Reference

断言结果必须能引用证据。建议格式：

```text
module_output:/intent
turn:0/run:run_x/event:event_001
turn:1/run:run_y/event:event_007
tool_call:turn:1/call:confirmed_x
snapshot:/mock_backpack_grants/0
```

第一阶段只做原始证据引用，不实现复杂 Trace 时间线和自动根因分析。

## 十 评分和质量结论

### 1 确定性得分

单案例得分：

```text
score = 通过断言权重之和 / 所有适用断言权重之和 × 100
```

要求：

- 使用 Decimal 或明确的舍入策略，结果可重复；
- 无适用断言时不返回伪造的 100 分；
- 默认通过阈值为 100；
- 阈值允许在运行配置中显式设置；
- critical 断言失败时，无论总分多少都必须 FAIL。

### 2 质量结论

```text
PASS
所有 critical 断言通过，并且 score 达到阈值。

FAIL
任意 critical 断言失败，或 score 低于阈值，或存在明确违规证据。

INCONCLUSIVE
因评测基础设施问题缺少关键证据，无法判断。

NOT_APPLICABLE
当前 Agent Profile 不支持该案例。
```

已有明确失败证据时，不得因为其他证据缺失而改判 INCONCLUSIVE。

### 3 汇总指标

至少计算：

- 总案例数；
- COMPLETED、AGENT_EXCEPTION、OUTER_TIMEOUT、INITIALIZATION_ERROR、EVALUATOR_ERROR 数量；
- PASS、FAIL、INCONCLUSIVE、NOT_APPLICABLE 数量；
- 框架执行完成率；
- Agent 用例通过率；
- 平均得分；
- 按 scope、intent、task_id 分组的数量和通过率；
- 平均延迟；
- 失败断言分布。

框架执行完成率和 Agent 用例通过率必须分开报告。Agent FAIL 不等于框架执行失败。

## 十一 报告和产物

每次运行输出到独立目录：

```text
artifacts/eval_run_xxx/
├── run_manifest.json
├── results.json
├── summary.md
└── cases/
    ├── CASE-001.json
    └── CASE-002.json
```

### 1 run_manifest.json

至少记录：

- evaluator 版本；
- mini_agent 代码或包版本；
- run_mode；
- ModelClient 类型和模型元数据；
- Tool Profile 和工具版本；
- 数据集路径、版本、hash 和样本数量；
- 断言注册表版本；
- pass threshold；
- max_steps、timeout 和过滤条件；
- 开始和结束时间；
- Python 版本。

不得记录 API Key。

### 2 results.json

保存 EvaluationRunResult 和完整 CaseResult。必须能够通过 Pydantic 重新反序列化，不能只输出面向人阅读的松散 JSON。

### 3 summary.md

至少包含：

- 运行配置摘要；
- 数据集版本和 hash；
- 框架执行完成率；
- Agent 用例通过率；
- 平均得分；
- 按 scope 分组结果；
- 按 intent 或 task_id 分组结果；
- 失败案例列表；
- 第一个失败断言；
- 期望值和实际值；
- 平均延迟。

不实现 HTML 报告、Dashboard 或外部发布。

## 十二 CLI 和 Python 接口

### 1 CLI

至少提供：

```bash
python -m eval_framework.cli validate --dataset PATH
python -m eval_framework.cli run --dataset PATH --output-dir PATH
```

可以提供筛选参数：

```text
--scope
--task-id
--label
--case-id
--run-mode
```

CLI 必须：

- 成功时退出码为 0；
- 数据集非法、初始化失败或评测器错误时退出非 0；
- Agent 用例 FAIL 不应默认使整个 CLI 被视为框架崩溃；
- 如需门禁式退出码，必须提供显式参数，第一阶段可不实现；
- 不提供 API Key 命令行参数；
- 不输出隐藏推理或秘密配置。

### 2 Python 接口

至少暴露稳定的公开接口：

```python
load_dataset(path, filters=None) -> DatasetBundle
validate_dataset(dataset) -> ValidationReport
run_evaluation(dataset, config, model_client_factory) -> EvaluationRunResult
write_report(result, output_dir) -> ReportPaths
```

具体类名可以合理调整，但必须保持加载、校验、执行、报告四个职责边界清楚。

## 十三 测试要求

默认测试必须完全离线，每个测试使用独立临时目录和 SQLite 文件。

至少覆盖：

### 1 协议和加载

- 合法 JSONL；
- 非法 JSON；
- Pydantic 字段错误；
- 额外字段；
- 重复 case_id；
- 错误 scope 条件；
- 数据集 hash 稳定；
- 过滤结果正确；
- JSON Schema 与模型一致。

### 2 答案隔离

- AgentAdapter 只接收 ExecutionSpec；
- OracleSpec 不进入 Agent 调用；
- expected 不出现在 ModelClient 请求；
- 不根据 case_id 分支；
- 正式 expected 不被转换为 Scripted 响应。

### 3 Module

- 正确意图 PASS；
- 意图错误 FAIL；
- 参数错误 FAIL；
- 缺参列表错误 FAIL；
- ScriptedModelClient 非法输出形成明确 Agent 错误；
- module 不执行工具、不修改 SQLite。

### 4 Link

- 正确工具和参数 PASS；
- 工具名错误 FAIL；
- 参数错误 FAIL；
- 禁止工具被调用 FAIL；
- ToolResult 和 ToolCallRecord 状态矛盾 FAIL；
- 只读链路前后状态不变。

### 5 End to End

- 多轮确认保存全部 AgentResult；
- 每轮使用相同 session_id、fault_config、allowed_tools；
- 确认前无写入；
- 确认后 snapshot 正确；
- 取消后 snapshot 不变；
- 重复副作用可以被发现；
- 临时数据库隔离；
- 清理发生在结果序列化之后。

### 6 评分和报告

- 权重得分计算正确；
- critical 失败强制 FAIL；
- 阈值行为正确；
- 无适用断言不会伪造满分；
- 单案例异常不影响后续；
- results.json 可重新验证；
- summary 与详细结果一致；
- API Key 不出现在产物中。

### 7 真实 API Smoke

真实 OpenAI 测试必须使用显式环境开关，例如：

```text
RUN_OPENAI_EVAL_SMOKE=1
```

默认测试不得产生网络请求或 API 费用。

## 十四 第一阶段禁止实现

本阶段不得实现：

- 评测集生成器；
- 在一次运行中自动生成或修改数据集；
- LLM Judge；
- Judge Prompt、Rubric 或语义评分；
- 高级 Trace 时间线、状态机分析或自动根因判断；
- 多次 Trial 和 pass@k、pass^k；
- 基线对比；
- CI 工作流；
- 发布门禁；
- HTML 报告；
- Web 服务；
- 前端；
- 数据库服务；
- 多 Agent；
- RAG 或 Memory；
- 自动修复被测 Agent；
- 根据 case_id、固定输入或 expected 编写特殊通过逻辑。

第一阶段可以保存原始 Trace，但只能做透传、聚合和证据引用，不提前实现第二阶段的高级 Trace 分析。

## 十五 工作方式

1. 修改前先完整阅读技术方案、mini_agent 规范、README、源码和相关测试；
2. 先输出对公开接口和约束的简短理解，再开始创建新工程；
3. 只实现本文定义的第一阶段；
4. 不修改 mini_agent；
5. 不提前生成正式评测集；
6. 不擅自增加依赖、目录或功能；
7. 每完成一个子模块即运行对应测试；
8. 测试失败时先定位并修复，不只描述失败；
9. 保留用户已有文件和无关改动；
10. 所有默认测试离线；
11. 任何外部写入、发布、提交或 CI 配置都必须另行获得授权；
12. 不得为了得到更高通过率修改标准答案、过滤失败案例或重跑覆盖失败结果。

建议内部实现顺序：

```text
项目骨架和配置
→ Pydantic 协议
→ JSON Schema 导出
→ DatasetLoader
→ DatasetValidator
→ RuntimeFactory
→ MiniAgentAdapter
→ 断言注册表
→ 评分器
→ Runner
→ JSON 报告
→ Markdown 摘要
→ CLI
→ 全量离线测试
```

## 十六 最终验收标准

以下条件全部满足，第一阶段才算完成：

- 新项目位于 `/Users/yuanyu/Documents/ChatGPT/agent_evaluator`；
- mini_agent 未被修改；
- JSONL 可以加载、校验、筛选和计算 hash；
- ExecutionSpec 与 OracleSpec 在类型和调用边界上隔离；
- module、link、end_to_end 都有可运行的离线 Fixture；
- 每个 Case 使用独立 Agent Runtime 和 SQLite 临时文件；
- 多轮结果不丢失，所有 run_id 和原始 Trace 可关联；
- 程序断言按注册表执行；
- 分数、critical 规则和质量结论可复算；
- 单案例 Agent 失败不阻断后续案例；
- 能输出合法 `run_manifest.json`、`results.json` 和 `summary.md`；
- 框架执行完成率与 Agent 用例通过率分开统计；
- 默认 Pytest 完全离线；
- Ruff 通过；
- README 包含安装、validate、run、Python API 和测试命令；
- 未实现任何第二阶段禁止功能。

验收不要求所有 Agent Fixture 都 PASS。反向 Fixture 必须被框架稳定判定为 FAIL，这本身是框架正确性的证据。

## 十七 阶段结束报告

完成后必须报告：

1. 新建和修改的文件；
2. 项目目录；
3. 核心协议与边界；
4. ExecutionSpec 和 OracleSpec 如何隔离；
5. Runtime 如何保证案例隔离；
6. 已实现的断言；
7. 评分和质量结论规则；
8. CLI 和 Python 接口；
9. 执行过的命令；
10. Pytest 和 Ruff 结果；
11. 未完成项；
12. 已知风险；
13. 发现的 mini_agent 问题，但不得顺手修改；
14. 第二阶段需要继续建设的 Judge、Trace、Trial、基线和 CI 接口预留情况。

不要只描述代码结构。必须给出可以复核的命令和实际测试结果。
