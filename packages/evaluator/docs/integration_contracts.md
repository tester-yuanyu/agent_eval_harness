# Evaluator 契约与接入规范

2026-10-20 更新：Inspect 负责正式调度、判分和指标；Evaluator 保留业务扩展；Langfuse 接管展示和人工标注。旧 DeepEval Runner/G-Eval 路径已删除；2026-10-28 起可选接入 [Conversation Completeness](conversation_completeness.md)，仍由 Inspect 执行。最新单一职责、权威数据与验收限制见 [接入说明](langfuse.md)。

本文面向需要接入新 Agent、数据集格式或测试环境的开发者。依据为 2026-10-13 当前工作区，包含尚未提交的实现。能力边界见[能力清单](capabilities.md)，执行顺序见[架构说明](architecture.md)。

## 1. 先确定接入类型

| 需求 | 应实现或准备的内容 | 当前边界 |
| --- | --- | --- |
| 用现有 mini_agent 评测新任务 | 冻结数据集、能力包、执行 Profile 和 Suite | 任务必须在当前 Agent 与 Provider 的支持范围内 |
| 接入另一种数据格式 | DatasetLoaderPlugin、描述符、注册与 Suite | Loader 必须生成统一 DatasetBundle，Runner 不按外部格式分支 |
| 接入新 Agent | ProviderFactory、EvaluationProvider、能力与工具映射、描述符和注册 | Provider 需要自行适配 Agent API、异常和证据 |
| 接入有状态测试环境 | Provider 配置、工具实现、初始数据、状态读取和清理 | Suite 中写配置不会自动创建所需环境 |
| 新增评分或报告规则 | 当前代码中的相应实现与测试 | 尚不能承诺只新增 Profile 文档即可接入任意规则 |

## 2. 契约之间的关系

```text
SuiteDefinition
  ├─ dataset_loader：可信 Loader 的精确 ID、版本和配置
  ├─ dataset_sources：显式列出的数据文件及 SHA-256
  │    ├─ EvalCase：execution + oracle + 范围与标签
  │    └─ Manifest：冻结元数据、绑定与 execution_profiles
  ├─ provider：可信 Provider 的精确 ID、版本和配置
  ├─ capability_bundle：能力快照入口及 SHA-256
  │    └─ Agent、模块、意图、工具和 Schema 等引用契约
  └─ run_config：运行模式、Trial 次数、阈值和过滤等
```

这里以冻结 JSONL Loader 为例；其他 Loader 可以采用不同的外部组织方式，但必须输出相同内部协议。

| 契约 | 负责回答的问题 | 不能替代的内容 |
| --- | --- | --- |
| Suite | 本次使用哪些实现、文件、版本和参数？ | 插件可执行代码、真实环境 |
| Capability Bundle | Agent 声明哪些接口、能力、工具及证据？ | Case 的期望答案、实际运行观测 |
| EvalCase.execution | 向 Agent 输入什么，采用什么执行限制？ | 评分预期 |
| EvalCase.oracle | 预期什么行为，按什么规则判断？ | 模型输入或工具配置 |
| Manifest / execution_profiles | 数据集身份、冻结状态和各 Profile 可用工具是什么？ | 从当前工作区推测出的能力 |
| Judge Rubric | 如何评价声明的语义维度？ | 安全、权限、确认和终态的确定性检查 |
| Gate Policy | 质量结果满足哪些发布要求？ | Case 判定、原始结果修改 |

Schema 入口为 [Suite Schema](../schemas/suite_definition.schema.json) 和 [EvalCase Schema](../schemas/eval_case.schema.json)。运行时模型分别见 [contracts/models.py](../src/eval_framework/contracts/models.py) 和 [schemas.py](../src/eval_framework/schemas.py)；JSON Schema 快照由测试核对，变更模型时应同步维护。

## 3. Suite 与文件绑定要求

1. 使用精确的 plugin_id 与 version。插件按 `(kind, id, version)` 注册和解析，不自动选择最近版本。
2. 将所有影响执行的数据源显式列入 dataset_sources。冻结 JSONL 与 Manifest 分别记录 SHA-256；不能依赖未声明的相邻文件。
3. 引用使用根目录内的相对路径，校验 Hash；不能通过 `..` 或符号链接逃逸约定根目录。
4. 新能力包以带校验的 agent.json 为入口，历史 bundle_manifest.json 路径保留兼容；不要用工作区当前快照悄悄替换冻结快照。
5. 正式 agent_benchmark 使用 FROZEN 数据。允许非冻结运行时应显式声明，结果仅用于临时观察，不能当正式基线或发布依据。
6. 配置只描述数据，不能声明 Python 模块、程序入口、Shell 命令或内联代码。凭据通过环境提供，不写入 Suite 或报告。

可参考[历史格式 Suite](../suites/mini_agent_module_v1/suite.json)了解文件组织。其冻结能力包不保证与当前 mini_agent 兼容；第一次验证当前环境优先运行[状态型示例](../examples/stateful_gift.py)，由示例导出匹配的自测契约。

Suite 中 assertion_profile、trace_profile、judge_profile、report_profile、gate_policy 的字段存在，不表示已完成统一执行接入。当前文件 Suite 显式启用 judge_profile 或 run_config.judge 会报 PROFILE_STAGE_NOT_MIGRATED。现阶段 Judge 使用既有兼容 CLI/API，Gate 使用独立命令；不要仅添加引用就假设功能生效。

## 4. 用例与执行 Profile

ExecutionSpec 包含 user_input、user_responses、tool_profile、可选 allowed_tools、fault_injection、max_steps 和 timeout_seconds 等字段。字段通过 Schema 校验之后，还必须通过 Provider 的语义校验；例如声明 fault_injection 并不意味着当前环境已支持故障注入。

OracleSpec 包含预期模块输出、Agent 状态、工具调用、禁止工具、目标状态、过程约束和 evaluation.checks 等。断言声明指定 name、weight、critical 和 config。运行时及模型客户端工厂只能接收 ExecutionSpec，不读取 Oracle，也不能按 Case ID 选择标准答案。

冻结 execution_profiles 将工具 Profile 名称映射到 allowed_tools，工具必须属于绑定的能力包。历史 Manifest 缺少此字段时，仅 module 案例保留空工具集兼容；link/end_to_end 缺失冻结 Profile 会被拒绝。

当前 mini_agent 的 scope 约定：

- module：调用一次纯意图入口，不接受后续 user_responses。
- link：调用一次 Agent.run，不接受后续 user_responses。
- end_to_end：在澄清或确认等待状态继续消费声明输入，到终态或输入耗尽时停止。

需要校验中间行为时使用 turns_match；轮次数、状态、工具顺序和次数按声明要求检查，参数、工具入参和状态对象采用声明的子集匹配。具体可运行数据由状态型示例生成。

## 5. Provider 接口与责任

权威接口为 [provider.py](../src/eval_framework/provider.py)，不要仅凭本文表格创建省略方法的实现。

| 接口 | 责任 |
| --- | --- |
| ProviderFactory.create(dataset, model_client_factory, **kwargs) | 根据已验证数据与配置构造 Provider |
| provider_id / provider_version | 标识接入实现，必须与数据绑定一致 |
| capabilities / tools / diagnostics | 提供能力、工具元数据和诊断路由 |
| create_runtime(execution, session_id, scope) | 为 Trial 创建运行时及资源 |
| run_module(runtime, execution) | 执行模块级调用并返回 AdapterOutput |
| run_full(runtime, execution, scope) | 执行 link/end_to_end 并返回 AdapterOutput |
| cleanup(runtime) | 清理 Trial 自有资源，核验结果；失败抛出异常 |
| classify_exception(exc) | 将 Agent 异常映射为标准执行状态，尽可能保留部分输出 |
| runtime_metadata(runtime) / tool_version(runtime) | 提供可审计运行身份，不泄露凭据 |

需要独立取证时，实现可选 create_observed_runtime(execution, session_id, scope, sink)，向 Agent 注入 Sink。Runner 管理整个 Trial 的 Sink，Provider 不在单轮后关闭。旧 Provider 可以保留内嵌证据路径，但独立通道启用后不允许失败回退。

AdapterOutput 提供 module_output、turns、before_snapshot、turn_snapshots、snapshot 等实际观察。涉及真实写操作时，状态必须来自实际存储读取；不能根据工具成功文案或 Oracle 生成状态。

建议在 Provider 配置旁记录五项环境约定：工具是模拟还是真实测试实现、初始数据版本、状态读取方式、清理与核验方式、限制及不支持项。初始化在返回 runtime 前失败时，由 Provider 回收已分配资源；Runner 无法清理由它尚未获得的运行时对象。

当前 gift_sqlite_v1 的 Suite 配置为：

```json
{
  "plugin_id": "mini_agent_provider_v1",
  "version": "1.0.0",
  "config": {"environment": "gift_sqlite_v1"}
}
```

该环境仅支持其声明的礼物工具，初始化空账本，每次调用真实记录写入并保留重复操作，不补实现 Agent 的确认接受能力。应绑定用该环境工具注册表导出的能力包。

## 6. Loader、描述符与注册

DatasetLoaderPlugin.load 接收已解析 sources、filters 和 config，返回 DatasetBundle；接口见 [plugins/protocols.py](../src/eval_framework/plugins/protocols.py)。新 Loader 不应把外部格式分支泄漏到 Runner，也不能把 Oracle 转成脚本答案注入运行时。

插件描述符包含 plugin_id、kind、version、config_schema、supported_contract_versions 和 implementation_fingerprint。配置 Schema 应拒绝未知字段，实现指纹应覆盖影响行为的源码。调用 catalog.register(descriptor, implementation) 显式注册，参考 [composition.py](../src/eval_framework/composition.py)。

Provider 可实现 validate_dataset 进行创建运行时之前的语义预检。接入新插件至少验证：合法输入可以运行，非法配置、未知版本、能力不匹配及越界路径在运行前失败；新格式或 Provider 不要求 Runner 增加专用分支。

## 7. 当前 Python 执行路径

下面是现有接口的调用模板；suite.json 需替换为已准备并校验的 Suite。真实运行仍需准备所选 Provider 的模型和环境。

```python
from pathlib import Path

from eval_framework import (
    ContractStore,
    compile_suite,
    execute_compiled_suite,
    load_suite_definition,
    write_report,
)
from eval_framework.composition import default_plugin_catalog

suite_path = Path("suite.json").resolve()
catalog = default_plugin_catalog()  # 自定义插件在此组装阶段显式注册
compiled = compile_suite(
    load_suite_definition(suite_path),
    catalog,
    ContractStore(suite_path.parent),
)
result = execute_compiled_suite(compiled, catalog, output_dir="artifacts")
paths = write_report(result, "artifacts")
print(paths.report)
```

离线自测在 execute_compiled_suite 中传入 model_client_factory，工厂签名为 `(ExecutionSpec) -> ModelClient`。完整可执行实现见[状态型示例](../examples/stateful_gift.py)，不要把脚本模型自测结果当作真实模型质量结论。

## 8. 接入验收与变更管理

接入完成应提供一组可重复执行的样例和以下证据：已知正确行为通过，已知错误行为失败，缺失证据不误判通过，异常后清理并继续后续 Trial，报告可追溯至所用契约与插件指纹。命令与现有测试见[验收手册](acceptance_examples.md)。

改变数据、能力契约或判定语义时产生新版本与 Hash，不覆盖既有冻结文件。改变比较条件后，基线与候选应在相同新条件下重跑。断言语义版本以当前实现及产物为准；旧设计文档中的版本不能替代运行清单。人工复核与回归用例交接保留原运行、原始结果和审核记录。
