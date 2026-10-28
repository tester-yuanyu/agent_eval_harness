# Portable Capability Snapshot Kit 设计

## 1. 背景

`mini_agent` 当前可以导出 Capability Snapshot Protocol v3，但快照事实的来源并不统一：

- Tool 和 Intent 的一部分事实来自运行时 Registry 与 Contract；
- Scope、Chain、Evidence、Boundary 主要来自 Python Catalog 中的静态字典；
- Module 同时包含运行时推导与静态声明；
- 协议文档只供人阅读，不参与生成；
- 生成后的 `capabilities-v3/*.json` 又作为一套独立制品保存在仓库中。

这使“自动生成快照”实际上依赖大量 MiniAgent 专属硬编码，容易造成运行时代码、Catalog、文档和导出 Bundle 之间的漂移，也不利于将能力快照机制迁移到其他 Agent。

## 2. 目标

在 `mini_agent` 仓库内建设一个边界独立、未来可直接迁出的 Capability Snapshot Kit。该 Kit 组合三类输入：

1. 面向人的自然语言能力约束；
2. 面向编译器的结构化约束；
3. 由目标 Agent Adapter 提供的真实运行时事实。

Kit 编译并校验这些输入，继续输出与当前 Builder 兼容的 Capability Protocol v3 Bundle。

成功标准：

- 当前 v3 快照类型、ID、引用方向、文件布局和外部 API 保持兼容；
- 通用包不依赖 `minimal_agent`；
- 迁移到其他 Agent 时只需复用 Kit 与 Capability Spec，并新增一个薄 Adapter；
- Spec 只能定义能力要求，不能把某个 Agent 的能力直接判为 `supported`；
- 未声明或无法验证的能力保持 `unknown`；
- 新旧生成器对相同运行配置产生语义等价的 Bundle；
- Builder 无需补写业务规则。

## 3. 非目标

本次重构不负责：

- 生成评测题、覆盖矩阵或 `EvalCaseV2`；
- 实现 Judge、评分、Evaluator Fixture 或业务数据；
- 扩展 MiniAgent 当前实际能力；
- 把缺失能力伪装成 `supported`；
- 使用大模型临时解析自然语言正文并决定快照内容；
- 在本阶段拆分为独立仓库或发布到包索引。

## 4. 总体架构

```text
自然语言约束 + 结构化 Capability Spec
                    ↓
           Capability Snapshot Kit
                    ↑
       Target Agent Capability Adapter
                    ↑
        Registry / Contract / Runtime
                    ↓
     Capability Protocol v3 Bundle
                    ↓
                  Builder
```

仓库中的目标布局：

```text
capability_specs/
├── protocol.md
├── scopes/
├── chains/
├── evidence/
└── boundaries/

src/capability_snapshot_kit/
├── adapter.py
├── compiler.py
├── models.py
├── spec_loader.py
├── validation.py
├── resolution.py
├── diffing.py
└── cli.py

src/minimal_agent/
└── capability_adapter.py
```

依赖方向固定为：

```text
capability_snapshot_kit
          ↑
MiniAgentCapabilityAdapter
          ↑
minimal_agent runtime
```

`capability_snapshot_kit` 不得导入 `minimal_agent`，也不得引用 MiniAgent 的 Intent 模型、ToolRegistry 或运行时事件类型。

## 5. Capability Spec

### 5.1 两类事实必须分离

Capability Spec 描述“评测某能力需要什么”，Agent Adapter 描述“当前 Agent 实际有什么”。

例如：

- “全链路需要理解、规划、执行和结果节点”属于通用 Spec；
- “MiniAgent 不支持跨轮 Context”属于 MiniAgent Adapter 提供的事实；
- “工具执行需要 Tool Trace”属于通用 Spec；
- “当前 ToolRegistry 中没有注册工具”属于运行配置事实。

Scope 和 Chain 不缓存具体组合后的最终支持状态。最终的 `supported / unsupported / unknown` 由编译器或 Resolver 将要求与 Agent 事实绑定后计算。

### 5.2 文件格式

每项可迁移能力使用 Markdown 文件，结构化 YAML Front Matter 与自然语言正文位于同一制品中：

```markdown
---
id: chain.end_to_end
version: "1.0"
required_nodes:
  - understanding
  - planning
  - execution
  - result
required_evidence:
  - evidence.intent_result
  - evidence.tool_trace
  - evidence.final_response
terminal_states:
  - success
  - failure
  - partial_success
  - asynchronous
---

# 全链路能力约束

该链路从用户输入开始，到最终结果完成为止。

- 缺少任何强制节点时，不得判定为 supported。
- 未声明的恢复能力按 unknown 处理。
- 工具执行必须提供可关联的 Tool Trace。
```

职责划分：

- YAML Front Matter 是编译器读取的可执行约束；
- Markdown 正文解释语义、边界、禁止事项、示例和迁移方法；
- 二者共同组成可迁移 Capability Spec；
- 编译器不通过自然语言推断机器字段；
- Spec 的 Schema 校验失败时停止导出；
- Spec 不得声明某个具体 Agent 已支持一项能力。

自然语言正文不是第二套结构化事实源。它是规范性的人类接口，用于审查、迁移和解释；所有影响机器判定的规则必须在 Front Matter 中有明确表达。

Front Matter 使用 YAML 1.2 安全集，不允许自定义 tag 或对象构造。实现通过显式依赖的安全 YAML Loader 读取，解析结果必须继续通过 Pydantic Spec 模型校验，不能直接进入编译阶段。CLI 必须显式接收 `--spec-root`；仓库内默认值为 `capability_specs/`。迁移到其他 Agent 时，Kit 代码与该目录作为一组版本化制品交付。

### 5.3 权威来源与冲突规则

三类输入的权威范围固定如下：

- Markdown 正文：能力语义、迁移说明、人工审查依据；
- YAML Front Matter：通用要求、引用、完成条件和允许的终态；
- Agent Adapter Facts：当前 Agent、当前运行配置是否真实提供相应能力与 Evidence；
- 生成后的 JSON：只读构建产物，不是编辑源。

当正文与 Front Matter 不一致时，Spec 审查必须失败并由维护者修正；编译器不尝试理解正文并自动裁决。当 Front Matter 的要求与 Adapter Fact 冲突时，运行时事实优先决定支持状态：明确不支持为 `unsupported`，缺少可验证事实为 `unknown`。结构冲突、重复 ID、类型不一致和不可能满足的引用属于编译错误，不得降级后继续导出。

## 6. 通用 Adapter 接口

Kit 定义与具体 Agent 无关的协议：

```python
class CapabilityAdapter(Protocol):
    def agent_facts(self) -> AgentFacts: ...
    def module_facts(self) -> list[ModuleFact]: ...
    def intent_facts(self) -> list[IntentFact]: ...
    def tool_facts(self) -> list[ToolFact]: ...
    def evidence_facts(self) -> list[EvidenceFact]: ...
```

上述 Fact 类型由 `capability_snapshot_kit` 定义，只包含协议中立的数据结构。

`MiniAgentCapabilityAdapter` 的映射职责：

```text
IntentRegistry       → IntentFact
ToolRegistry         → ToolFact
运行时模块            → ModuleFact
事件和返回结果接口      → EvidenceFact
版本与运行配置          → AgentFacts
```

Adapter 必须遵循以下规则：

- Tool 仅来自当前实际注册的 ToolRegistry；
- Intent 的 Tool 引用仅在同名 Tool 实际注册时产生；
- 权限、风险、确认、幂等和结果协议来自 ToolContract；
- QueryUser 评测 Tool 只有在显式注册评测 Adapter 时才进入 Bundle；
- Adapter 不得修改通用 Scope、Chain 或 Boundary 定义；
- Adapter 无法证明的事实不得报告为 `supported`。

其他 Agent 通过实现相同接口接入，不修改编译器和协议 Spec。

## 7. 编译与导出流程

标准流程如下：

```text
1. 加载 Capability Spec
2. 按 Spec Schema 校验结构和引用
3. 调用 Agent Adapter 获取真实事实
4. 规范化并校验 Agent Facts
5. 将通用要求与 Agent Facts 绑定
6. 对缺失或不可验证事实应用 unknown
7. 生成 v3 Snapshot 对象
8. 校验单向引用 DAG、版本与 Hash
9. 原子导出 capabilities-v3/
```

支持状态规则：

- 显式 `unsupported` 优先；
- Provider、声明、版本或 Evidence 缺失时为 `unknown`；
- mandatory requirements 及其 Evidence 全部明确支持时才为 `supported`；
- optional requirement 的缺口进入 diagnostics，但不降低最终状态；
- Spec 本身不能证明运行时支持能力。

默认 Bundle 继续使用空 ToolRegistry，因此导出零 Tool。注册 QueryUser 评测 Adapter 后，必须从同一 Registry 导出独立 Bundle，保证运行配置与能力快照绑定。

## 8. v3 兼容边界

重构只改变快照来源，不改变 Builder 协议。

必须保持：

- `snapshot_format_version: "3.0"`；
- Agent、Module、Intent、Tool、Scope、Chain、Evidence、Boundary 类型；
- 快照 ID、契约版本与单向引用方向；
- 现有目录布局；
- Hash 与版本验证规则；
- 三态解析规则；
- Source Pack 所需信息；
- `export / validate / resolve / diff` CLI 能力；
- 现有公开 Python API，必要时通过兼容包装器委托给 Kit。

允许发生的变化：

- 不影响语义的 JSON 字段排序；
- 修正已证实的虚假能力声明；
- 由于规范化序列化变化导致的 Snapshot 或 Bundle Hash 变化。

任何有语义的变化都必须在 diff 中明确报告，不能以“重构”为由静默改变。

## 9. 迁移策略

### 阶段一：建立通用边界

- 新增 `src/capability_snapshot_kit/`；
- 新增 `capability_specs/`；
- 将现有 v3 数据模型、校验、解析和 diff 能力迁入通用包；
- 保留原有导出器和 CLI，不改变 Builder 输入。

### 阶段二：接入 MiniAgent Adapter

- 实现 `MiniAgentCapabilityAdapter`；
- 从 Registry、Contract 和运行时观测接口生成 Facts；
- 将 Scope、Chain、Evidence 和 Boundary 静态定义迁入 Capability Spec；
- 禁止 Kit 引用 `minimal_agent`。

### 阶段三：双生成器比对

旧 Catalog 生成器与新 Spec Compiler 并行输出临时 Bundle，并对以下配置执行 semantic diff：

1. 默认零工具配置；
2. 显式注册 `query_user_info` 评测 Tool 的配置。

出现语义差异时停止迁移，逐项判断是实现缺陷还是需要明确批准的事实修正。

双生成器切换的初始门槛是 semantic diff 为空。若迁移过程中发现旧 Catalog 存在虚假声明，应将事实修正作为独立变更记录、评审和验收，不能混入无语义变化的重构提交。

### 阶段四：Builder 验收

至少覆盖：

- QueryUser 意图理解；
- QueryUser Context；
- QueryUser 关键链路；
- QueryUser 全链路；
- 缺少 Tool；
- 引用、版本或 Hash 被篡改。

Builder 必须继续完成：

```text
递归解析 → Resolved Capability Graph → Source Pack
→ Coverage Slot → EvalCaseV2
```

### 阶段五：切换与清理

- 现有 CLI 和 Python API 内部切换到新 Compiler；
- 全部兼容测试通过后删除旧 `topology_catalog.py`；
- 删除 `runtime_catalog.py` 中已由 Adapter 和 Contract 提供的静态事实；
- 保留必要的兼容导入层，并标记后续移除版本；
- `capabilities-v3/` 继续作为可验证的发布 Bundle 或金丝雀制品，不作为人工编辑源。

## 10. 验证策略

### 10.1 通用 Kit

- 使用不依赖 MiniAgent 的 Fake Adapter 生成完整合法 Bundle；
- Spec Loader 覆盖格式错误、重复 ID、断裂引用和版本不兼容；
- Compiler 覆盖 supported、unsupported、unknown；
- Validator 覆盖 DAG、Hash、Schema 和 Bundle 一致性；
- Resolver 与 Diff 保持现有语义。

### 10.2 MiniAgent Adapter

- 默认 Registry 导出零 Tool；
- Intent 和 Tool 参数 Schema 与 Contract 一致；
- Tool 注册状态、风险、确认、幂等和结果协议来自真实 Contract；
- Evidence 只在运行时存在对应接口时声明可用；
- QueryUser 评测 Adapter 显式注册后才导出 Tool 快照。

### 10.3 兼容性

- 新旧默认 Bundle semantic diff 为空；
- 新旧 QueryUser 评测 Bundle semantic diff 为空；
- v3 Builder fixtures 继续通过；
- v2 Bundle 与解析器保持冻结；
- 当前完整测试、静态检查和 CLI 验证全部通过。

## 11. 失败与安全策略

- Spec 缺少机器可执行字段时，编译失败；
- Adapter Fact 与 Spec 冲突时，编译失败并指出冲突来源；
- 事实无法验证时输出 `unknown`，不得猜测；
- Snapshot 引用、版本或 Hash 不一致时拒绝 Bundle；
- 导出使用临时目录和原子替换，失败时保留旧 Bundle；
- 迁移期间旧生成器保持可用，直到双生成器和 Builder 验收全部完成。

## 12. 最终边界

重构完成后：

- Capability Snapshot Kit 拥有协议模型、Spec 读取、编译、校验、解析和 diff；
- Capability Spec 拥有可迁移的自然语言约束和结构化要求；
- MiniAgent Adapter 只拥有 MiniAgent 的真实能力映射；
- MiniAgent Runtime 继续拥有实际 Intent、Tool、执行和 Evidence；
- Builder 继续消费标准 v3 Bundle；
- Evaluator 继续拥有 Fixture、数据隔离、故障注入和评分。

该边界保证能力快照机制可以在不复制 MiniAgent 专属硬编码的前提下迁移到其他 Agent。
