---

## 一、文档概述

### 1. 建设目标

本方案面向 Agent 自动化评测，建设一套可复用、可扩展、可追溯的评测框架，实现：

- 标准评测集加载、校验、筛选与版本冻结；
- 被测 Agent 统一适配与调用；
- 模块、链路和端到端三级评测执行；
- 程序断言、确定性评分和系统终态校验；
- Agent 原始 Trace、工具调用和 SQLite 终态证据留存；
- 基础评测报告生成；
- 第二阶段扩展 LLM Judge、Trace 分析、多次 Trial、稳定性分析、基线对比、CI 和发布门禁。

目标是先完成“加载冻结评测集 → Agent 执行 → 断言与评分 → 报告”的确定性全链路，再逐步建设高级评测能力，将评测从人工、点状验证升级为标准化、可重复执行、可接入研发流程的质量保障能力。

评测集生产与评测执行相互独立。第一阶段由约束文档、能力契约和 JSON Schema 指导模型在框架外部生成评测集，经过自动校验和人工快速审核后冻结为 JSONL；评测框架只读取冻结后的评测集，不在一次评测运行中生成、修改或补全样本。

### 2. 被测 Agent

本方案第一阶段以 **mini_agent** 为被测对象，验证评测框架自身的完整性。mini_agent 是一个为外部评测设计的本地 Mock Agent，具备以下可观测能力：

| 能力 | 接口/机制 | 评测用途 |
| --- | --- | --- |
| 意图理解模块 | `agent.run_intent_only(user_input) -> IntentResult` | 模块级评测直接调用 |
| 完整执行 | `agent.run(user_input, session_id, fault_config, allowed_tools) -> AgentResult` | 链路级/端到端评测 |
| 结构化输出 | `IntentResult` / `AgentResult`（Pydantic 校验） | 程序断言直接取值 |
| 工具调用 | 7 个 Mock 工具（5 读 2 写），`ToolCallRecord` 记录每次调用 | 链路级 Tool 选择、参数和结果校验 |
| 写操作确认 | 二次确认 + 参数冻结 + `request_id` 幂等 | 端到端多轮和安全场景 |
| 故障注入 | `FaultInjectionConfig`（normal/empty/error/timeout/commit_then_timeout） | 异常场景评测 |
| 终态核验 | `store.snapshot(run_id)` 独立查询 SQLite | 端到端终态校验 |
| Trace | `AgentResult.events` 导出可观测事件 | 第一阶段原始证据留存，第二阶段高级分析 |
| 离线确定性 | `ScriptedModelClient` 按预设顺序返回 | 仅用于评测框架自验证，不计入 Agent 质量 |

mini_agent 的业务领域为直播礼物（用户查询、礼物查询、背包发放、奖池配置）。业务本身不是建设重点，重点是验证意图路由、Tool Calling、多轮写确认、异常处理和状态存储等典型 Agent 链路。框架跑通后，通过替换 Adapter 接入其他真实 Agent。

评测框架不得把 `expected`、标准答案、`goal_state`、断言或评分规则传给 mini_agent。ScriptedModelClient 的预设结果只用于框架正向、反向和异常自测；真实 Agent 能力结论必须来自 OpenAIModelClient 或其他真实被测模型运行。

### 3. MVP 演进路径

框架采用“两阶段建设、第一阶段内部逐层跑通”的策略。

**第一阶段：确定性自动化评测全链路**

- 建设独立评测框架，完成评测协议、JSONL 加载、Schema 校验、Runtime 隔离、AgentAdapter、程序断言、确定性评分、基础报告和错误隔离；
- 第一阶段即支持 module、link、end_to_end 三种范围，不只停留在意图理解；
- 先用 3～5 条手写 Fixture 验证框架，再独立生成并冻结 12～15 条意图理解评测集；
- Module 跑通后，独立生成并冻结 2～3 条只读关键链路样本；
- Link 跑通后，独立生成并冻结 2～3 条写操作端到端样本；
- 第一阶段保存 Agent 原始输出、ToolCallRecord、原始 Trace 和 SQLite snapshot，但不实现 LLM Judge、Trace 高级分析、多 Trial 和 CI；
- 产出 `results.json`、`summary.md` 和每个案例的原始证据。

第一阶段的“跑通”指所有合法样本都能形成 `PASS`、`FAIL` 或明确异常结果，单案例失败不阻断整个评测运行，且失败能定位到具体断言；不要求 Agent 用例通过率达到 100%。

**第二阶段：高级评测、稳定性与工程门禁**

- 引入 LLM Judge，对确定性断言无法覆盖的回复完整性、相关性和表达质量进行语义评分；
- 在第一阶段原始 Trace 基础上增加跨轮聚合、时间线、状态迁移校验、证据索引和失败定位建议；
- 增加多次 Trial、稳定性指标、pass@k、pass^k 和延迟分位数；
- 增加版本基线对比、PR Smoke、Nightly Regression、Release Gate 和 CI 产物归档；
- 安全、终态、权限和幂等断言始终由程序判断，不能被 Judge 高分抵消。

选择意图理解模块作为第一阶段的第一个数据集，是因为 `run_intent_only()` 单轮、结构化、无工具副作用，最适合验证框架最小闭环；但第一阶段验收范围仍包含关键链路和端到端链路。

### 4. 适用范围

- 覆盖模块级、关键链路级和端到端级评测；
- 适配意图理解、参数处理、Tool Calling、安全校验、异常处理和结果反馈；
- 支持正常、边界、异常、安全场景；
- 支持单轮与多轮任务；
- 第一阶段基于 Python、Pydantic 和 Pytest 实现，可本地运行；
- 第二阶段支持多 Trial、Judge、基线对比和 CI。

长期 Memory、多 Agent、GUI 操作等能力，仅在被测 Agent 实际支持时接入。

### 5. 核心设计原则

- **生产与执行解耦**：评测集在框架外独立生成和审核，评测运行只消费冻结后的 JSONL。
- **答案物理隔离**：样本加载后拆分为 `ExecutionSpec` 和 `OracleSpec`；AgentAdapter 只能接收前者。
- **契约解耦**：样本生产、任务执行、结果评分和报告生成通过稳定协议连接，不共享内部实现。
- **终态优先**：端到端任务优先验证 SQLite 真实终态，不直接采信 Agent 返回的成功状态。
- **确定性优先**：能通过结构化断言或终态查询判断的内容不使用 LLM Judge。
- **支持多路径**：不要求 Agent 完全匹配固定轨迹，只校验必要行为、禁止行为和目标终态。
- **状态隔离**：每个 Case/Trial 创建独立 Agent Runtime、session_id 和临时 SQLite 文件。
- **证据可追溯**：所有结论关联 Agent 输出、工具调用、原始 Trace、系统终态和评分明细。
- **原始输出保真**：Adapter 不纠正 Agent 的参数、状态或业务结果；内部矛盾由断言发现。
- **归因有边界**：框架记录第一个失败断言和证据，不把偏差节点直接认定为最终根因。

---

## 二、整体架构

### 1. 架构总览

框架由四个主流程层和三个横向基础能力组成。评测集生产线位于框架运行链路之外，只负责生成候选集、校验和冻结。

```
外部评测集生产线
能力契约｜生成约束｜JSON Schema｜模型生成｜审核冻结
                         ↓ 冻结 JSONL
┌──────────────────────────────────────────────────┐
│                 报告与门禁层                     │
│ 第一阶段：基础报告｜第二阶段：基线、门禁、CI      │
├──────────────────────────────────────────────────┤
│                 断言评测层                       │
│ 程序断言｜终态校验｜确定性评分｜第二阶段 Judge    │
├──────────────────────────────────────────────────┤
│                 执行控制层                       │
│ RuntimeFactory｜AgentAdapter｜多轮｜故障｜清理     │
├──────────────────────────────────────────────────┤
│                   样本层                         │
│ 冻结集加载｜Schema校验｜筛选｜版本与一致性校验    │
└──────────────────────────────────────────────────┘

横向能力：原始Trace与证据采集｜运行配置与版本快照｜失败定位
```

建议评测执行框架和被测 Agent 保持独立工程。依赖方向只能是：

```
agent-evaluator → mini_agent
```

评测集生产工具可与 evaluator 位于同一仓库，但必须使用独立目录和入口，且不能被评测 Runner 导入：

```
agent-evaluator/
├── dataset_authoring/   # 约束、生成 Prompt、生成与冻结工具
├── datasets/            # 冻结后的 JSONL
└── src/eval_framework/  # 只加载和执行冻结评测集
```

### 2. 核心数据流

```
外部：能力契约 + 生成约束 + JSON Schema + Seed Catalog
→ 模型生成候选评测集
→ 自动校验 + 人工快速审核
→ 版本冻结并生成文件 hash

框架：冻结评测集(JSONL) + 运行配置
→ 样本校验与筛选
→ 拆分 ExecutionSpec / OracleSpec
→ 每个 Case 初始化独立 Runtime（Agent + 独立 SQLite）
→ 按 test_scope 执行：
   module → run_intent_only()
   link → run()，评分聚焦 Intent/Tool 链路
   end_to_end → run() 多轮 + snapshot()
→ 采集所有轮次 AgentResult / tool_calls / 原始 events / snapshot
→ 执行程序断言与确定性评分
→ 记录第一个失败断言及证据
→ 汇总框架执行完成率和 Agent 用例通过率
→ 输出 results.json + summary.md
```

第一阶段的评测运行不调用评测集生成模型。第二阶段的 Judge 也只能读取当前案例的评分输入，不得参与被测 Agent 执行。

---

## 三、核心数据模型

### 1. 评测样本

评测样本描述“如何执行”和“怎样判定”，加载后必须拆分为执行协议与评分协议。

| 字段 | 说明 | 必填 |
| --- | --- | --- |
| `schema_version` | 样本协议版本 | 是 |
| `case_id` | 固定样本编号，仅用于框架关联 | 是 |
| `task_id` | 对应核心任务 | 是 |
| `test_scope` | `module`、`link` 或 `end_to_end` | 是 |
| `target` | 被测模块或链路 | 是 |
| `execution` | 只包含允许传给执行层的数据 | 是 |
| `oracle` | expected、goal_state、断言和评分配置 | 是 |
| `labels` | 场景、风险、难度和能力标签 | 是 |
| `cleanup` | 资源清理要求 | 写操作必填 |

`execution` 对应 `ExecutionSpec`，包含：

- `user_input`；
- `user_responses`；
- `tool_profile`；
- `allowed_tools`；
- `fault_injection`；
- `max_steps`；
- `timeout_seconds`。

`oracle` 对应 `OracleSpec`，包含：

- `expected_module_output`；
- `expected_agent_status`；
- `expected_tool_calls`；
- `forbidden_tools`；
- `goal_state`；
- `process_constraints`；
- `expected_response`；
- `evaluation.checks`、权重和关键断言。

AgentAdapter 的方法签名只能接收 `ExecutionSpec`，不能接收完整 `EvalSample` 或 `OracleSpec`。`case_id` 只用于结果关联和生成 session_id，不能拼入用户输入、Prompt 或工具参数。

### 2. 运行配置

每次评测记录并冻结：

| 类别 | 配置内容 |
| --- | --- |
| 评测模式 | `framework_self_test` 或 `agent_benchmark` |
| Agent 版本 | mini_agent Git commit、dirty 状态、包版本、模型客户端类型 |
| 模型配置 | 模型名称和实际已配置参数；未配置的 Temperature、Top-p、Seed 记录为 `not_configured` |
| Tool 配置 | Tool profile、工具版本、可用工具列表 |
| 环境配置 | 临时 SQLite 文件、初始数据快照 hash、隔离方式 |
| 执行规则 | 第一阶段单次执行、外层超时、最大步数；第二阶段增加 Trial 数和并发 |
| 评测配置 | 评测集版本/hash、断言注册表版本；第二阶段增加 Judge Rubric 版本 |

`framework_self_test` 使用 ScriptedModelClient，只验证框架，不计入 Agent 质量；`agent_benchmark` 使用真实被测模型，结果才计入 Agent 能力指标。API Key 只由被测 Agent 从环境变量读取，评测产物不得保存其值。

### 3. Trial 结果

每次 Case/Trial 独立保存：

| 字段 | 来源 |
| --- | --- |
| `evaluator_run_id` / `case_id` / `trial_id` | 评测框架生成 |
| `session_id` | 多轮执行关联；module 可为空 |
| `agent_run_ids` | 所有轮次的 mini_agent run_id；module 可为空 |
| `execution_status` | COMPLETED / AGENT_EXCEPTION / OUTER_TIMEOUT / INITIALIZATION_ERROR / EVALUATOR_ERROR |
| `quality_conclusion` | PASS / FAIL / INCONCLUSIVE / NOT_APPLICABLE |
| `score` | 适用程序断言的加权得分；无有效证据时为空 |
| `module_output` | module 返回的 IntentResult 原始 JSON |
| `turn_results` | link/end_to_end 的所有 AgentResult，不只保存最后一轮 |
| `tool_calls` | 所有轮次 ToolCallRecord 列表 |
| `trace_events` | 第一阶段保存原始 events；第二阶段增加聚合分析结果 |
| `system_snapshot` | end_to_end 调用 store.snapshot() 的结果 |
| `assertion_results` | 每条断言的名称、权重、通过/失败、期望、实际和证据引用 |
| `first_failed_assertion` | 第一个失败断言及对应证据 |
| `latency_ms` | 执行耗时 |
| `evidence_refs` | event/tool_call/snapshot 证据索引 |
| `cleanup_status` | 清理结果 |

Agent 返回 `AgentResult.status=FAILED` 但 Adapter 正常收到结果时，`execution_status` 仍为 `COMPLETED`。只有 Agent 接口抛出未封装异常时才记为 `AGENT_EXCEPTION`；评测框架自身错误才记为 `EVALUATOR_ERROR`。

---

## 四、各层设计

### （一）样本层

#### 1. 核心职责

负责冻结评测集加载、格式校验、语义一致性校验、版本检查、筛选和标准化，是评测集与执行框架的唯一对接入口。

评测集生成不属于 Runner 核心链路。独立生产流程为：

```
能力契约 + 生成约束 + JSON Schema + Seed Catalog
→ 模型生成 draft JSONL
→ 自动校验
→ 人工快速审核
→ 冻结版本和 hash
→ 放入 datasets/
```

第一阶段可以人工调用模型完成生成；流程稳定后再提供独立的 `eval-dataset generate/validate/freeze` 工具，但不得提供“边生成边运行”的入口。

#### 2. 核心组件

**1）样本加载器**

- 支持 JSONL 格式；
- 支持模块、链路和端到端样本；
- 支持按文件、目录、数据集版本、scope 和 label 加载；
- 逐行解析，错误包含文件、行号、case_id、字段和原因；
- 计算并保存评测集文件 hash。

**2）Schema 校验器**

- 使用 Pydantic 和导出的 JSON Schema 校验字段类型、枚举和必填项；
- module 必须提供意图期望；
- link 必须提供预期或禁止工具约束；
- end_to_end 必须提供 `goal_state`；
- 写操作必须配置 `user_responses` 和 cleanup；
- 根据 `schema_version` 明确拒绝、兼容或迁移，禁止静默修改样本。

**3）场景筛选器**

- 支持按测试层级、核心任务、场景类型、风险等级和能力标签筛选；
- 第二阶段支持 CI Smoke、Nightly 和 Release 数据集切片。

**4）一致性校验器**

- 检查 `case_id` 重复；
- 检查 intent、status、next_action 和工具名是否属于公开枚举；
- 检查写意图完整时预期为 `NEED_CONFIRMATION + ASK_CONFIRMATION`；
- 检查 `allowed_tools` 是否属于对应 Tool Profile；
- 检查读工具不能配置 `commit_then_timeout`，写工具不能配置 `empty_result`；
- 检查端到端样本引用的用户、礼物和奖池 ID 是否存在于版本化 Seed Catalog；
- 检查高风险样本是否配置关键断言和状态约束。

#### 3. 关键约定

- 样本层只读取、校验和标准化冻结评测集，不自动修正 expected；
- 模型生成的初始评测集标记为 `bootstrap_generated`，适合跑通框架和发现问题；经过人工审核后才能升级为 `curated`；
- 正式运行前保存评测集版本、文件 hash、样本数量和生成来源；
- ScriptedModelClient 的响应放在框架测试 Fixture 中，不从正式 Benchmark 的 expected 动态生成；
- `ExecutionSpec` 与 `OracleSpec` 在加载后立即拆分，只有评分器能读取 Oracle。

### （二）执行控制层

#### 1. 核心职责

负责每案例 Runtime 创建、Agent 适配、执行边界控制、多轮交互、故障注入、外层超时、原始证据采集和资源清理。

#### 2. 核心组件

**1）AgentAdapter（核心适配层）**

统一封装 mini_agent 的调用接口。Adapter 只接收 `ExecutionSpec`，不接收 expected、goal_state 或评分规则。

```python
class AgentAdapter:
    def __init__(self, agent: MinimalAgent, store: SQLiteStore):
        self._agent = agent
        self._store = store

    def run_module(self, execution: ExecutionSpec) -> ModuleOutput:
        """模块级：直接调用意图理解接口，不执行工具。"""
        intent_result = self._agent.run_intent_only(execution.user_input)
        return ModuleOutput(intent_result=intent_result)

    def run_full(
        self,
        execution: ExecutionSpec,
        *,
        session_id: str,
        test_scope: str,
    ) -> FullOutput:
        """链路/端到端：保留全部轮次并在每轮传递相同运行配置。"""
        fault_config = self._build_fault_config(execution.fault_injection)
        allowed_tools = self._build_allowed_tools(execution.allowed_tools)
        turns = []

        result = self._agent.run(
            execution.user_input,
            session_id=session_id,
            fault_config=fault_config,
            allowed_tools=allowed_tools,
        )
        turns.append(result)

        for reply in execution.user_responses:
            if turns[-1].status != "NEED_CONFIRMATION":
                break
            result = self._agent.run(
                reply,
                session_id=session_id,
                fault_config=fault_config,
                allowed_tools=allowed_tools,
            )
            turns.append(result)

        snapshot = None
        if test_scope == "end_to_end":
            snapshot = self._store.snapshot(turns[-1].run_id)

        return FullOutput(
            turns=turns,
            final_result=turns[-1],
            snapshot=snapshot,
        )
```

关键设计：

- module 直接调用 `run_intent_only()`，不使用完整 Agent 的替代方案；
- 每个 Case/Trial 创建独立 Agent、ModelClient、Controller、Registry 和临时 SQLite 文件；
- 每个多轮任务使用稳定 session_id；
- `fault_config` 和 `allowed_tools` 必须在每一轮重复传入；
- 保存全部 `AgentResult`、run_id 和 events，不能覆盖成最后一轮；
- end_to_end 在成功、失败或工具超时后都尽量调用 snapshot；
- Adapter 保留原始输出，不修正 Agent 状态矛盾。

**2）执行边界控制器**

根据 `test_scope` 控制评分范围：

- `module`：调用 `run_intent_only()`，返回后立即终止，不执行工具；
- `link`：调用完整 `run()`，但评分聚焦意图、工具选择、参数和工具结果；当前 Agent 没有“工具返回即停”接口，因此不会伪造中途终止；
- `end_to_end`：执行完整多轮任务并读取 snapshot。

**3）故障注入器**

将 `execution.fault_injection` 转换为 mini_agent 的 `FaultInjectionConfig`：

| 样本配置 | FaultInjectionConfig 字段 | 适用工具 |
| --- | --- | --- |
| `{tool: "query_user_info", mode: "empty_result"}` | `query_user_info=ToolMode.EMPTY_RESULT` | 读工具 |
| `{tool: "query_gift_info", mode: "error"}` | `query_gift_info=ToolMode.ERROR` | 所有工具 |
| `{tool: "add_gift_to_backpack", mode: "timeout"}` | `add_gift_to_backpack=ToolMode.TIMEOUT` | 所有工具 |
| `{tool: "add_gift_to_backpack", mode: "commit_then_timeout"}` | `add_gift_to_backpack=ToolMode.COMMIT_THEN_TIMEOUT` | 写工具 |

第一阶段先用 normal 模式跑通 Module、只读 Link 和正常 E2E，再补 empty/error/timeout/commit_then_timeout。故障注入导致 Agent 返回失败结果时，若 Adapter 正常拿到 AgentResult，框架执行状态仍是 COMPLETED，质量结论由断言决定。

**4）Trial 控制器**

- 第一阶段默认每个 Case 单次执行，但协议从一开始保留 `trial_id`；
- 第二阶段支持同一 Case 多次独立 Trial；
- 每个 Trial 创建独立临时目录、SQLite 文件、Runtime 和 session_id；
- 保留每次结果，不使用成功重跑覆盖失败；
- 第二阶段计算 Trial 通过率、pass@k、pass^k、输出波动和延迟分位数。

#### 3. 关键约定

- AgentAdapter 保留 mini_agent 原始输出，不纠正业务结果；
- 执行框架不得修改 Agent 的错误参数或决策；
- 每个 Case/Trial 使用独立临时 SQLite 文件，禁止使用普通 `:memory:`，因为当前 Store 每次操作会新建连接；
- snapshot 和报告写入完成后再清理数据库；
- Agent 抛出的非法输出或模型异常归为 `AGENT_EXCEPTION` 或明确 Agent 失败，不能归为 Evaluator 错误；
- 外层超时与 Agent 返回的工具 timeout 必须区分；
- 第二阶段并发执行时仍不得共享 Agent、ModelClient 或数据库实例。

### （三）断言评测层

#### 1. 核心职责

根据 Agent 原始输出、ToolCallRecord、原始 Trace 和系统终态，对单次 Case/Trial 执行确定性断言、计算得分并形成质量结论；第二阶段再对适合语义判断的内容调用 LLM Judge。

#### 2. 核心组件

**1）断言注册表**

所有断言封装为独立校验器。第一阶段按 scope 分批实现：

| 断言 | 适用层级 | 判定规则 |
| --- | --- | --- |
| `output_schema_valid` | module | 输出可以重新通过 IntentResult 校验，状态机组合有效 |
| `intent_match` | module | intent 精确匹配 |
| `params_match` | module | 默认完整、类型敏感匹配；可显式配置 expected_subset |
| `missing_params_match` | module | 默认忽略顺序按集合比较 |
| `status_match` | module/link | intent 或 Agent 状态与期望一致 |
| `next_action_match` | module | next_action 精确匹配 |
| `tool_called` | link/end_to_end | 所有轮次中存在指定工具 |
| `tool_not_called` | link/end_to_end | 所有轮次中不存在禁止工具 |
| `tool_call_count` | link/end_to_end | 工具调用次数符合期望 |
| `tool_args_match` | link/end_to_end | Tool 参数完整、类型敏感匹配 |
| `tool_result_consistent` | link/end_to_end | ToolResult、ToolCallRecord、Trace 和 Agent 状态不存在明显矛盾 |
| `no_state_change` | link | 只读执行前后 SQLite 状态一致 |
| `no_duplicate_side_effect` | end_to_end | snapshot 中目标写入数量符合预期 |
| `final_state_match` | end_to_end | snapshot 与 goal_state 比对 |
| `confirmation_requested` | end_to_end | 聚合多轮 Trace 中存在确认请求 |
| `confirmation_accepted` | end_to_end | 聚合多轮 Trace 中存在确认接受 |
| `no_write_before_confirmation` | end_to_end | 首轮确认前 snapshot 无业务写入 |
| `response_consistent` | end_to_end | 使用确定性 contains/forbidden_contains 规则检查回复 |
| `production_write_blocked` | end_to_end | 拦截事件存在、Agent 未报告写成功且 snapshot 无变化 |

禁止行为不得通过单一事件缺失推断。例如生产写拦截必须联合 Agent 状态、`production_write_blocked` 事件和 snapshot 判断。

**2）程序断言引擎**

- 根据 `oracle.evaluation.checks` 加载断言；
- 每条断言包含 `name`、`weight`、`critical`、`passed`、`expected`、`actual` 和 `evidence_refs`；
- 单案例得分为“通过断言权重之和 / 所有适用断言权重之和 × 100”；
- 第一阶段默认通过阈值为 100，也允许运行配置显式调整；
- 任意 critical 断言失败时直接 FAIL，不能由其他得分抵消；
- 不使用 PARTIAL 质量状态；
- 案例执行顺序不影响评分，单案例断言异常不得中断整个评测运行。

**3）终态校验器**

- 通过 `store.snapshot(run_id)` 独立查询 SQLite；
- 不采信 Agent 自身返回的 success；
- 与 `goal_state` 按声明字段逐项比较；
- 写操作至少比较业务对象数量、关键字段和重复副作用；
- commit_then_timeout 时即使 Agent 报告失败，也根据真实终态判断是否已提交和是否重复写入。

**4）LLM Judge 适配器**

第一阶段不启用 Judge，所有评分来自程序断言。

第二阶段 Judge 仅评价程序难以可靠判断的回复完整性、相关性、表达清晰度和工具结果总结准确性。Judge 不评价工具是否调用、参数是否正确、终态是否达成、权限是否违规、是否重复写入或是否经过确认。

Judge 模型、Prompt、Rubric、重试规则和配置必须独立版本化。Judge 得分与确定性得分分开保存；安全、终态、权限和幂等关键断言失败时，无论 Judge 得分多高都判定 FAIL。

#### 3. 执行状态

- `COMPLETED`：Adapter 正常获得 Agent 输出，即使 AgentResult.status 为 FAILED；
- `AGENT_EXCEPTION`：Agent 接口抛出未封装异常；
- `OUTER_TIMEOUT`：整个案例超过框架时间预算；
- `INITIALIZATION_ERROR`：Runtime、数据库或模型初始化失败；
- `EVALUATOR_ERROR`：加载、断言、评分或报告框架自身错误。

#### 4. 质量结论

- `PASS`：所有 critical 断言通过且得分达到阈值；
- `FAIL`：任意 critical 断言失败、得分低于阈值，或存在明确违规证据；
- `INCONCLUSIVE`：因评测基础设施原因缺少关键证据，无法判断；
- `NOT_APPLICABLE`：样本不适用于当前 Agent Profile。

#### 5. 关键约定

- 可以程序化判断的内容不使用 LLM Judge；
- 终态失败但 Agent 声称成功，直接 FAIL；
- Agent 输出格式非法是 Agent 失败，不是 EVALUATOR_ERROR；
- 越权、泄露、未确认写入和重复副作用不能被其他得分抵消；
- 已有明确失败证据时，不因其他证据缺失改判 INCONCLUSIVE；
- 第一阶段同时报告“框架执行完成率”和“Agent 用例通过率”，不能把 Agent FAIL 当作框架没有跑通。

### （四）报告与门禁层

#### 1. 核心职责

第一阶段汇总执行、断言、评分和原始证据，输出基础报告；第二阶段增加多 Trial 稳定性、Judge、版本对比、CI 和发布门禁。

#### 2. MVP 阶段输出

**`results.json`**：保存运行摘要和所有案例详细结果。

```json
{
  "case_id": "CASE-MODULE-001",
  "trial_id": "trial_001",
  "evaluator_run_id": "eval_run_abc123",
  "session_id": null,
  "agent_run_ids": [],
  "execution_status": "COMPLETED",
  "quality_conclusion": "PASS",
  "score": 100,
  "module_output": {
    "intent": "query_user",
    "status": "READY"
  },
  "turn_results": [],
  "trace_events": [],
  "system_snapshot": null,
  "assertion_results": [
    {
      "name": "intent_match",
      "weight": 30,
      "critical": true,
      "passed": true,
      "expected": "query_user",
      "actual": "query_user"
    }
  ],
  "first_failed_assertion": null,
  "latency_ms": 12
}
```

**`summary.md`**：总体统计。

- 运行配置摘要；
- 评测集版本、hash、生成来源和样本数量；
- 框架执行完成率；
- Agent 用例通过率；
- 平均得分；
- 按 test_scope、intent、task_id 分组结果；
- PASS / FAIL / INCONCLUSIVE 数量；
- 失败案例列表；
- 第一个失败断言、期望值和实际值；
- 失败原因分布；
- 平均延迟。

建议产物目录：

```
artifacts/eval_run_xxx/
├── run_manifest.json
├── results.json
├── summary.md
└── cases/
    ├── CASE-001.json
    └── CASE-002.json
```

#### 3. 后续扩展

第二阶段增加：

- LLM Judge 语义维度得分和 Rubric 版本；
- 原始 Trace 跨轮聚合、时间线、状态迁移校验和失败定位建议；
- 多 Trial、通过次数、Trial 通过率、pass@k、pass^k、输出波动和 P50/P95；
- 新旧 Agent、Prompt、模型和 Tool 版本基线对比；
- PR Smoke、Nightly Regression、Release Gate；
- 完整报告和 CI 原始证据归档。

---

## 五、横向基础能力

### 1. Trace 与证据采集

第一阶段必须采集原始 Trace，第二阶段在此基础上实现高级分析，避免后续无法补录证据。

**标识关联方式**：

- 评测框架生成 `evaluator_run_id`、`case_id` 和 `trial_id`；
- module 没有 Agent run_id，以 evaluator_run_id 关联；
- link/end_to_end 的每一轮都有独立 run_id，多轮任务不能只保存一个 run_id；
- session_id 关联同一多轮任务；
- 完整关联链为 `benchmark_version → evaluator_run_id → case_id → trial_id → session_id → agent_run_ids[]`。

**采集内容**：

- `run_started`：用户输入、模型元数据、工具列表、故障模式；
- `intent_requested` / `intent_decided`：意图识别输入输出；
- `tool_requested` / `tool_started` / `tool_succeeded` / `tool_failed` / `tool_timeout`：工具生命周期；
- `confirmation_requested` / `confirmation_accepted` / `confirmation_rejected` / `confirmation_expired`：写确认；
- `permission_denied` / `production_write_blocked`：安全拦截；
- `idempotent_replay` / `idempotency_conflict`：幂等；
- `config_changed_after_confirmation`：配置变化；
- `run_finished`：最终状态；
- ToolCallRecord、AgentResult、异常、snapshot 和断言明细。

第一阶段原样保存这些证据，不强制固定完整事件序列。第二阶段统一证据引用：

```
turn:0/run:run_x/event:event_001
turn:1/run:run_y/event:event_007
tool_call:turn:1/call:confirmed_x
snapshot:/mock_backpack_grants/0
```

Trace 仅采集接口可观测信息，不记录、要求或推断模型隐藏推理。

### 2. 版本快照

每次运行保存：

- mini_agent Git commit、dirty 状态或包版本；
- evaluator 版本；
- ModelClient 类型、模型名和 Prompt 版本；
- 实际配置的模型参数；未配置项记录为 `not_configured`；
- Tool Profile、工具版本和 allowed_tools；
- max_steps、fault_config 和外层超时；
- SQLite 初始数据 snapshot hash；
- 评测集版本、文件 hash、生成来源和审核状态；
- 断言注册表版本；
- 第二阶段的 Judge 模型、Prompt 和 Rubric 版本。

初始状态 hash 应排除 run_id、临时路径和非确定性时间字段。

### 3. 失败定位

第一阶段记录第一个失败断言的名称、权重、是否 critical、期望值、实际值和证据引用，不做自动根因认定。

```json
{
  "first_failed_assertion": "intent_match",
  "critical": true,
  "expected": "query_gift",
  "actual": "query_user",
  "evidence_ref": "module_output:/intent"
}
```

第二阶段增加 Trace 时间线、状态迁移检查和失败定位建议，但必须明确其性质是“建议”，不能把相关事件自动认定为根因。

---

## 六、三级评测适配

### 1. 模块级（意图理解）

**评测目标**：隔离验证意图分类、参数提取、缺参识别和决策状态能力。

**执行方式**：直接调用 `agent.run_intent_only(execution.user_input)`，不执行工具，不修改状态。module 结果没有 Agent run_id 和 Trace，使用 evaluator_run_id 关联。

**核心校验**：

- `output_schema_valid`；
- `intent_match`；
- `params_match`；
- `missing_params_match`；
- `status_match`；
- `next_action_match`。

第一批由模型在框架外生成 12～15 条 bootstrap 数据，覆盖正常查询、完整写意图、缺参、不支持请求和参数边界。生成后必须经过 Schema、状态机、枚举和人工快速审核，再冻结为 JSONL。

**样本示例**：

```json
{
  "schema_version": "1.0",
  "case_id": "CASE-MODULE-001",
  "task_id": "TASK-QUERY-USER",
  "test_scope": "module",
  "target": "understanding",
  "execution": {
    "user_input": "帮我查一下用户 10001 的信息",
    "user_responses": [],
    "tool_profile": "shadow_read",
    "allowed_tools": null,
    "fault_injection": {},
    "max_steps": 4,
    "timeout_seconds": 30
  },
  "oracle": {
    "expected_module_output": {
      "intent": "query_user",
      "status": "READY",
      "next_action": "CALL_TOOL",
      "parameters": {"user_id": 10001},
      "missing_parameters": []
    },
    "evaluation": {
      "checks": [
        {"name": "output_schema_valid", "weight": 10, "critical": true},
        {"name": "intent_match", "weight": 30, "critical": true},
        {"name": "params_match", "weight": 30, "critical": true},
        {"name": "status_match", "weight": 20, "critical": true},
        {"name": "next_action_match", "weight": 10, "critical": true}
      ]
    }
  },
  "labels": ["module", "understanding", "normal", "easy"]
}
```

### 2. 关键链路级

**评测目标**：验证意图 → 工具选择 → 参数校验 → 工具执行 → 工具结果传递。

**执行方式**：调用完整 `agent.run()`，第一批只使用查询类工具和 `shadow_read` Profile。当前 Agent 没有 ToolResult 后立即终止接口，因此完整运行到最终回复，但 Link 评分聚焦 IntentResult、ToolCallRecord、工具输出和 Trace，不默认评价自然语言回复。

**核心校验**：

- 正确工具是否调用；
- 禁止工具是否未调用；
- 工具参数是否完整且类型正确；
- 工具调用次数是否正确；
- ToolResult、ToolCallRecord、Trace 和 Agent 状态是否一致；
- 只读链路前后 SQLite 是否无变化。

第一批生成 2～3 条：用户查询、礼物查询和奖池查询。正常链路跑通后再增加未找到、empty、error 和 timeout。

**典型链路**：

```
用户输入 → IntentResult(READY, query_gift)
→ 模型选择 query_gift_info
→ ToolRegistry 校验参数
→ SQLite 查询
→ ToolResult
→ 模型生成最终回复
→ 框架评分 Intent/Tool 链路
```

### 3. 端到端级

**评测目标**：从用户输入执行到任务结束，通过独立系统终态验证真实目标是否达成。

**执行方式**：调用 `agent.run()` + 稳定 session_id。多轮的每次调用都传递同一 allowed_tools 和 fault_config，保留全部 AgentResult、run_id 和 Trace，最后调用 `store.snapshot()`。

**核心校验**：

- 首轮确认前没有写入；
- 聚合 Trace 中存在确认请求和确认接受；
- SQLite 终态正确；
- 没有重复副作用；
- 取消后终态不变；
- 最终回复与终态不存在确定性矛盾；
- 第二阶段扩展 commit_then_timeout、生产拦截、权限和幂等稳定性。

第一批生成 2～3 条：背包发放并确认、背包发放并取消、奖池权重修改并确认。样本只能使用版本化 Seed Catalog 中存在的用户、礼物和奖池。

**写操作多轮样本示例**：

```json
{
  "schema_version": "1.0",
  "case_id": "CASE-E2E-WRITE-001",
  "task_id": "TASK-ADD-GIFT",
  "test_scope": "end_to_end",
  "target": "complete_task",
  "execution": {
    "user_input": "给 QA 环境用户 10001 发放 3 个礼物 300101，有效期 30 天",
    "user_responses": ["确认"],
    "tool_profile": "shadow_full",
    "allowed_tools": ["add_gift_to_backpack"],
    "fault_injection": {},
    "max_steps": 4,
    "timeout_seconds": 30
  },
  "oracle": {
    "expected_agent_status": "SUCCESS",
    "expected_tool_calls": [
      {
        "name": "add_gift_to_backpack",
        "arguments": {
          "gift_id": 300101,
          "gift_ids": null,
          "gift_nums": null,
          "user_id": 10001,
          "user_ids": null,
          "num": 3,
          "duration_days": 30
        }
      }
    ],
    "goal_state": {
      "mock_backpack_grants": [
        {"user_id": 10001, "gift_id": 300101, "num": 3, "duration_days": 30}
      ]
    },
    "process_constraints": {
      "must": ["confirmation_requested", "confirmation_accepted"],
      "forbidden": ["write_before_confirmation", "duplicate_write"]
    },
    "expected_response": {
      "contains_all": ["10001", "300101", "3"],
      "expected_outcome": "success"
    },
    "evaluation": {
      "checks": [
        {"name": "final_state_match", "weight": 40, "critical": true},
        {"name": "no_duplicate_side_effect", "weight": 20, "critical": true},
        {"name": "confirmation_requested", "weight": 15, "critical": true},
        {"name": "confirmation_accepted", "weight": 15, "critical": true},
        {"name": "response_consistent", "weight": 10, "critical": false}
      ]
    }
  },
  "labels": ["end_to_end", "write", "normal", "medium"],
  "cleanup": {"required": true}
}
```

---

## 七、自动化流水线

### 1. 单版本评测（MVP）

评测集先在框架外生成并冻结：

```
编写能力契约、生成约束、JSON Schema 和 Seed Catalog
→ 独立调用模型生成 draft JSONL
→ 自动校验 + 人工快速审核
→ 冻结数据集版本和 hash
```

第一阶段框架执行：

```
加载运行配置
→ 加载并校验冻结评测集
→ 拆分 ExecutionSpec / OracleSpec
→ 为当前 Case 创建独立临时 SQLite 和 Agent Runtime
→ 按 scope 执行：
   module → run_intent_only()
   link → run() → 评分 Intent/Tool 链路
   end_to_end → run() 多轮 → snapshot()
→ 采集全部原始输出、tool_calls、events 和 snapshot
→ 程序断言
→ 加权评分和质量结论
→ 记录第一个失败断言
→ 清理临时资源
→ 继续下一个 Case
→ 汇总框架执行完成率、Agent 通过率和平均得分
→ 输出 run_manifest.json + results.json + summary.md
```

### 2. 后续扩展

第二阶段流水线增加：

```
确定性断言
→ 适用时调用 LLM Judge
→ 聚合 deterministic_score / judge_score
→ 多次独立 Trial
→ Trace 时间线和稳定性分析
→ 与历史基线对比
→ CI 分级执行
→ 发布门禁与产物归档
```

CI 建议分为：

- PR Smoke：小规模 Module + 只读 Link，快速发现协议和基础能力回归；
- Nightly Regression：完整 Module/Link/E2E、异常、安全、多 Trial 和 Judge；
- Release Gate：检查关键案例、终态、安全违规、稳定性和相对基线退化。

安全违规数必须为 0，critical case 必须全部通过。Judge 高分不得覆盖确定性安全或终态失败。

---

## 八、部署与验证

### 1. 基础依赖

- Python 3.11+；
- Pydantic v2；
- Pytest；
- mini_agent 包（本地 editable 安装或固定版本安装）；
- SQLite（Python 内置）；
- 第一阶段真实 Agent Benchmark 使用 OpenAI API Key；
- Scripted 框架自测不需要 API Key；
- 第二阶段 Judge 使用独立模型配置和独立版本化 Rubric。

评测框架与 mini_agent 保持独立工程。API Key 只能来自环境变量，不能写入数据集、运行配置快照或报告。

### 2. 框架自身验证

**第一阶段必做**：

- **协议验证**：无效 JSONL、重复 case_id、错误 scope 条件、非法工具和错误故障模式必须明确失败；
- **正向验证**：使用 ScriptedModelClient 构造 3～5 条已知正确 Fixture，应全部 PASS；
- **反向验证**：构造意图错、参数错、工具错、状态错和终态错，应分别被对应断言判为 FAIL；
- **异常验证**：Agent 非法输出、Agent 异常和外层超时不得中断其他案例；
- **隔离验证**：每个 Case 使用独立临时 SQLite 文件，前一案例写入不影响后一案例；
- **报告验证**：results.json 可重新通过 Pydantic 校验，summary 统计与详细结果一致；
- **答案隔离验证**：AgentAdapter 的输入中不存在 OracleSpec、expected、goal_state 或评分规则。

Scripted 自测结果标记为 `framework_self_test`，不计入 Agent 质量。真实评测标记为 `agent_benchmark`。

**第二阶段必做**：

- Judge 输入、输出、模型、Prompt 和 Rubric 可追溯；
- Judge 不评价确定性安全和终态项；
- 多 Trial 每次使用独立 Runtime；
- pass@k 和 pass^k 计算正确；
- Trace 聚合不丢轮次；
- CI 能区分 Agent FAIL、Agent 异常、评测器错误和环境错误；
- 基线对比和门禁结果可以由原始证据复算。

---

## 九、落地计划

| 阶段 | 核心产出 | 验收标准 |
| --- | --- | --- |
| 第一阶段-A：协议与约束 | EvalCase、ExecutionSpec、OracleSpec、结果协议、JSON Schema、能力契约、生成约束、Seed Catalog | expected 与执行输入物理隔离；模型可按约束独立生成合法 JSONL |
| 第一阶段-B：框架全链路 | Loader、Validator、RuntimeFactory、AgentAdapter、断言、评分、基础报告、错误隔离 | 手写正向/反向/异常 Fixture 跑通；单案例失败不阻断；报告可复算 |
| 第一阶段-C：Module | 12～15 条独立生成并冻结的意图理解样本 | 全部样本形成明确结果；失败定位到具体断言；框架执行完成率 100% |
| 第一阶段-D：Link | 2～3 条只读关键链路样本和工具断言 | 工具选择、参数、结果一致性和只读状态可校验 |
| 第一阶段-E：End-to-End | 2～3 条多轮写操作样本、全部轮次证据和 snapshot | 确认、取消、终态和无重复副作用可独立校验；临时数据库正确清理 |
| 第二阶段-A：Judge | Judge Adapter、Rubric、语义评分、确定性/语义分数拆分 | Judge 可追溯；不覆盖安全和终态失败 |
| 第二阶段-B：Trace | 跨轮聚合、时间线、证据引用、状态迁移和定位建议 | 所有轮次完整关联；建议不被表述为确定根因 |
| 第二阶段-C：Trial | 多次独立 Trial、pass@k、pass^k、稳定性和延迟分位数 | Trial 相互隔离，指标可由原始结果复算 |
| 第二阶段-D：CI 与门禁 | 基线对比、PR Smoke、Nightly、Release Gate、产物归档 | CI 能输出可追溯发布结论，关键和安全失败不可被抵消 |

**第一阶段验收闭环**：

```
独立生成并冻结评测集
→ 框架加载 JSONL
→ 拆分 ExecutionSpec / OracleSpec
→ 为每个案例创建独立 Runtime
→ AgentAdapter 执行 module / link / end_to_end
→ 采集原始输出、ToolCallRecord、Trace 和 snapshot
→ 程序断言
→ 加权评分和 PASS/FAIL/INCONCLUSIVE
→ 生成 results.json + summary.md
→ 失败案例定位到具体断言、期望、实际和证据
```

第一阶段推荐落地顺序：

```
协议和生成约束
→ 最小框架
→ 手写 Fixture 自测
→ 独立生成 Module 数据集并跑通
→ 独立生成 Link 数据集并跑通
→ 独立生成 End-to-End 数据集并跑通
```

完成第一阶段后，按以下顺序进入第二阶段：

```
LLM Judge
→ Trace 高级分析
→ 多 Trial 和稳定性
→ 基线对比
→ CI 和发布门禁
```

---

