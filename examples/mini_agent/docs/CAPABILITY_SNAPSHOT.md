# Capability Snapshot 能力快照协议

通用 Collector、LLM 候选导入、来源核验和独立安装入口见
[通用 Agent 能力快照接入](PLUGGABLE_CAPABILITY_SNAPSHOT.md)。最终交付继续使用本页的 Snapshot 3.0。

Capability Snapshot 是 `mini_agent` 提供给 Builder/Evaluator 的事实协议。Agent 只导出
自身实现、当前运行配置和可观测证据；它不生成评测题、不定义覆盖数量，也不包含评分、
Judge 或业务 fixture。

## Portable Kit 的生成边界

仓库内的实现分为三个可迁移层次：

```text
capability_specs/（自然语言说明 + YAML Front Matter）
+ Agent 的 CapabilityAdapter（结构化运行时 Facts）
→ capability_snapshot_kit Compiler
→ 不可变 Capability Bundle
```

`capability_snapshot_kit` 不导入 `minimal_agent`。Spec 负责通用 Scope、Chain、Evidence、
Boundary 和聚合约束；Adapter 只提供当前 Agent 的模块、Intent、已注册 Tool、Evidence
接口、版本与运行时绑定。Compiler 合并两者并计算引用和 Hash。

自然语言正文只用于审阅、迁移和维护，生成脚本只解析 YAML Front Matter，绝不动态调用
模型解释正文。`capabilities/` 是生成制品，不应手工编辑；修改 Spec、Adapter 或运行
配置后必须重新导出并验证。

迁移到其他 Agent 时复制独立的 `capability_snapshot_kit` 包和 `capability_specs/`，实现
`CapabilityAdapter` 的五组 Fact 方法，再调用
`compile_capability_bundle`/`export_capability_bundle`。Agent 专属模块名、入口、
Schema、工具注册表和 Evidence 接口只能存在于 Adapter Facts，不应写回通用 Kit。

## Builder 输入模型

```text
评测范围快照（Scope 或 Chain）
+ 目标 Intent 快照
+ 可选、已注册的 Tool 快照
+ Suite 覆盖要求
→ Resolved Capability Graph
→ Source Pack
→ Coverage Slot
→ EvalCaseV2
```

Suite 只选择 `scope_or_chain_id`、`intent_id`、可选 `tool_id`，并声明覆盖矩阵与数据集
规模。能力事实、业务参数语义、异常协议和完成条件必须来自快照。未声明的事实按
`unknown` 处理，Builder 不得补写或推断业务规则。

一个选择文件的形状如下：

```json
{
  "scope_or_chain_id": "scope.understanding",
  "intent_id": "intent.query_user",
  "tool_id": null
}
```

## 制品职责

| 制品 | 职责 |
| --- | --- |
| Agent | 协议根、运行时版本、全量子制品引用和配置绑定 Hash |
| Scope | 单层评测边界、输入输出、必需能力、Evidence 和完成条件 |
| Chain | 有序节点、依赖、正常/异常/提前停止分支和完成条件 |
| Module | 代码中真实存在的模块能力事实 |
| Intent | 参数 Schema、参数语义、决策规则和可选 Tool 引用 |
| Tool | 已注册工具的执行、结果、安全、幂等、模拟与观测协议 |
| Evidence | 生产者、时机、Payload Schema、事件和观测接口 |
| Boundary | 入口、停止点、允许/禁止模块、终态和禁止越界规则 |

引用方向是单向 DAG：

```text
Agent
├── Scope  ──→ Module / Evidence / Boundary
├── Chain  ──→ Module / Evidence / Boundary
├── Module ──→ Module / Intent / Tool
├── Intent ──→ Tool（仅同名工具实际注册时）
├── Tool   （无反向引用）
├── Evidence
└── Boundary
```

Builder 可在内存建立反向索引用于 diff 影响分析，但不得把反向关系写回 Tool 或其他
快照。

## 三态解析

解析器按每个 requirement 绑定 Provider：

- `selected_intent` 绑定 Suite 选择的 Intent；
- `selected_tool` 只有在 Tool 与 Intent 的 `required_tool_name` 匹配后才绑定；
- `snapshot` 绑定快照中明确声明的 ID。

状态规则固定为：显式 `unsupported` 优先；否则 Provider、声明、版本或 Evidence 缺失为
`unknown`；只有全部 mandatory requirement 及其 Evidence 均为 `supported` 时，组合才是
`supported`。optional requirement 的缺口保留在 diagnostics 中，但不降低总状态。
Scope 和 Chain 自身不缓存组合后的支持状态。

## Source Pack 与 Hash 绑定

Builder 应先用 Validator 校验根文件，然后从所选 Scope/Chain 和 Intent 开始递归加载
强引用，形成 Source Pack。Tool 仅在选择存在且匹配时加入。Source Pack 必须绑定：

- 根 `capability_bundle_sha256`；
- 每个引用的 `snapshot_sha256`、`contract_version` 和
  `snapshot_format_version`；
- Suite 使用的选择文件。

任一 Hash 或版本不一致都应拒绝生成数据集，不得回退到工作区的另一份 Bundle。

## 单协议边界

- 每次交付使用一个完整 Bundle 目录，内部格式版本固定为 `3.0`；本仓库保留
  `capabilities/` 冻结包，新通用交付位于调用方指定目录下的 `bundle/`；
- Builder/Evaluator 使用无版本 API、CLI、目录和 Provider 名称；
- 不提供旧协议 Loader、迁移器、回退或兼容分支；
- 引用只能指向同一 Bundle 内通过校验的制品；
- 非 `3.0` 根或混入不兼容引用时立即拒绝，不推断、不降级。

默认 Bundle 包含 1 Agent、7 Module、7 Intent、0 Tool、5 Scope、3 Chain、
5 Evidence 和 7 Boundary。导出及验证：

```bash
PYTHONPATH=src ../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli \
  export --output capabilities
PYTHONPATH=src ../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli \
  export --spec-root capability_specs --output capabilities
PYTHONPATH=src ../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli \
  validate --input capabilities
```

解析与差异检查：

```bash
PYTHONPATH=src ../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli \
  resolve --input capabilities --selection selection.json
PYTHONPATH=src ../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli \
  diff --old previous-capabilities --new capabilities
```

## QueryUser 评测适配器

默认 ToolRegistry 始终为空。QueryUser 工具链评测必须由调用方注入 handler、显式注册，
并从同一个 Registry 导出独立 Bundle：

```python
from minimal_agent.capabilities import export_capability_bundle
from minimal_agent.contracts import ToolResult, build_default_intent_registry
from minimal_agent.runtime import ToolRegistry
from minimal_agent.testing import query_user_evaluation_definition


def evaluator_handler(**query: object) -> ToolResult:
    # 具体数据、确定性响应和故障选择归 Evaluator fixture 所有。
    return ToolResult(success=True, code="OK", message="matched", data={"query": query})


registry = ToolRegistry()
registry.register(query_user_evaluation_definition(evaluator_handler))
export_capability_bundle(
    "query-user-capabilities",
    build_default_intent_registry(),
    registry,
)
```

适配器只声明参数、结果类型、权限、风险、幂等和 Evidence 接口，不存储用户数据、固定
响应、数据库地址或故障触发值。Evaluator fixture 继续负责每个 case 的数据隔离。

Builder 将 Agent、Scope、Chain、Module、Intent、可选 Tool、Evidence 和 Boundary 转换为
自身的中立 Capability IR；它只读取完整 Bundle 目录，不导入 `minimal_agent`、不调用
Agent CLI，也不读取 `capability_specs/`。Evaluator 必须用与 Bundle 相同的 IntentRegistry、
ToolRegistry、工具版本和 allow-list 运行 Agent，再从 `IntentResult`、`AgentResult`、
`tool_calls`、`events` 和 `final_response` 收集证据。评测集、fixture、expected、评分、
Judge、报告和模型密钥均留在 Agent 外部。
