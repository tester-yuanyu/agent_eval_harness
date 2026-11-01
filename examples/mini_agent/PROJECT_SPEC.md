# Minimal Agent 项目规范

## 1. 目标

本示例包实现一个小型但真实可执行的 Agent。它拥有自己的意图契约、模型适配、规划/
工具循环、工具注册、Trace 和能力快照，并通过稳定协议与外部 Builder/Evaluator 对接。

本示例包不承担评测框架职责。用例生成、expected、评分规则、Judge、重试策略和报告不得进入
Agent Prompt、工具参数、Trace 或生产分支。

## 2. 三域架构

### Contracts：正式协议

`minimal_agent.contracts` 定义 `IntentResult`、`AgentResult`、`IntentRegistry`、
`ToolContract` 和 `ToolResult`。模型输出只是候选结果；IntentRegistry 负责参数归一化、
Schema 校验、语义约束和最终状态判定。

### Runtime：运行时

`minimal_agent.runtime` 包含 `MinimalAgent`、IntentRouter、模型适配器、ToolRegistry 和
Trace。运行时只执行显式注册的 Tool，不自带业务工具或状态数据库。

### Capabilities：能力快照

`minimal_agent.capabilities` 从一个具体的 IntentRegistry 和 ToolRegistry 构建快照。
快照描述实际配置，而不是潜在能力或测试替身。

## 3. 执行边界

- `run_intent_only`：分类、抽取、归一化和契约判定，到 IntentResult 停止；
- `MinimalAgent.run`：仅在 `READY + CALL_TOOL` 后进入 Tool 循环；
- ToolRegistry：Schema 暴露、运行级 allow-list、参数校验和 handler 调用；
- Trace：只记录公开输入、输出、事件和错误，不记录隐藏推理。

完整工具链成立需要同时满足：

1. 调用方注册 ToolDefinition；
2. ToolContract 的名称与模型调用名称一致；
3. 对应 Intent 声明的 `tool_name` 与注册名称一致；
4. handler 返回正式 ToolResult；
5. 运行级 allow-list 未拒绝该 Tool。

默认 ToolRegistry 为空。默认配置能运行全部 Intent 判定，但 Intent 为 READY 后若模型
请求未注册 Tool，将以明确失败结束。

## 4. 正式协议

IntentResult 状态/动作组合固定为：

- `READY / CALL_TOOL`；
- `NEED_CLARIFICATION / ASK_USER`；
- `NEED_CONFIRMATION / ASK_CONFIRMATION`；
- `REJECTED / REJECT`。

AgentResult 状态为 `SUCCESS`、`NEED_CLARIFICATION`、`NEED_CONFIRMATION`、
`REJECTED`、`FAILED` 或 `MAX_STEPS_EXCEEDED`。Tool 调用记录必须包含 call ID、名称、
参数、终态、输出或错误以及耗时。

Intent 契约可以声明读、写或不支持的执行模式。写意图到达完整参数后可返回
`NEED_CONFIRMATION`，但通用运行时不提供持久化确认状态；需要多轮确认的接入方必须在
自身执行层实现并显式注册相关能力。

## 5. Tool 契约

每个 ToolDefinition 绑定：

- 不可变 ToolContract 元数据；
- 严格 Pydantic 参数模型；
- 返回 ToolResult 的可执行 handler。

ToolContract 描述版本、读写类型、权限、确认要求、风险、幂等、副作用、结果码和边界
行为。这些字段同时驱动执行期 Schema 和能力快照。测试替身属于消费方测试目录，不得
放进生产包。

## 6. 能力快照

`build_capability_bundle(intent_registry, tool_registry)` 是唯一构建入口。默认 Bundle 注册 7 个 Intent、0 个 Tool；具体 Scope、Chain、Evidence、Boundary 和 Schema 清单以导出制品为准。

固定 Module 为：agent_orchestrator、model_gateway、intent_router、tool_loop、
tool_registry、execution_guard、observability。工具为空时，工具执行相关层在快照中明确
标为 unsupported，而不是虚构支持。

导出物必须绑定具体运行配置。Builder/Evaluator 在生成、校验、冻结和执行前都应验证
引用和 Hash；若运行配置与 bundle 不一致，必须拒绝而不是猜测或降级。

## 7. 配置与安全

- Python 3.11+、Pydantic v2、OpenAI Responses API；
- API Key 和模型名只来自 `OPENAI_API_KEY`、`OPENAI_MODEL`；
- Function Schema 使用 strict 模式并拒绝额外字段；
- 未知 Tool、非法参数、模型失败、Tool 失败和最大步数耗尽必须显式终止；
- Agent 不连接或模拟任何未由接入方显式提供的业务系统。

## 8. 非目标

- 评测数据生产、评分、Judge、报告与发布门禁；
- 内置 Mock/Shadow 业务数据、SQLite store、故障注入；
- 生产脚本模型客户端；
- RAG、长期 Memory、多 Agent、Web 服务和前端。

## 9. 验收

在 `examples/mini_agent` 目录执行适用检查：

```bash
../../.venvs/evaluator/bin/python -m pytest -q
../../.venvs/evaluator/bin/ruff check .
../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli validate --input capabilities
```

默认测试离线运行；付费 OpenAI 冒烟测试保持显式 opt-in。
