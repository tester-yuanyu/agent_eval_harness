# Capability Snapshot Protocol v2 设计

## 1. 目标

`mini_agent` 自己导出当前真实能力，`agent_dataset_builder` 只消费机器可读快照，
不扫描源码、不解析 Prompt、不根据 Agent 实际回答反推能力。

v2 提供四类快照：

```text
Agent → Module → Intent → Tool
                 └──────→ Tool
```

Agent 是根索引；Module 是可独立评测的执行边界；Intent 是意图理解模块中的具体
能力；Tool 是模型可调用函数及其执行契约。正式评测只绑定当前能力，不在当前
快照中声明目标能力。

## 2. 非目标

- 不实现评测集生成、Judge、评分或报告；
- 不向 Agent 传递 expected、case ID 或评分规则；
- 不增加 RAG、Memory、多 Agent 或 Web 服务；
- 不根据评测失败自动修改能力声明；
- 不把未来目标能力混入当前能力 Bundle。

## 3. 目录与唯一 ID

正式目录固定为：

```text
capabilities/
├── agent.json
├── modules/
│   ├── agent_orchestrator.json
│   ├── model_gateway.json
│   ├── intent_router.json
│   ├── tool_loop.json
│   ├── tool_registry.json
│   ├── execution_guard.json
│   ├── state_store.json
│   └── observability.json
├── intents/
│   ├── query_information.json
│   ├── prepare_resource.json
│   ├── query_user.json
│   ├── query_gift.json
│   ├── add_backpack_gift.json
│   ├── query_pool.json
│   └── unsupported.json
├── tools/
│   ├── query_information.json
│   ├── prepare_resource.json
│   ├── query_user_info.json
│   ├── query_gift_info.json
│   ├── query_pool_config.json
│   └── add_gift_to_backpack.json
└── schemas/
    ├── snapshot-reference.schema.json
    ├── agent.schema.json
    ├── module.schema.json
    ├── intent.schema.json
    └── tool.schema.json
```

ID 全局唯一并包含类型前缀：

```text
agent.mini_agent
module.intent_router
intent.query_user
tool.query_user_info
```

引用路径使用相对 `capabilities/` 根目录的 POSIX 路径，禁止绝对路径、`..`、空路径
和反斜杠。每个路径只能对应一个 snapshot ID。

## 4. 统一信封

四类快照必须包含：

```json
{
  "snapshot_id": "...",
  "snapshot_type": "agent | module | intent | tool",
  "snapshot_format_version": "2.0",
  "contract_version": "...",
  "source_hashes": {},
  "snapshot_sha256": "..."
}
```

所有 Pydantic v2 模型使用 `extra="forbid"` 和严格校验。`contract_version` 统一替代
v1 的 `module_contract_version`、`tool_contract_version` 等主版本字段；Prompt 版本
仍作为模块内部组成字段保留。

引用统一为：

```json
{
  "snapshot_id": "module.intent_router",
  "snapshot_type": "module",
  "snapshot_format_version": "2.0",
  "contract_version": "intent-router-module-v2",
  "snapshot_sha256": "...",
  "path": "modules/intent_router.json"
}
```

## 5. Canonical JSON 与 Hash

所有 Hash 使用：

```python
json.dumps(
    payload,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8")
```

`snapshot_sha256` 计算时只排除自身字段。时间戳、机器路径、运行 ID 等非能力字段
不得进入快照。`source_hashes` 只记录正式结构化契约组成部分的 Hash。

## 6. 五层能力模型

五层固定为：

```text
understanding
context
planning_execution
safety_recovery
result
```

`input` 不是能力层，而是每份快照的 `input_schema`。Module 和 Agent 必须完整列出
五层，不得省略。

每层使用：

```json
{
  "support_status": "supported | unsupported | unknown",
  "inputs": [],
  "outputs": [],
  "entrypoints": [],
  "stop_nodes": [],
  "upstream_dependencies": [],
  "downstream_dependencies": [],
  "evidence": [],
  "state_reads": [],
  "state_writes": [],
  "failure_modes": [],
  "related_tools": [],
  "formal_rules": [],
  "reason": null
}
```

约束：

- `supported`：至少声明输入、输出、入口、停止节点和证据；
- `unsupported`：`reason` 必填，不允许伪造输入输出或证据；
- `unknown`：`reason` 必填，表示当前正式契约不足；
- Builder 只能使用 `supported` 生成正向 Coverage；
- `unsupported` 可用于正式负向案例；
- `unknown` 不能被推断为支持或不支持。

证据只允许公开可观测事实，例如入口协议、返回协议、Trace 事件和 SQLite 快照；
不得记录或伪造模型内部思维过程。

Module 层的 `evidence` 只允许使用 Agent `evidence_catalog` 注册的稳定 ID。
当前 ID 固定为 `intent_router_output`、`conversation_state`、`tool_trace`、
`permission_event`、`system_state` 和 `final_response`。

## 7. Agent 总快照

`agent.json` 至少包含：

- `agent_id=mini_agent` 和 Agent 版本；
- `run`、`run_intent_only`、`store.snapshot` 三个公共入口；
- 8 个 Module 引用；
- Module 拓扑和依赖边；
- 总体当前任务类型；
- 五层能力汇总；
- 会话、状态、模型和工具注册版本；
- Evidence Catalog 和 Execution Boundary Catalog；
- `capability_bundle_sha256`。

Agent 五层汇总必须由被引用 Module 的层状态归并得到，不允许单独手写冲突值。
唯一汇总算法为：任一 Module `supported` 则 Agent `supported` 并只合并支持 Module
的输出与证据，同时写入 `supporting_module_ids`；无 `supported` 但存在
`unknown` 则 Agent `unknown`；全部 `unsupported` 则 Agent `unsupported`。
当前快照不包含 `target_capabilities`。

Execution Boundary ID 固定为 `intent_router_only`、`tool_chain`、`guarded_write`、
`end_to_end` 和 `state_snapshot`。每个 Boundary 声明稳定入口、停止节点、参与
Module 和 Evidence ID；Module 通过 `execution_boundary_ids` 引用。

## 8. Module 快照

固定 8 个逻辑模块：

1. `agent_orchestrator`
2. `model_gateway`
3. `intent_router`
4. `tool_loop`
5. `tool_registry`
6. `execution_guard`
7. `state_store`
8. `observability`

每份包含模块职责、输入输出 Schema、五层三态、多轮 Context 规则、执行边界、
Mock 依赖、Trace/Event、失败模式、Module 依赖、Intent 引用和 Tool 引用。

`module.intent_router` 引用 7 个 Intent；`module.tool_registry` 引用 6 个 Tool；其他
模块只引用其真实使用的 Intent 或 Tool，允许空列表。

## 9. Intent 快照

当前支持 7 个意图：

```text
query_information
prepare_resource
query_user
query_gift
add_backpack_gift
query_pool
unsupported
```

每份包含所属 `module_id`、参数 Schema、缺参词表、状态动作规则、字段格式、组合
规则、语义规则、关联 Tool 引用和结果边界。为避免循环 Hash，只有 Module 持有
Intent 的完整 Hash 引用；Intent 不反向引用 Module Hash。`intent.unsupported` 不引用 Tool。

Module Suite 生成 `query_user` 数据集时读取：

```text
agent.json
+ module.intent_router
+ intent.query_user
```

此时只校验 `tool.query_user_info` 引用存在和 Hash 一致，不使用工具执行结果反推
意图 expected。Link Suite 才加载 Tool Loop、Registry 和 Tool 的执行契约。

## 10. Tool 快照

当前 6 个 Tool 快照必须包含：

- 名称、版本、说明和 Strict Function Schema；
- 精确结果 Schema；
- read/write 类型和参数组合规则；
- 权限、确认、风险、幂等、副作用；
- 故障注入模式；
- 结果码和终态；
- Trace/Event；
- timeout、rate limit、empty result 和 partial success 的正式行为。

手机号、邮箱等业务格式只能来自 Tool Schema 或正式 Intent/Module 协议，Builder
不得补充规则。

## 11. Bundle Hash

`capability_bundle_sha256` 对全部非 Agent 子快照的以下规范数组计算 SHA-256：

```json
[
  {
    "snapshot_id": "...",
    "snapshot_type": "...",
    "snapshot_format_version": "2.0",
    "contract_version": "...",
    "snapshot_sha256": "...",
    "path": "..."
  }
]
```

数组按 `snapshot_id` 升序排列。任一 Module、Intent 或 Tool 的能力变化都会改变自身
Hash、父引用、Agent 快照 Hash 和 Bundle Hash。
时间戳不进入能力快照主体；如需 `generated_at` 只能位于独立 Export Manifest。

## 12. 一致性校验

正式校验必须覆盖：

- 四类快照分别通过正式 JSON Schema；
- 单文件 `snapshot_sha256` 可复算；
- Agent 引用的 Module 全部存在且 Hash 一致；
- Module 引用的 Intent、Tool 和其他 Module 全部存在；
- Intent 引用的 Tool 全部存在；
- 引用中的 ID、类型、版本、Hash 和路径与目标完全一致；
- ID、路径全局唯一，无悬空引用和路径逃逸；
- Module 声明的 Intent/Tool 是 Agent 当前能力的子集；
- Agent 五层汇总能由 Module 推出；
- Module 的 Evidence 和 Boundary ID 全部已注册，且 Catalog 中的 Module/Evidence 无越界；
- `capability_bundle_sha256` 可复算；
- 修改任一子快照后父引用与 Bundle 校验失败。

## 13. 导出与校验接口

Python 接口：

```python
export_capability_bundle("capabilities")
validate_capability_bundle("capabilities")
```

CLI：

```bash
python -m minimal_agent.capability_snapshot export --output capabilities
python -m minimal_agent.capability_snapshot validate --input capabilities
```

`export` 先在内存构造并校验全部子快照，再按依赖顺序写入，最后写 `agent.json`。
`validate` 只读，不修改文件，任何未知字段、Hash 不一致、悬空引用或 Bundle 不一致
都必须以非零状态明确失败。

## 14. v1 迁移

v2 验证通过后，v1 根目录快照和旧信封不再作为正式事实来源。正式 Builder 只能从
`capabilities/agent.json` 开始解析。旧文件不得与 v2 文件并列成为两个有效来源；
迁移实施时应删除可由导出器重新生成的旧文件，并由版本控制保留历史。

## 15. 测试策略

按 TDD 实施：

1. 四类信封和 JSON Schema 严格校验；
2. 五层三态规则测试；
3. 7 Intent、6 Tool、8 Module 清单测试；
4. 单文件 Hash 测试；
5. 引用和相对路径测试；
6. Bundle Hash 传播测试；
7. 导出后重新加载一致性测试；
8. 篡改子快照后校验失败测试；
9. 全量现有 Agent 测试与 Ruff 检查。
