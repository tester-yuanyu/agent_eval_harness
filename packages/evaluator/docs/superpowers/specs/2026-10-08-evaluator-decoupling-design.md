# Evaluator Provider、执行 Profile 与诊断扩展解耦设计

## 背景

当前 Evaluator 的加载、执行、确定性断言、评分和报告主链路已经由评测集与
Capability Bundle 驱动。QueryGift 可以在不修改 Runner 和断言核心的情况下完成
正式评测，证明核心边界基本成立。

剩余耦合主要集中在三处：

- `runtime_factory.py` 固定声明 `legacy`、`shadow_read`、`shadow_full` 及其工具；
- CLI 使用条件分支只允许 `mini_agent`；
- mini_agent Provider 固定注册 QueryUser 诊断规则，诊断扩展没有按 Intent 路由。

此外，运行结果仍使用 `mini_agent_version` 这一实现相关字段。

## 目标

本次改造完成后：

1. 新增普通 Intent 及其模块评测集时，不修改 Evaluator 核心；
2. 工具 Profile 成为冻结评测协议的一部分，能够随运行复现；
3. Provider 通过统一注册表接入，CLI 不包含具体 Provider 条件分支；
4. 业务诊断按 Intent 注册，Runner 只依赖通用诊断接口；
5. 旧评测集与旧报告保持可读，模块评测可以继续执行；
6. 不引入动态插件扫描、网络发现或隐式工具推断。

## 非目标

- 本阶段不实现第三方动态插件安装或入口点扫描；
- 不为 mini_agent 重新引入已经删除的 Mock/Shadow 工具实现；
- 不改变断言语义、评分规则和报告结论规则；
- 不修改已经冻结的 JSONL 内容和历史 Manifest；
- 不通过 LLM Judge 替代确定性断言。

## 方案选择

### 采用：Manifest 绑定 Execution Profile

Execution Profile 描述一次评测允许使用的工具集合，属于评测执行协议，而不是
Agent 生产能力本身。Builder 在冻结时将 Profile 写入 Manifest，Evaluator 加载后
校验 Profile 中的工具均存在于同一个冻结 Capability Bundle。

该方案同时满足可复现性和职责边界，不会把 `shadow_read` 等评测环境概念写进
mini_agent 的生产 `AgentSnapshot`。

### 不采用：写入 AgentSnapshot

该方案可以做到单一来源，但会使生产 Agent 能力协议携带 Evaluator 专用 Profile，
并让 Agent 发布与评测环境命名相互耦合。

### 不采用：Evaluator 本地配置

本地配置实现简单，但不会随评测集冻结。相同 JSONL 在不同机器上可能使用不同
Profile，无法满足可追溯和可重复执行要求。

## Manifest 协议

新 Manifest 可包含：

```json
{
  "execution_profiles": {
    "read_only": {
      "allowed_tools": ["query_user_info", "query_gift_info"]
    },
    "full": {
      "allowed_tools": [
        "query_user_info",
        "query_gift_info",
        "add_gift_to_backpack"
      ]
    }
  }
}
```

约束如下：

- Profile 名称必须为非空字符串且唯一；
- `allowed_tools` 不得重复；
- 每个工具必须存在于 Manifest 绑定的 Capability Bundle；
- 故障模式继续由 Tool Snapshot 的 `fault_modes` 声明，不在 Profile 中重复；
- Case 的 `execution.tool_profile` 必须引用已声明 Profile；
- Case 的 `allowed_tools` 若存在，必须是 Profile 工具集合的子集；
- Case 的 `fault_injection` 工具必须同时属于有效 Profile，并支持指定故障模式。

Builder 的 Suite 配置增加可选 Execution Profile 配置。冻结时只复制明确声明的
Profile，不根据工具名称、读写类型或目录内容自动猜测。

## 历史兼容

历史 Manifest 没有 `execution_profiles`。兼容规则为：

- 如果筛选后的全部 Case 都是 `module`，Evaluator 为这些 Case 引用的 Profile 名称
  建立空工具集合；这是模块执行兼容，不代表 Agent 支持对应工具；
- 如果存在 `link` 或 `end_to_end` Case，则预检失败，错误代码为
  `EXECUTION_PROFILE_REQUIRED`；
- v1/v2 Capability Bundle 的读取和 Hash 校验逻辑保持不变；
- 新冻结评测集必须显式携带 Execution Profile，不使用兼容路径。

该规则使 QueryUser v1.6、QueryGift v1.0 等现有模块评测集保持可运行，同时禁止
旧 Link/E2E 数据集在工具配置未知时被静默执行。

## Provider 注册表

新增通用 `ProviderRegistry`，保存 `provider_id -> ProviderFactory`：

```python
registry.register("mini_agent", MiniAgentProviderFactory())
provider = registry.create(
    provider_id=dataset.provider_id,
    dataset=dataset,
    model_client_factory=model_client_factory,
    bundle_override=bundle_override,
)
```

约束如下：

- 重复 `provider_id` 注册失败；
- 未知 Provider 返回稳定错误 `UNKNOWN_PROVIDER`；
- 数据集 Provider 与所选注册 ID 不一致时，在构造 Provider 前失败；
- Factory 返回的 Provider ID 必须与注册 ID 一致；
- CLI 只依赖注册表，不导入或判断具体 Provider；
- 第一阶段在组合根显式注册 mini_agent，不进行动态扫描；
- Python 调用方可以构造独立注册表并注册测试或其他 Provider。

`MiniAgentProviderFactory` 位于 mini_agent Provider 包内，负责加载冻结能力、检查
当前能力兼容性、构造 ToolCatalog 和 Native Runtime。Runner 不感知这些细节。

## 诊断注册表

新增 `DiagnosticRegistry`，按 Intent ID 保存零个或多个 `DiagnosticRule`：

```python
diagnostics.register("query_user", QueryUserDiagnosticRule())
diagnostics.register("query_gift", QueryGiftDiagnosticRule())
```

运行时使用 Case 的预期 Intent 选择业务诊断规则；没有预期 Intent 时，从
`intent_match` 断言证据中读取实际 Intent。随后执行通用诊断作为兜底。

约束如下：

- Runner 只调用 `rules_for(case, assertions)`；
- 未注册 Intent 返回空规则，不影响评分；
- 一个 Intent 可以注册多个规则；
- 一个 Case 可以产生多个诊断；
- 业务规则继续位于 Provider 扩展目录，不进入核心 `diagnostics.py`；
- QueryUser 现有规则迁移到注册表后，行为保持不变；
- QueryGift 可以增加专用规则，但本次不改变已经生成的评测结果。

## Runtime 与 ToolCatalog

删除 `MINI_AGENT_TOOL_PROFILES`。ToolCatalog 的 Profile 来源只允许是：

1. 新 Manifest 的 `execution_profiles`；
2. 历史模块评测兼容产生的空 Profile。

RuntimeFactory 不再判断 `legacy/shadow_read/shadow_full`。它接收已经解析完成的
Profile 工具集合，并将其交给 Provider 的 Tool Registry 工厂。当前精简版
mini_agent 没有内置业务 Tool，因此模块评测使用空 Registry；若未来 Link/E2E
需要工具，mini_agent Provider 必须显式注入与冻结 Tool Snapshot 对应的处理器。
缺少处理器时应在预检或初始化阶段失败，不得伪造工具执行结果。

## 通用版本字段

`EvaluationRunResult` 增加 `agent_version` 并停止在新产物中写入
`mini_agent_version`。兼容读取规则为：

- 旧结果只有 `mini_agent_version` 时，将其迁移到 `agent_version`；
- 同时出现两个字段且值不同，拒绝读取；
- 报告继续展示“Agent 版本”，不改变人类可读格式；
- 新 `run_manifest.json` 只写 `agent_version`。

## 数据流

完整数据流为：

1. DatasetLoader 读取 JSONL 与 Manifest；
2. CapabilityBundle 校验冻结文件、Snapshot 与 Bundle Hash；
3. DatasetLoader 解析 `execution_profiles`，或应用历史模块兼容规则；
4. ProviderRegistry 根据 `provider_id` 构造 Provider；
5. DatasetValidator 联合校验 Case、Profile、Tool Snapshot 和故障模式；
6. Provider 为每个 Case 创建隔离 Runtime；
7. Runner 执行 Agent、运行确定性断言；
8. DiagnosticRegistry 选择 Intent 专用规则并与通用诊断合并；
9. Reporting 输出通用 Agent/Provider 元数据和证据。

## 错误处理

新增或稳定使用以下预检错误：

- `UNKNOWN_PROVIDER`：Provider 未注册；
- `EXECUTION_PROFILE_REQUIRED`：旧 Link/E2E 数据集没有冻结 Profile；
- `EXECUTION_PROFILE_INVALID`：Profile 结构错误或引用未知工具；
- `CAPABILITY_BUNDLE_INVALID`：能力 Bundle 完整性失败；
- `CAPABILITY_CONTRACT_MISMATCH`：冻结能力与当前 Agent 不兼容；
- `DATASET_VALIDATION_FAILED`：Case 引用 Profile、工具或故障模式不合法。

所有预检错误均发生在模型客户端创建和外部 API 调用之前，并生成
`INVALID_RUN` 证据，不产生 Agent 通过率。

## 修改范围

Evaluator：

- `schemas.py`：Execution Profile 与通用版本字段；
- `dataset_loader.py`、`dataset_validator.py`：Profile 加载和校验；
- `tool_catalog.py`、`runtime_factory.py`：移除固定 Profile；
- `provider_registry.py`：Provider 注册表；
- `diagnostics.py`、mini_agent Provider 扩展：诊断注册表；
- `cli.py`、`runner.py`、`reporting.py`：使用新接口和通用字段；
- 测试与 README。

Builder：

- Suite 配置 Schema 增加 `execution_profiles`；
- prepare/generation metadata 保留 Profile；
- freeze 将 Profile 写入 Manifest；
- 校验 Profile 引用当前选择后的 Tool Snapshot。

mini_agent：

- 不修改生产 Agent 核心；
- 不把评测 Profile 加入 AgentSnapshot；
- 继续通过现有 Capability Bundle 提供 Tool 合同与当前能力身份。

## 测试与验收

必须满足：

1. Evaluator 和 Builder 全量离线测试通过；
2. Ruff 全量通过；
3. QueryUser v1.6、QueryGift v1.0 预检和离线回放结果不变；
4. 历史 module-only Manifest 无 Profile 时仍可运行；
5. 历史 Link/E2E Manifest 无 Profile 时稳定返回
   `EXECUTION_PROFILE_REQUIRED`，且模型客户端未创建；
6. Profile 引用未知工具、Case 越权工具和非法故障模式均在预检失败；
7. 注册第二个测试 Provider 时不修改 CLI、Runner 或报告核心；
8. 新增测试 Intent 诊断规则时不修改核心诊断代码；
9. 旧 `results.json` 可以迁移读取，新结果只含 `agent_version`；
10. 不执行付费 API 调用。

## 迁移顺序

1. 在 Evaluator 中加入兼容读取模型和注册表，不改变现有默认行为；
2. Builder 支持冻结 `execution_profiles`；
3. 迁移 mini_agent Provider 和 CLI 到新注册表；
4. 删除固定 Profile 常量和专用版本字段写出；
5. 运行跨项目离线验证；
6. 后续新评测集统一使用显式 Execution Profile。
