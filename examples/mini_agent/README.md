# Minimal Agent 示例运行时

一个精简、可执行、可观测的 Agent 运行时。它只负责自身能力：意图识别、规划/工具
循环、显式注册工具以及能力快照；评测用例、评分、Judge、Mock 业务数据和报告均由外部
项目负责。

## 架构边界

代码分为五个域：

- `capability_snapshot_kit`：独立的 Spec 加载、编译、校验、解析、diff 与导出包；
- `minimal_agent.contracts`：Agent、Intent、Tool 的正式协议；
- `minimal_agent.runtime`：意图路由、模型适配、工具注册与执行、Trace；
- `minimal_agent.capability_facts`：把运行时事实转换为 Kit 的结构化 Fact；
- `minimal_agent.capabilities`：面向调用方的稳定、无版本 API 与 CLI 门面。

通用接入入口为 `python -m capability_snapshot_kit`：支持显式 Collector 插件、LLM
请求包和候选导入、来源核验、独立 wheel，以及无需工具的 conversation 评测配置。
接入其他 Agent 参见 [通用能力快照接入](docs/PLUGGABLE_CAPABILITY_SNAPSHOT.md)。

能力快照遵循 `capability_specs/` 中的自然语言约束加 YAML Front Matter。编译器只读取
Front Matter 的结构化字段，自然语言正文用于人工审阅，不会在运行时交给模型解释。
因此相同 Facts 和 Spec 的编译结果可重复、可校验。可选的 LLM 抽取发生在编译之前；
候选及其来源需要核验，未经 Collector 确认的能力声明保持 unknown。

默认配置包含 7 个 Intent、0 个 Tool。默认 Tool 注册表为空，因此意图识别可以直接
运行；进入 Tool 链时，只有调用方显式注册真实或测试自有 Tool 才能成功执行。运行时
不内置 SQLite、Shadow/Mock 工具、故障注入或脚本模型客户端。

## 安装与验证

需要 Python 3.11 或更高版本。从仓库根目录安装，再进入示例包目录运行后续命令：

```bash
python3.11 scripts/setup.py --only evaluator
cd examples/mini_agent
../../.venvs/evaluator/bin/python -m pytest -q
../../.venvs/evaluator/bin/python -m ruff check .
```

OpenAI 适配器只从环境读取配置：

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=your-compatible-model
```

付费网络冒烟测试默认跳过；显式设置 `RUN_OPENAI_SMOKE=1` 才会执行。

## 公共 Python API

顶层只暴露 13 个名称：

```python
from minimal_agent import (
    AgentResult,
    IntentRegistry,
    IntentResult,
    MinimalAgent,
    ToolContract,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    build_capability_bundle,
    build_default_intent_registry,
    export_capability_bundle,
    run_intent_only,
    validate_capability_bundle,
)
```

`run_intent_only(user_input, client)` 只完成意图候选解析和正式契约校验，不执行工具。
`MinimalAgent.run()` 在结果为 `READY + CALL_TOOL` 时进入有步数上限的工具循环，并返回
`AgentResult` 和可观测事件。

### 独立证据通道（第一阶段）

`agent-trace-sdk` 由评测体系维护，为独立 Python 依赖。采集逻辑已提取到该包，
Agent 仅维护业务事件规则和兼容入口。现有 `AgentResult.events`、
`intent_trace_snapshot()` 继续可用；配置本地 Sink 后，过程事件独立持续落盘。

```python
from agent_trace_sdk import EvidenceReader, LocalEvidenceSink, TraceContext

context = TraceContext()
sink = LocalEvidenceSink(
    "./evidence/" + context.trace_id, context,
    event_rules_version="mini-agent-events-v1",
)
agent = MinimalAgent(model_client, tool_registry, evidence_sink=sink)
completed = False
try:
    result = agent.run("用户输入", trace_context=context)
    completed = True  # 正常返回 FAILED 也属于执行到达终态
finally:
    sink.finish(execution_completed=completed)
    events, collection = EvidenceReader().read(
        sink.directory, memory_manifest=sink.manifest()
    )
```

多轮 Trial 共用 Sink，逐轮传入 `TraceContext(context.trace_id, turn_index)`，
最后一次执行后才 finish。序号跨轮递增；事件字段校验、脱敏、截断和写入错误会
进入采集状态，不改变 Agent 决策和工具重试行为。未知或缺少必需字段的事件保留
但不能作为严格检查的有效证据。`trace_id` 为不透明标识，不应编码案例编号。
完整接入、状态优先级与异常评测规则见[证据协议](../../packages/evaluator/docs/TRACE_PHASE1.md)。

`capabilities/` 是现有 Builder Suite 按哈希绑定的旧快照，保持不变。新采集声明
由当前导出器生成到独立目录，新 Suite 应显式绑定新目录及其 hash：

```bash
../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli export --output exports/trace_v1
```

`exports/` 为可重新生成的本地产物，不纳入版本控制；不要覆盖已被 Suite 固定引用
的快照目录。

## 注册工具并执行全链路

工具实现由接入方提供。下面示例展示注册、执行以及与快照共用同一配置：

```python
from pydantic import ConfigDict

from minimal_agent import (
    MinimalAgent,
    ToolContract,
    ToolDefinition,
    ToolRegistry,
    ToolResult,
    build_default_intent_registry,
    export_capability_bundle,
)
from minimal_agent.contracts.agent import ProtocolModel


class QueryArguments(ProtocolModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    resource_type: str
    environment: str


def query_information(resource_type: str, environment: str) -> ToolResult:
    return ToolResult(
        success=True,
        code="OK",
        message="completed",
        data={"resource_type": resource_type, "environment": environment},
    )


contract = ToolContract(
    name="query_information",
    version="query-information-v1",
    description="Query information from the configured integration.",
    arguments_model=QueryArguments,
    tool_type="read",
    parameter_rules={},
    permission_requirements=("REGISTERED_TOOL",),
    requires_confirmation=False,
    risk_level="low",
    idempotency_rules={"mode": "NOT_APPLICABLE"},
    side_effects=(),
    result_contracts={"OK": {"terminal_status": "success", "data_schema": {}}},
    empty_result_behavior="HANDLER_DEFINED",
    partial_success_behavior="HANDLER_DEFINED",
    trace_event_types=(),
)
registry = ToolRegistry()
registry.register(ToolDefinition(contract=contract, handler=query_information))

# client 必须实现 ModelClient；它负责产出意图结果和工具循环步骤。
agent = MinimalAgent(client, registry)
result = agent.run("query fixture information in test")

# 能力快照必须使用与执行时相同的注册表配置。
export_capability_bundle(
    "configured-capabilities",
    build_default_intent_registry(),
    registry,
)
```

Tool 名称还需与 Intent 契约声明的 `tool_name` 匹配，才能在对应 Intent 快照中形成引用。
未知工具、未授权工具、非法参数、模型错误、超时和最大步数耗尽都会显式失败。

## CLI

运行 CLI 使用 OpenAI 适配器。默认 `run` 命令的注册表为空：

```bash
python -m minimal_agent.cli intent "帮我查询测试信息"
python -m minimal_agent.cli run "帮我查询测试信息" --max-steps 4
```

程序化调用 `minimal_agent.cli.main(..., tool_registry_factory=...)` 可注入配置好的注册表。
生产 CLI 已移除 `--script`、`--database` 和 `--profile`。

## 给 Builder 的文件

包含全部 6 个业务工具的可执行评测配置现已提供，详见
[完整工具能力快照](docs/FULL_TOOL_CAPABILITY_BUNDLE.md)。在 `examples/mini_agent` 目录运行：

```bash
../../.venvs/evaluator/bin/python -m examples.full_tool_fixture.export \
  --output exports/full_tools_fixture_v1
```

Builder 应读取生成的 `exports/full_tools_fixture_v1/bundle/`。六个工具均明确标记为
`test_fixture`，不代表生产后端已接入。外层目录包含能力清单、缺口报告和校验报告。
旧的零工具冻结目录保留用于历史 Suite；运行与导出可通过
`--tool-registry-factory module:callable` 显式选择同一配置。

Builder 应将完整的 `capabilities/` 目录作为唯一交付协议，从
`capabilities/agent.json` 开始递归读取：

```text
capabilities/agent.json
capabilities/modules/*.json
capabilities/intents/*.json
capabilities/tools/*.json
capabilities/scopes/*.json
capabilities/chains/critical/*.json
capabilities/chains/end_to_end/*.json
capabilities/evidence/*.json
capabilities/boundaries/*.json
capabilities/schemas/*.schema.json
```

默认 Bundle 为零工具配置。Suite 选择 Scope/Chain、Intent 和可选 Tool；Builder 校验
Schema、格式版本、Hash 和 DAG 后递归闭包引用，将 Agent、Scope、Chain、Module、Intent、
可选 Tool、Evidence 和 Boundary 转换为中立 Capability IR，再通过三态解析结果生成
Source Pack。Builder 不得导入 `minimal_agent`、调用其 CLI 或补写快照未声明的业务规则。

```bash
../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli export --output capabilities
../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli export \
  --spec-root capability_specs --output capabilities
../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli validate --input capabilities
../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli \
  resolve --input capabilities --selection selection.json
```

Bundle 内的 `snapshot_format_version: "3.0"` 是校验数据，不是 Provider、路径或 API 的
版本选择器。完整协议、QueryUser 评测适配器和组合规则见
[docs/CAPABILITY_SNAPSHOT.md](docs/CAPABILITY_SNAPSHOT.md)。

配置了 Tool 的运行时应导出独立 bundle，并将该 bundle 与评测任务一起交给 Builder。
Builder/Evaluator 必须校验 Schema、引用 Hash 和 `capability_bundle_sha256`，配置不一致时
拒绝运行，不能回退到工作区当前快照。

## 明确不做

- 不内置评测生成、expected、评分、Judge、报表或发布门禁；
- 不内置业务 Mock、Shadow 数据、SQLite 状态或故障注入；
- 不把模型 chain-of-thought 写入 Trace；
- 不提供 RAG、长期记忆、多 Agent 编排或 Web 服务。
