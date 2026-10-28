# Agent JSON Adapter 与 QueryUser 评测链路迁移设计

## 状态

对话设计已确认。本文件补充既有 Evaluator 解耦与合同插件架构，定义
mini_agent 新 Capability Bundle 的接入方式。实现前还需单独评审实施计划。

## 背景

QueryUser 意图理解评测集 v2.0 已正式冻结，共 42 条 Case。数据集绑定的
Capability Bundle SHA-256 为：

```text
99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8
```

冻结 Bundle 已采用以 `agent.json` 为入口的新协议，而当前 Evaluator 的能力加载器
仍要求旧式 `bundle_manifest.json`。因此预检会在创建 Agent Runtime 和模型客户端前
失败。该问题属于 Provider 边界上的 Agent 协议适配，不应扩散到 Runner、确定性断言、
评分或报告核心。

mini_agent 已提供稳定的无版本公共能力接口 `minimal_agent.capabilities`。Evaluator
不得依赖其内部版本命名空间，例如 `minimal_agent.capabilities.v3`。

## 目标

1. Evaluator 能从 Bundle 根目录的 `agent.json` 加载并校验新版能力快照；
2. mini_agent 的协议差异由 Provider-owned Adapter 吸收；
3. Builder 生成的 canonical `EvalCase` 继续由现有 Runner、断言和评分逻辑执行；
4. QueryUser 全链路使用 Evaluator-owned handler，并保证 Bundle 导出与 Runtime
   执行来自同一个 `ToolRegistry` 实例；
5. 42 条冻结 Case 在 Bundle Hash 未变化时直接复用；
6. 不原地修改历史 FROZEN Manifest；
7. 所有不兼容、路径和 Hash 错误继续在任何模型调用前失败。

## 非目标

- 不修改 Runner 的 Trial 生命周期、断言语义或评分规则；
- 不重新生成或原地编辑当前 42 条 EvalCase；
- 不把 mini_agent 的协议模型引入 Evaluator 核心；
- 不恢复旧式 `bundle_manifest.json` 或生成一份降级兼容 Bundle；
- 不在本次工作中增加 CI；
- 不默认执行语义 Judge 或其他额外付费模型调用。

## 方案选择

### 采用：Provider-owned Stable Adapter

在 `eval_framework.providers.mini_agent` 内新增或重构能力适配层。该适配层：

1. 接收 Bundle 根目录；
2. 要求入口文件为 `<bundle-root>/agent.json`；
3. 通过 Provider-owned、无版本名的 Adapter 按 Bundle 自带 Schema 和引用加载冻结
   文档；调用 mini_agent 能力 API 时只使用 `minimal_agent.capabilities` 公共门面；
4. 将 Agent-specific Bundle 转为 Evaluator 已有的中立 `CapabilityRegistry`；
5. 将 Bundle 身份、模块输出 Schema、Intent 参数 Schema、Tool 声明和故障模式映射为
   现有校验和断言所需的字段。

`CapabilityRegistry` 之后的数据流不变，因此 DatasetValidator、Runner、Assertions、
Scoring 和 Reporting 不需要理解 `agent.json` 的原始结构。

### 不采用：Evaluator 核心直接依赖新版 Bundle 模型

这会让通用模块导入 mini_agent 的协议类型，并迫使后续其他 Agent 适配同一具体格式，
违背 Provider 隔离边界。

### 不采用：将新版 Bundle 转存为旧 Bundle

生成 `bundle_manifest.json` 兼容副本会产生第二个能力事实来源，容易造成 Hash、Schema
和工具声明漂移，也掩盖了 Provider 边界缺少 Adapter 的真实问题。

## 无版本依赖边界

Evaluator 对 mini_agent 能力协议的唯一允许导入入口是：

```python
from minimal_agent.capabilities import ...
```

仓库内不得新增或保留以下依赖：

```python
from minimal_agent.capabilities.v3 import ...
```

版本选择属于 mini_agent 包内部实现。Evaluator 的 Runtime Bundle 构建、校验和导出
只依赖无版本门面公开的能力；冻结 Bundle 的文档转换由 Provider-owned Adapter 根据
`agent.json`、引用和随 Bundle 冻结的 JSON Schema 完成。增加架构守卫测试扫描生产
代码，阻止版本化导入重新出现。

## Bundle 加载与内部映射

### 入口和完整性

Adapter 接收的是 Bundle 根目录，而不是某个内部 Snapshot 文件。它必须：

- 检查 `agent.json` 存在且可读；
- 使用 Bundle 随附的 Schema 校验 `agent.json` 和每个被引用 Snapshot；
- 校验引用路径不越出 Bundle、引用元数据与目标文档一致、Snapshot Hash 正确；
- 读取 `agent.json` 声明的 `capability_bundle_sha256`；
- 根据 `agent.json` 的全部直接子引用重新计算 Bundle Hash；
- 将其与 FROZEN Manifest 声明的 Bundle Hash 比较；
- 在构造 Runtime 或模型客户端前完成以上步骤。

Bundle 中没有任何 `tool_refs` 时，`tools/` 是无引用的可选目录，可以不存在。这正是
当前 42 条 module Case 的冻结形态。Adapter 不通过创建空目录修改历史 Bundle；如果
存在任一 Tool 引用，则对应文件和 Schema 校验仍为强制要求。

缺失入口、无效 Schema、引用缺失和 Hash 不一致统一落入现有预检错误边界，错误证据
可以包含逻辑文件名和期望/实际 Hash，但不得包含密钥或整个 Bundle 内容。

### 中立 Registry 映射

Adapter 生成现有 `CapabilityRegistry` 所需信息：

- Agent 元数据和 Bundle 身份来自 `agent.json`；
- Module 的 `output_schema` 来自相应 module snapshot；
- Intent 的参数 Schema 来自相应 intent snapshot 的 `parameters_schema`；
- Tool 的参数、结果、故障模式和只读/写入属性来自 tool snapshot；
- 引用关系按 snapshot ID 解析，不根据目录名或文件名猜测业务语义。

Adapter 可以使用 Provider 内部 DTO 或构造 Evaluator 的现有 `CapabilityBundle` 中立模型，
但转换后的对象不得向 Runner 暴露 mini_agent 的版本化类型。

## EvalCase 与核心执行链路

Builder 已经把外部评测集规范化为 canonical `EvalCase`。只要 Evaluator 消费该结果，
以下模块保持不变：

- Runner 的 Case/Trial 调度和隔离；
- 确定性断言的执行顺序与通过条件；
- 评分、稳定性聚合和结论优先级；
- 结果证据和报告语义。

本次改动只替换能力加载来源和 mini_agent Runtime 组合方式。相同 EvalCase、相同执行
输出和相同 Registry 应产生与迁移前等价的断言及评分结果。

### Evaluator 接口桥

现有 `MiniAgentAdapter` 已经覆盖执行与结果转换，不需要重写：

- module Case 调用 `run_intent_only()`，消费 `IntentResult` 并读取
  `intent_trace_snapshot()`；
- link/end-to-end Case 调用 `MinimalAgent.run()`，消费 `AgentResult`、
  `ToolCallRecord`、`tool_calls`、`events` 和 `final_response`；
- Evidence Snapshot 只声明这些观测接口和 payload Schema，实际 expected、确定性断言、
  评分、Judge 和报告继续完全位于 Evaluator 外部；
- oracle、Case ID 和期望结果不得进入 Agent Runtime。

因此本次实现不修改 `MiniAgentAdapter`、Runner、Assertions 或 Scoring，只用回归测试固定
既有桥接行为。

## QueryUser ToolRegistry 一致性

QueryUser 全链路必须由 Evaluator 显式注册评测专用 handler。组合过程如下：

1. 为一个 Trial 创建隔离的 `ToolRegistry`；
2. 创建 Evaluator-owned `QueryUserEvaluationHandler`；
3. 通过 mini_agent 测试公共 API 取得 QueryUser tool definition，并将 handler 注册到
   该 Registry；
4. 使用这个确切的 Registry 实例导出或验证本 Trial 的 runtime Capability Bundle；
5. 将同一个 Registry 实例注入该 Trial 的 Agent Runtime；
6. Trial 结束后释放 Registry 和 handler，不在不同 Trial 间共享可变状态。

“同一个 ToolRegistry”指同一 Trial 内导出/验证 Bundle 与实际工具执行使用对象身份相同，
而不只是分别构造两个内容看似相同的 Registry。这样可以防止工具声明与实际 handler
集合发生漂移，同时保留 Trial 隔离。

当前 42 条 QueryUser 意图理解 Case 属于 module 范围且允许工具集合为空，因此实际执行
不会调用 QueryUser 工具；但全链路注册约束必须由独立的 Provider 集成测试固定，避免
未来 Link/E2E 数据集接入时再次修改核心。

## 冻结数据集与路径策略

当前 FROZEN Manifest 的 Bundle 路径是相对路径：

```text
capability_bundles/<bundle-hash>
```

它没有写死 `capabilities-v3`，且该目录内已存在 `agent.json`。因此：

- 继续使用当前 42 条 Case 和原 Bundle Hash；
- 不修改 JSONL、Coverage 或历史 Manifest；
- DatasetLoader 仍以 Manifest 的相对路径解析冻结 Bundle；
- Adapter 在解析后的 Bundle 根目录读取 `agent.json`。

如果其他历史 FROZEN Manifest 确实写死了 `capabilities-v3`，不得原地修改。允许两种
方式：

1. 运行时通过外部 Provider 配置指定 Bundle 根目录覆盖；
2. 使用 Builder 重新冻结为一个具有新身份的新数据集。

外部覆盖只改变物理定位，不改变声明的能力身份。编译阶段必须校验覆盖内容的 Bundle
Hash 与 Manifest 绑定值相同。`CompiledSuite` 和运行产物记录覆盖内容指纹及来源类型，
但不把机器相关绝对路径写入 canonical 可复现身份。

## 数据流

```text
FROZEN JSONL + Manifest
  -> DatasetLoader / Suite Compiler
  -> canonical EvalCase
  -> MiniAgent Provider Adapter
       -> <bundle-root>/agent.json
       -> minimal_agent.capabilities
       -> Evaluator CapabilityRegistry
  -> per-Trial ToolRegistry
       -> QueryUser evaluator-owned handler
       -> runtime Bundle export/verification
       -> native Agent Runtime injection
  -> existing Runner
  -> existing Assertions
  -> existing Scoring and Reporting
```

## 配置与秘密

正式运行继续通过环境或受支持的秘密注入方式提供：

- `MODEL_PROVIDER=deepseek`；
- `DEEPSEEK_API_KEY`；
- 可选的 DeepSeek model/base URL 配置。

API Key 不写入 Suite、Manifest、命令示例、日志或运行产物。外部 Bundle 路径覆盖属于
Provider 运行配置，不属于历史 Manifest 变更。

## 错误处理

至少覆盖以下失败：

- Bundle 根目录缺少 `agent.json`；
- Bundle 公共校验失败或引用文件缺失；
- Manifest Hash 与 `agent.json` 身份不一致；
- 外部覆盖内容 Hash 与冻结绑定不一致；
- Adapter 无法映射 Case 引用的 Module、Intent 或 Tool；
- QueryUser 全链路缺少 evaluator-owned handler；
- Bundle 导出所用 Registry 与 Runtime 注入 Registry 不是同一实例；
- 生产代码导入 `minimal_agent.capabilities.v3`。

这些错误必须在首次模型请求前暴露。对于结构完整但不支持某个业务能力的情况，返回
稳定的能力合同不匹配错误，不进行静默降级或目录猜测。

## 修改范围

预计修改集中在：

- `src/eval_framework/providers/mini_agent/`：稳定 Bundle Adapter、Provider 组合和
  QueryUser Registry binding；
- `src/eval_framework/contracts/compiler.py`：让 Bundle 合同入口兼容 `agent.json`，并
  保持覆盖指纹 path-free；
- 对应 Provider、合同编译、架构守卫和端到端测试；
- README 中 Bundle 入口与运行说明。

现有 `ToolRegistryFactory` 可以在返回 Registry 前使用该对象导出 runtime Bundle，再由
`RuntimeFactory` 原样注入，因此原则上不修改 `runtime_factory.py`。也不计划修改
DatasetBundle Schema、DatasetLoader、MiniAgentAdapter、Assertions、Scoring 或 Runner。

## 测试与验收

必须满足：

1. 能直接加载只含新协议入口的 `<bundle-root>/agent.json`；
2. `tool_refs` 为空时允许 Bundle 不含 `tools/`，有 Tool 引用时缺失文件必须失败；
3. 无效 Bundle 和 Hash 不匹配在 Runtime/模型客户端创建前失败；
4. Evaluator 生产代码不存在 `minimal_agent.capabilities.v3` 导入；
5. 当前 42 条冻结 EvalCase 和 Manifest 字节不被修改；
6. 42 条 Case 可以完成 validate，并能进入 native DeepSeek 正式执行路径；
7. Module 输出 Schema 与 Intent 参数 Schema 断言继续使用现有实现并通过回归测试；
8. QueryUser handler 由 Evaluator 注册；
9. 同一 Trial 的 Bundle 导出/验证与 Runtime 使用同一个 `ToolRegistry` 对象；
10. 不同 Trial 使用不同 Registry，避免状态泄漏；
11. 外部路径覆盖不修改 FROZEN Manifest，Hash 相同可接受，Hash 不同拒绝；
12. 固定夹具在迁移前后的 Runner、断言和评分结果等价；
13. 全量离线测试与 Ruff 通过；
14. 不添加 CI，不在默认测试中产生 DeepSeek 费用。

## 实施与正式运行顺序

1. 以测试驱动方式实现 Stable Adapter 与 `agent.json` 预检；
2. 接入 QueryUser per-Trial Registry binding；
3. 补齐路径覆盖、Hash、导入边界和回归测试；
4. 运行全量离线测试与静态检查；
5. 验证 FROZEN 数据集及 Manifest 未被修改；
6. 检查本地 DeepSeek 环境变量是否已配置，不输出秘密；
7. 先执行 42 条 Case 的 validate；
8. 再显式执行 native DeepSeek 评测并保存完整运行产物；
9. 汇总通过率、失败断言、运行错误、模型配置和可追溯指纹。
