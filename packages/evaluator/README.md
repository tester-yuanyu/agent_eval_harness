# Agent Evaluator 自动化评测框架 第二阶段

## 项目理解文档

整体方案见 [基于 Inspect AI 的 Agent 自动化评测技术方案](docs/evaluator_technical_design.md)，已按当前架构、迁移结果和真实评测更新。以下文档进一步说明能力、架构、接入和验收：

1. [能力清单与边界](docs/capabilities.md)：当前能做什么、前置条件与限制，以及尚未完成的能力。
2. [架构与运行流程](docs/architecture.md)：模块职责、一次评测的数据流、异常边界及与目标架构的差距。
3. [契约与接入规范](docs/integration_contracts.md)：Suite、能力包、用例和执行 Profile 的关系，以及 Provider/Loader 接入要求。
4. [能力验收与示例手册](docs/acceptance_examples.md)：离线示例、预期结果、产物阅读方式与现有测试入口。
5. [评测指标字典](docs/metric_dictionary.md)：逐项标明 Inspect 原生／DeepEval 复用／业务自研／暂不适用，定义证据、口径与 Gate 用途，包含已接入的 Conversation Completeness 诊断指标和其余专项指标的验收顺序。

当前默认评测框架与迁移边界见 [Inspect AI 主评测框架](docs/inspect_engine.md)，实施结果见 [迁移验收记录](docs/inspect_migration_acceptance.md)。

当前按“原生替换、业务扩展、额外原生能力保留”划分的能力地图见 [Inspect 迁移说明](docs/inspect_engine.md)。原 [DeepEval 能力对照](docs/deepeval_capability_mapping.md) 作为选型历史保留。

详细判定和证据约定分别见[评测报告规范](docs/evaluation_report_spec.md)与[独立证据通道规范](docs/TRACE_PHASE1.md)。

## 项目概览

这是一个独立、可复现的 Agent 评测框架。核心逻辑不绑定特定 Agent，通过显式注入的 Provider 提供能力契约、工具元数据、执行能力、异常映射和可选诊断规则。

第二阶段由 Inspect AI 承担 Trial 调度、正式 Scorer 与指标聚合，语义 Judge 使用原生 `model_graded_qa`。Evaluator 只保留业务规则、适配、独立取证、契约校验与发布门禁。Langfuse 负责可视化、实验对比和人工标注，支持本地部署。每项指标只计算一次；原始结果为权威来源，Langfuse 只接收结果。详见 [接入与职责边界](docs/langfuse.md)。

仓库中的首个 Provider 面向 `minimal-agent`，因此当前依赖方向是 `agent_evaluator -> mini_agent`。契约驱动的插件层会在执行前，将带版本的 Suite 文档编译为统一内部协议。框架可以确定性导入候选交付并生成标准 Suite，但不推断或改写评分预期；也不包含 CI 工作流、HTML 输出或托管服务。

## 本地报告与看板

按[本地 Langfuse 部署与自动交付说明](docs/local_langfuse.md)初始化后，每次 `run` 自动保存正式报告、同步本机 Langfuse，并返回本轮看板链接。服务不可用时保留待同步回执和原评测退出码；`sync-local --source PATH` 可补同步已有结果，无需重跑 Agent。

## 契约驱动的 Suite 入口

推荐使用严格校验的 `SuiteDefinition` 作为入口。它指定 Loader 和 Provider 插件的精确版本，为每个数据源记录 Hash，并且只引用明确根目录范围内的数据契约。在创建 Provider、Agent 运行时或模型客户端前，编译阶段会解析并校验所有引用。每次运行都会保存规范化编译快照及其 SHA-256。

```bash
python -m eval_framework.cli validate \
  --suite suites/mini_agent_module_v1/suite.json
python -m eval_framework.cli run \
  --suite suites/mini_agent_module_v1/suite.json \
  --output-dir artifacts
```

`legacy_jsonl_eval_case_v1` 保留现有冻结 JSONL/Manifest 格式。`fixture_json_document_v1` 用于验证第二种数据源格式也能生成相同的 `DatasetBundle`，而不必修改 Runner。仓库中的 mini-agent Suite 自包含所需文件，其相对路径引用的数据集、Manifest 和 Capability Bundle 可以一起迁移。

所有影响执行的文件都必须显式声明。使用旧版 JSONL Loader 时，应将 JSONL 与 Manifest 分别列入 `dataset_sources`，各自记录 SHA-256；数据集在前，备用 Manifest 按查找顺序排列。内容解析不依赖文件扩展名。如果使用当前格式的 Capability Bundle，应将 `capability_bundle` 指向该能力包中带 Hash 校验的 `agent.json`。历史能力包继续使用 `bundle_manifest.json`；Suite 不能从相邻文件隐式继承未声明的能力包绑定。随后，Provider 的语义预检会在创建 Provider 运行时或模型客户端前，校验解析后的能力、工具配置和案例评分预期。

约束文档被视为不可信数据，不能指定 Python 模块、程序入口、Shell 命令或内联代码。只有在应用组装入口显式注册的实现才能执行。插件按照精确的 `(kind, id, version)` 解析，并校验实现指纹；不支持自动发现或版本回退。

## 新 Agent 交付自动接入

使用 `--input` 接收候选目录/ZIP，也可自动识别既有 Suite JSON 和 EvalCase JSONL。候选导入会保留来源、状态和 blocked 记录；静态契约检查与业务执行生成独立的标准 Inspect 结果。

```bash
agent-evaluator validate --input /path/to/delivery.zip --output-dir artifacts/intake
agent-evaluator run --input /path/to/delivery --agent-root /path/to/nanobot \
  --output-dir artifacts/nanobot
agent-evaluator run --input /path/to/delivery.zip --binding /path/to/trusted-binding.json \
  --output-dir artifacts/new-agent
```

缺失运行绑定时仍可执行静态分区，业务记录保留在导入账本；有 blocked 时返回 `5`。候选草稿结果不能用于发布放行。通用 stdio 绑定只传执行信息、返回 observations，正式评分仍由 Inspect 承担。导入时自动记录所选运行文件 hash，执行前复验；绑定启动的是受信本地进程，不提供操作系统沙箱。详见[接入协议、绑定示例和结果说明](docs/agent_onboarding.md)。

## 安装

需要 Python 3.11 或更高版本。在本项目目录中执行：

```bash
python3.11 -m venv .venv
.venv/bin/python scripts/bootstrap_inspect.py --agent-path ../mini_agent
```

Inspect AI 固定为 0.3.280，使用本地源码，以 Task / Solver / Scorer / Epochs 负责调度、判分和原生日志。业务源码位于 `third_party/inspect_ai/extensions/agent_evaluator/`，根目录同名路径为符号链接。Langfuse 使用官方 Python SDK 5.0.2；本地服务通过官方 Compose 部署，历史 Cloud 导出仍为显式操作。旧 DeepEval Runner/G-Eval 路径已移除。Conversation Completeness 已通过可选依赖 `agent-evaluator[conversation]`（DeepEval 4.2.9）接入 Inspect Scorer，默认关闭、暂不进 Gate；见[使用说明](docs/conversation_completeness.md)。OpenAI Python SDK 仍由现有模型传输直接使用。

本地 `minimal-agent` 使用可编辑安装，其源码不会复制到本仓库。API 凭据仅由所选模型客户端从环境变量读取，不作为 CLI 参数，也不会写入报告字段。

## 冻结 JSONL 协议

每一行都是一个 `EvalCase`，所有协议模型均拒绝额外字段。加载时立即将 `execution`（`ExecutionSpec`，执行信息）与 `oracle`（`OracleSpec`，评分预期）分开。`MiniAgentAdapter` 和 `RuntimeFactory` 只接收 `ExecutionSpec`；预期答案、检查项、权重、目标状态及 `case_id` 不会进入模型请求或工具调用。`schemas/eval_case.schema.json` 由 Pydantic 模型生成，并通过测试检查。

`datasets/fixtures` 中的数据仅是框架自测使用的脚本化示例，不是正式的 mini-agent Benchmark。脚本响应通过 Python 工厂注入，不根据 Oracle 值反向生成。

新冻结数据集在 Manifest 中绑定可移植的 Capability Bundle。能力包包含冻结时使用的精确 Agent、模块、意图、工具和 JSON Schema 契约。Evaluator 通过 mini-agent Provider Adapter 从 `agent.json` 加载当前快照协议，同时保留对历史 `bundle_manifest.json` 的兼容。在创建模型客户端前，会校验引用快照的 Hash、防止路径越出能力包目录，并检查与当前 Provider 的兼容性。没有 Tool 引用的能力包无需空的 `tools/` 目录。Evaluator 不会静默替换为 Agent 工作区中的当前文件。没有能力包的旧数据集，必须显式使用 `--capability-bundle` 指定绑定。

新冻结 Manifest 还声明 `execution_profiles`。每个 Profile 是有名称、已冻结的案例可用工具列表，列出的工具都必须存在于同一 Capability Bundle 中。Evaluator 不会根据工具名称、读写类别、本地文件或 AgentSnapshot 推导 Profile。缺少该字段的历史 Manifest，仅在所选案例全部属于 `module` 时仍可执行，此时引用的 Profile 名称按空工具集处理。历史 `link` 或 `end_to_end` 数据缺少冻结 Profile 时，会报 `EXECUTION_PROFILE_REQUIRED`。

仓库中已纳入版本管理的模块级基准包括：

- `datasets/mini_agent/module_query_user_intent_v1_6.jsonl`：42 个 Case；
- `datasets/mini_agent/module_query_user_intent_v2_0.jsonl`：42 个 Case，使用快照协议 3.0；
- `datasets/mini_agent/module_query_gift_intent_v1_0.jsonl`：23 个 Case；
- 对应的 Manifest、覆盖报告和冻结 Capability Bundle。

旧版本仍可加载和审计。如果旧能力包与当前 `minimal-agent` 契约不一致，实际运行会在预检阶段主动失败，避免将过期基准契约的结果当作当前 Agent 的质量结论。

## 命令行 CLI

```bash
# 推荐的契约驱动入口。
python -m eval_framework.cli validate --suite suites/example/suite.json
python -m eval_framework.cli run --suite suites/example/suite.json \
  --output-dir artifacts

# 已弃用的兼容入口，会转换为内存中的 Suite。
python -m eval_framework.cli validate --dataset datasets/cases.jsonl
python -m eval_framework.cli run --provider mini_agent \
  --dataset /path/to/currently-bound-frozen-dataset.jsonl \
  --output-dir artifacts --trials 3

# 派生命令不会修改已保存的 results.json。
python -m eval_framework.cli analyze --run-dir artifacts/eval_run_...
python -m eval_framework.cli compare \
  --baseline artifacts/baseline/eval_run_... \
  --candidate artifacts/candidate/eval_run_... \
  --output-dir artifacts/comparison
python -m eval_framework.cli gate \
  --candidate artifacts/candidate/eval_run_... \
  --comparison artifacts/comparison \
  --policy policies/release_gate.example.json \
  --output-dir artifacts/gate
```

`run` 是实际执行 `agent_benchmark` 的入口，会为每个案例创建新的模型客户端。`MODEL_PROVIDER` 支持 `openai`（默认）或 `deepseek`，需配置对应的 `OPENAI_*` 或 `DEEPSEEK_*` 环境变量。可重复指定的过滤参数包括 `--scope`、`--task-id`、`--label` 和 `--case-id`。

Agent 断言失败时，CLI 仍返回退出码 0；无效数据或框架初始化失败不属于这种情况。结构化预检失败会写入 `invalid_run.json` 和最简 `report.md`，返回退出码 2，不生成 Case 结果，也不报告 Agent 通过率。`--capability-bundle` 仅用于显式覆盖旧版绑定；新数据集从 Manifest 解析能力包相对路径。

`--suite` 不能与旧版数据集、Provider、过滤或 Judge 参数混用。Provider、数据和过滤应写进 Suite；Judge Profile 尚未迁移，启用 Judge 仍需下面的兼容入口或显式 Python API。旧参数在兼容期内仍可使用，但会产生弃用警告。

使用兼容入口启用语义 Judge 时，添加 `--judge-config src/eval_framework/judge_rubrics/semantic_response_v1.json`，并配置独立的 Judge 环境变量：

```bash
export DEEPSEEK_JUDGE_API_KEY=...
export DEEPSEEK_JUDGE_MODEL=deepseek-flash
# 可选，默认值为 https://api.deepseek.com。
export DEEPSEEK_JUDGE_BASE_URL=https://api.deepseek.com
```

Judge 不会回退使用 Agent 模型的 `DEEPSEEK_*` 环境变量。其 Rubric、Prompt、输出 Schema、模型、重试与超时设置、Rubric Hash，以及 Inspect 后端/版本/适配语义身份会作为比较指纹保存，但凭据不会保存。历史 Judge 与新后端的结果不能直接比较，需重新运行基线。真实 Judge 冒烟测试需显式设置 `RUN_DEEPSEEK_JUDGE_SMOKE=1`。

每个语义维度调用一次 Inspect 原生 Model Grading，沿用业务 Rubric 和共享超时预算。G-Eval 与新原生评分的分布不视为等价；切换后需要重新运行基线并校准阈值。旧 DeepEval 客户端、导入别名、指标桥和 TestCase 转换均已删除，不保留备用生产路径。详见 [职责与迁移清单](docs/langfuse.md)。

退出码约定如下：`compare` 在比较有效时返回 0，在比较或输入无效时返回 2；`gate` 在 PASS 时返回 0，输入或比较无效时返回 2，FAIL 时返回 4，REVIEW_REQUIRED 时返回 5。`run` 中普通的 Agent 质量失败不会被伪装成评测器执行错误。

## Python API

```python
from eval_framework import (
    ContractStore,
    PluginCatalog,
    ProviderRegistry,
    RunConfig,
    compile_suite,
    execute_compiled_suite,
    load_suite_definition,
    analyze_run,
    compare_runs,
    evaluate_gate,
    load_dataset,
    load_run_result,
    run_provider_evaluation,
    write_report,
)
from eval_framework.providers.mini_agent import MiniAgentProviderFactory

dataset = load_dataset("cases.jsonl")
registry = ProviderRegistry()
registry.register("mini_agent", MiniAgentProviderFactory())
provider = registry.create(
    "mini_agent",
    dataset=dataset,
    model_client_factory=model_client_factory,
)
result = run_provider_evaluation(dataset, RunConfig(), provider)
paths = write_report(result, "artifacts", provider.capabilities)
```

新入口的使用顺序：在应用组装入口构建 `PluginCatalog`，调用 `load_suite_definition()`，再使用具有根目录边界的 `ContractStore` 调用 `compile_suite()`，最后执行 `execute_compiled_suite()`。原有 Python API 在迁移期内继续可用。

要在不修改 Runner 的情况下接入新 Agent 或数据集格式：

1. 实现 `ProviderFactory` 或 `DatasetLoaderPlugin` 协议。
2. 提供严格定义的 `PluginDescriptor`，包含配置 Schema、支持的契约版本及实现指纹。
3. 添加引用精确插件 ID 和版本的 Suite。
4. 增加协议一致性、预检失败及离线执行测试。
5. 在应用组装入口显式注册可信实现。

当前基础阶段完成的是 Loader/Provider 选择及来源追溯的迁移。Judge/Trace Pipeline 插件，以及声明式 Assertion/Report/Gate 策略属于后续两个阶段；在迁移完成前，Judge CLI 桥接保持独立，其客户端已切换为 Inspect Model Grading。

mini-agent 的模型客户端工厂签名为 `(ExecutionSpec) -> minimal_agent.runtime.model_client.ModelClient`。每个案例都会创建新的工厂返回对象、Agent、通用工具注册表和会话 ID。精简原生运行时不内置 Mock 工具、SQLite 存储、故障注入或确认状态；这些能力必须由显式配置的 Provider 提供，不能根据历史 Profile 推断。

可选的 `gift_sqlite_v1` Provider 环境提供 Trial 独立的 SQLite 礼物账本及状态读取，但不会为 Agent 补上确认处理能力，详见下方状态型示例。工厂有意保持不接触 Oracle。

`run_evaluation(..., model_client_factory)` 暂时作为已弃用的兼容封装保留；新接入应直接提供 `EvaluationProvider`。注册第二个 Provider 无需修改 CLI、Runner、评分或报告逻辑。注册必须在应用组装入口显式进行，本阶段不包含动态发现或插件扫描。所选注册 ID 必须同时匹配数据集中的 Provider 绑定及工厂返回的 Provider；不匹配时会在创建模型客户端前失败。

## 断言与评分

模块级断言：`intent_envelope_schema_valid`、`intent_parameters_schema_valid`、`intent_match`、`status_match`、`next_action_match`、`params_match`、`missing_params_match`。旧名称 `output_schema_valid` 仍作为兼容别名，为已冻结数据集提供仅针对外层结构的校验。

链路级断言：`tool_called`、`tool_not_called`、`tool_call_count`、`tool_args_match`、`tool_result_consistent`、`no_state_change`。

端到端断言：`final_state_match`、`no_duplicate_side_effect`、`confirmation_requested`、`confirmation_accepted`、`no_write_before_confirmation`、`response_consistent`。

得分按通过的适用断言权重除以适用断言总权重计算，并按百分制四舍五入保留两位小数。没有适用检查项时，不生成分数，结论为 `INCONCLUSIVE`，不会生成虚假的 100 分。关键项失败会强制判定为 `FAIL`，其余情况按显式阈值判断。报告将框架执行完成率与 Agent 案例通过率分开呈现。

## 输出产物

Runner 在执行 Agent 前创建 `eval_run_*` 目录；`write_report` 补充以下文件：人读报告 `report.md`、机器可读摘要 `summary.json`、可重新加载的 `results.json`、流式记录 `results.jsonl`、失败汇总 `failures.json`、`run_manifest.json`、`stability.json`、`cases/<case_id>/<trial_id>.json` 及逐 Trial 证据。

Judge 结果写入 `judge/<case_id>/<trial_id>.json`，标准化 Trace 分析写入 `trace_analysis/<case_id>/<trial_id>.json`。实际输出、断言及可选系统状态保存在 `evidence/<case_id>/<trial_id>/`。独立业务 Trace 使用 Inspect 原生接口保存至 `evidence/<trace_id>/trace.inspect.json`，事件与采集状态同快照存储，同目录保留业务 `association.json`。旧 JSONL 仅只读兼容，不再生成。旧版内嵌 Trace 保留 Case/Trial 目录结构。

报告复制到其他位置时保留原始证据字节。SDK 脱敏作用于独立证据通道，返回业务数据的隐私策略由调用方负责。

SDK 安装、可选 Provider 接口与证据状态语义见[本地独立证据通道](docs/TRACE_PHASE1.md)。无效评测 Trial 保留 Agent 执行状态，但没有分数，也不能通过发布门禁。必需证据缺失时，相关断言属于适用但无法判定；已被独立证据证明的失败仍保持失败。断言语义版本为 `inspect-assertions-v1`，覆盖逐轮检查、状态缺失处理和确认前各轮的检查。

`inspect/*.eval` 是 Inspect 原生运行记录；`results.json` 是不可变的领域审计结果。两者由同一次评测生成。`evaluation_backend` 记录引擎版本和适配策略，`native_artifacts` 保存原生文件相对路径。`analyze` 写入 `analysis.json` 和 Trace 文件；`compare` 写入 `comparison.json`/`.md`；`gate` 写入 `gate.json`/`.md`。JSON 是稳定的接口格式。加载历史第一阶段结果时，会为缺失的 Judge、Trace、稳定性、标签和 Trial 字段补默认值；人工复核改从 Langfuse 导入，与导出回执的结果 Hash 绑定；历史本地复核文件仅用于审计。

运行结果和 `run_manifest.json` 包含 `compiled_suite_sha256`、展开的 Suite 快照、插件/契约指纹、`provider_id`、`provider_version`、`agent_version` 和 `capability_bundle_sha256`，使报告能标识 Agent 适配器及评分所用的冻结契约。仅含 `mini_agent_version` 的旧 `results.json` 在加载时迁移；新产物不再写入这个 Provider 专属字段。报告中的业务标签来自冻结的展示契约，缺失时回退到稳定的原始字段名。

报告结构、结论规则、指标定义和证据关联要求见[评测报告规范](docs/evaluation_report_spec.md)。

## 轻量评测工作流

当前验收范围是让一个代表性任务经过执行、取证、判定、报告和回归复核全过程。以下约定基于现有 Provider 与产物接口。

### 可运行的状态型示例

```bash
.venv/bin/python examples/stateful_gift.py --output-dir artifacts
```

此离线自测会创建新目录，包含可移植 Suite、冻结测试夹具契约、四个 Case 和评测报告。它使用真实 mini-agent 运行时与脚本化模型响应，每个 Case 执行两次：

| Case | 验证内容 | 当前预期结论 |
| --- | --- | --- |
| GIFT-GRANT | 澄清、确认后检查实际账本状态 | FAIL：原生 Agent 停留在 NEED_CONFIRMATION |
| GIFT-CANCEL | 提供取消输入，观察 REJECTED 且没有写入 | 在脚本化拒绝响应下为 PASS |
| GIFT-CORRECTION | 逐轮检查修改后的数量与预期最终发放结果 | FAIL：原生 Agent 仍无法放行写操作 |
| GIFT-LINK | 一次调用请求确认后停止，状态保持不变 | PASS |

这些结果验证的是评测器行为，不是真实模型质量或跨轮记忆。Agent 当前没有确认接受状态转换或会话记忆；Evaluator 不会补入前序参数，也不会合成确认接受事件。示例中的失败通过保存的状态证据暴露这些限制。

编写 Suite 时，需显式启用该环境：

```json
"provider": {
  "plugin_id": "mini_agent_provider_v1",
  "version": "1.0.0",
  "config": {"environment": "gift_sqlite_v1"}
}
```

与示例一致，应将 Suite 绑定到使用该环境工具注册表导出的 Capability Bundle，不会静默替换任意历史工具契约。Python 接入可向 `MiniAgentProvider.from_dataset` 传入 `environment="gift_sqlite_v1"`。

环境以空账本（`empty-backpack-v1`）初始化，支持 `add_gift_to_backpack`，记录每次调用的插入操作，不抑制重复写入；清理时删除并核验自身临时目录。快照来自 SQLite 查询，而不是工具成功消息。默认环境保持不变，故障注入尚未实现。

mini-agent 的执行边界明确如下：`module` 调用一次纯意图入口；`link` 调用一次 `Agent.run`，包含其有步数上限的工具循环；`end_to_end` 仅在 NEED_CLARIFICATION 或 NEED_CONFIRMATION 后继续输入下一个已声明的 `user_responses`。到达终态或输入耗尽时停止。带有后续输入的 module/link 案例会在执行前被拒绝。不支持在任意工具循环中间设置截断点。

使用 `turns_match` 断言精确检查轮次数及逐轮行为：

```json
{
  "name": "turns_match", "weight": 1, "critical": true,
  "config": {"turns": [
    {"status": "NEED_CONFIRMATION", "parameters": {"num": 2},
     "tool_calls": [], "state": {"grant_count": 0}},
    {"status": "SUCCESS", "parameters": {"num": 3},
     "tool_calls": [{"name": "add_gift_to_backpack", "arguments": {"num": 3}}],
     "state": {"grant_count": 1, "total_quantity": 3}}
  ]}
}
```

状态、工具顺序和调用次数要求精确匹配；参数、工具入参及状态对象按声明的子集匹配。启用独立通道后，可选的工具 `status` 检查需要终态证据。状态缺失或工具证据不完整时无法判定，已独立观察到的不匹配仍判 FAIL。`before_snapshot`、`turn_snapshots` 和 `system_snapshot` 保存在 Case 结果中。状态读取失败属于 Evaluator 错误，但仍会触发清理。

### 环境约定

每个接入方应在 Suite 或 Provider 配置旁记录以下约定：

| 项目 | 最低要求 |
| --- | --- |
| 工具模式 | 说明工具是模拟实现，还是连接真实测试环境。 |
| 初始数据 | 标识测试夹具及版本；在 `create_runtime` 或 `create_observed_runtime` 中，为每个 Trial 准备新会话及限定范围的数据。 |
| 状态证据 | 对有状态变更的任务，在执行前、每个相关轮次后及完成时读取状态，通过 `AdapterOutput.before_snapshot`、`turn_snapshots` 和 `snapshot` 返回。 |
| 清理 | 在 `cleanup` 中释放 Trial 自有资源，核验删除或重置结果，失败时抛出异常。如果初始化在返回运行时前失败，Provider 必须自行释放已部分创建的资源。 |
| 限制 | 声明支持的工具、步数上限、超时行为及故障注入能力。不支持的环境功能必须在预检时拒绝。 |

Runner 记录清理结果，但 `CLEANED` 只表示 Provider 的清理调用正常返回；实际重置核验由 Provider 负责。仅创建新的 Python 运行时并不能隔离共享外部数据库。默认 mini-agent 接入不会自动提供业务测试夹具或数据库重置；上面的可选环境提供本地夹具。超时限制见本文末尾。

以礼物发放为例，接入方可准备空测试背包、观察确认过程、查询最终发放数量，并清理该 Trial 的数据。规则将观测到的状态和事件与 Oracle 比较。必需状态或事件证据缺失时必须保留无法判定，独立观察到的违规仍是失败。较早的三级范围夹具使用脚本化状态；新的状态型示例读取真实本地 SQLite 账本，同时保留原生 Agent 当前的确认能力限制。

### 离线评分自检

在仓库根目录运行现有的小型验收测试集：

```bash
.venv/bin/python -m pytest -q \
  tests/test_multiturn_execution.py \
  tests/test_stateful_environment.py \
  tests/test_stateful_example.py \
  tests/test_execution_scoring.py::test_module_link_e2e_all_run_offline_and_are_isolated \
  tests/test_execution_scoring.py::test_wrong_module_answer_is_stable_fail \
  tests/test_evidence_boundaries.py::test_tampered_association_cannot_prove_a_violation \
  tests/test_evidence_boundaries.py::test_cleanup_failure_preserves_execution_and_observed_violation \
  tests/test_judge.py \
  tests/test_adjudication.py \
  tests/test_phase2_end_to_end.py
```

这些测试检查已知 PASS/FAIL 输出、证据无法关联到 Trial 时的 INCONCLUSIVE、清理失败报告、Judge 阈值与异常处理、追加式人工复核，以及报告、比较和 Gate 产物。Judge 测试使用脚本响应，验证评分集成逻辑，不验证真实 Judge 的语义准确性。在业务任务中依赖真实 Judge 前，应根据所选 Rubric 人工检查少量明确正确、明确错误及模糊答案，并将分歧保存在本次运行的复核记录中。

### 从失败案例到回归集的人工交接

1. 从 `failures.json` 和 `report.md` 开始，查看对应的 `cases/<case_id>/<trial_id>.json` 及证据引用。预检被拒绝时应查看 `invalid_run.json`，不要直接当作 Agent 失败。
2. 判断问题属于 Agent 行为、环境/采集失败，还是错误的 Oracle/Judge。使用现有命令追加复核记录，示例目录与标识需替换为实际运行值：

   ```bash
   .venv/bin/python -m eval_framework.cli export-langfuse \
     --run-dir artifacts/eval_run_EXAMPLE
   # 在 Langfuse Annotation 中完成复核，然后读取结构化快照：
   .venv/bin/python -m eval_framework.cli import-reviews \
     --run-dir artifacts/eval_run_EXAMPLE
   ```

   预期有争议时使用 `CONTRACT_DISPUTE`，证据无法支撑判断时使用 `INCONCLUSIVE`。复核保留自动结果，不会自动改变发布门禁结论。
3. 向 Builder 提交经人工复核的材料，包括来源运行、Case/Trial ID、数据集版本、证据引用、复核结论、预期行为及简短复现说明。共享前移除敏感业务数据。这是人工交接约定，不是新增的 Builder API。
4. Builder 审核并将接受的案例冻结到新数据集版本，保留原运行和原数据集。在比较前，基线与候选都必须使用同一份新冻结数据集评测；不同数据集版本的分数不能作为回归比较。

已有失败案例可以继续作为回归案例，无需重复新增。环境、证据及评分缺陷应先在各自层修复；只有经确认的业务场景才需要新增 Builder 案例。

## 测试与静态检查

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check src tests scripts
```

默认测试均离线执行。付费模型冒烟测试分别通过 `RUN_OPENAI_EVAL_SMOKE=1` 或 `RUN_DEEPSEEK_JUDGE_SMOKE=1` 显式启用。

本阶段有意不增加 CI 工作流。校验、比较和 Gate 命令是本地基础能力，后续 CI 可以调用这些命令完成集成。

## 当前超时机制的限制

mini-agent 的公开调用是同步的，没有安全取消接口。因此 Evaluator 测量案例耗时，并将已经返回但超出预算的调用标记为 `OUTER_TIMEOUT`。它不会启动无法终止的后台线程，也不宣称支持抢占式强制取消。进程隔离保留到后续执行控制阶段实现。
