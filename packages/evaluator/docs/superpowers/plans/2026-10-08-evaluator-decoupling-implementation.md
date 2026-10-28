# Evaluator 渐进式解耦 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将执行 Profile、Provider 接入和业务诊断从 Evaluator 核心硬编码中解耦，同时保持历史模块评测集和旧结果可读。

**Architecture:** 冻结 Manifest 成为 Execution Profile 的唯一正式来源，历史 module-only 数据集通过空 Profile 兼容；组合根用显式 `ProviderRegistry` 注册 Provider；`DiagnosticRegistry` 按预期 Intent 分派业务诊断。Evaluator 先完成兼容读取和注册表，再由 Builder 写出新协议，最后执行跨项目离线回归。

**Tech Stack:** Python 3.11、Pydantic 2、JSON Schema Draft 2020-12、Pytest、Ruff、JSONL/JSON Manifest

**Spec:** `docs/superpowers/specs/2026-10-08-evaluator-decoupling-design.md`

## Global Constraints

- 不修改已经冻结的 JSONL 内容和历史 Manifest。
- 不修改 mini_agent 生产 Agent 核心，也不把评测 Profile 写入 AgentSnapshot。
- 不引入动态插件扫描、网络发现、隐式 Provider 加载或隐式工具推断。
- 新 Manifest 必须显式携带 `execution_profiles`；旧 Manifest 仅在筛选后的 Case 全部为 `module` 时兼容为空 Profile。
- 所有预检失败必须发生在模型客户端创建和外部 API 调用之前；整个实施与验证过程不得调用付费 API。
- 确定性断言、评分和报告结论语义保持不变。
- 当前仓库 Git `HEAD` 损坏；除非用户另行修复或明确授权修复，否则不得改动 Git 元数据。实施时保留每个任务的验证节点、跳过不可执行的提交命令，并在交付说明中记录原因。

## File Structure

### agent_evaluator

- `src/eval_framework/errors.py`：通用、带稳定错误代码的预检异常。
- `src/eval_framework/schemas.py`：Execution Profile、DatasetBundle 与通用 `agent_version` 协议。
- `src/eval_framework/dataset_loader.py`：Manifest Profile 解析及历史 module-only 兼容。
- `src/eval_framework/dataset_validator.py`：Case、Profile、工具和故障模式的联合校验。
- `src/eval_framework/tool_catalog.py`：仅根据已解析 Profile 和冻结工具合同构建目录。
- `src/eval_framework/runtime_factory.py`：接收已解析工具集合，不保存 mini_agent Profile 常量。
- `src/eval_framework/provider.py`：Provider/Factory 协议；继续兼容导出预检异常。
- `src/eval_framework/provider_registry.py`：显式 Provider 注册与创建。
- `src/eval_framework/composition.py`：默认组合根，唯一负责注册内置 mini_agent Provider。
- `src/eval_framework/diagnostics.py`：通用诊断与 `DiagnosticRegistry`。
- `src/eval_framework/providers/mini_agent/provider.py`：mini_agent Factory、Profile 注入和诊断注册。
- `src/eval_framework/providers/mini_agent/diagnostics.py`：QueryUser 业务规则，不进入核心。
- `src/eval_framework/runner.py`、`cli.py`、`reporting.py`：消费通用注册表和版本字段。
- `schemas/eval_case.schema.json`、`README.md`、相关 `tests/`：协议快照、用法和回归测试。

### agent_dataset_builder

- `src/dataset_builder/suite_config.py`：Suite 的 Execution Profile 配置模型。
- `src/dataset_builder/schemas.py`：GenerationRequest 中的 Profile 快照。
- `src/dataset_builder/pipeline.py`：prepare、generation manifest 和验证生命周期透传。
- `src/dataset_builder/freezing.py`：冻结 Manifest 写入 Profile，并校验工具引用。
- `schemas/suite_definition.schema.json`：Suite 配置 Schema 快照。
- `suites/*/suite.json`：现有模块 Suite 显式声明空工具 Profile。
- `tests/test_suite_config.py`、`tests/test_lifecycle.py`、`tests/test_capability_snapshots.py`：配置、透传和冻结测试。

## Review Focus

- Manifest 声明空对象、空名称、重复工具或未知工具时，必须返回 `EXECUTION_PROFILE_INVALID`，且不得创建模型客户端（Task 1、Task 3）。
- 筛选后只有 module Case、但原始数据集还含 link/e2e 时，应按筛选结果走历史兼容；筛选结果含 link/e2e 时返回 `EXECUTION_PROFILE_REQUIRED`（Task 1）。
- CLI 参数 Provider、Manifest `provider_id` 与注册表 Provider 不一致时，不得回退到 mini_agent，必须返回稳定的 `UNKNOWN_PROVIDER` 或合同不匹配错误（Task 4）。
- 无预期 Intent 或实际输出为空时，诊断路由必须安全回退到通用诊断，不得产生异常或误用其他 Intent 规则（Task 5）。
- 旧结果同时包含 `mini_agent_version` 和 `agent_version` 且值冲突时必须拒绝读取；相同时允许迁移（Task 6）。

---

### Task 1: Evaluator 加载并规范化 Execution Profile

**Files:**
- Create: `src/eval_framework/errors.py`
- Modify: `src/eval_framework/schemas.py`
- Modify: `src/eval_framework/dataset_loader.py`
- Modify: `src/eval_framework/provider.py`
- Test: `tests/test_protocol_loader_validator.py`

**Interfaces:**
- Produces: `EvaluationPreflightError(code: str, message: str, *, evidence_path: str | None = None, evidence_refs: list[str] | None = None)` in `errors.py`，并从 `provider.py` 兼容导出。
- Produces: `ExecutionProfile(allowed_tools: list[str])`；`DatasetBundle.execution_profiles: dict[str, ExecutionProfile]`；`DatasetBundle.execution_profiles_source: Literal["manifest", "legacy_module"]`。
- Produces: `load_dataset(path, filters)` 返回已根据筛选后 Case 解析或兼容补齐 Profile 的 `DatasetBundle`。

- [ ] **Step 1: 写 Manifest Profile 与历史兼容的失败测试**

在 `tests/test_protocol_loader_validator.py` 增加：

- `test_loads_manifest_execution_profiles`
- `test_legacy_module_subset_synthesizes_empty_profiles`
- `test_legacy_link_or_e2e_requires_execution_profiles`
- `test_invalid_execution_profile_shape_has_stable_error_code`
- `test_execution_profile_rejects_blank_name_and_duplicate_tools`

关键断言：正式 Profile 保留声明顺序；兼容 Profile 覆盖筛选后 Case 引用的所有名称且 `allowed_tools == []`；旧 link/e2e 抛出 `EvaluationPreflightError` 且 `code == "EXECUTION_PROFILE_REQUIRED"`；结构错误使用 `EXECUTION_PROFILE_INVALID`。

- [ ] **Step 2: 运行新测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_protocol_loader_validator.py -q`

Expected: FAIL，原因是协议字段、错误类型和兼容解析尚不存在。

- [ ] **Step 3: 增加通用错误与 Profile 协议**

在 `errors.py` 移入 `EvaluationPreflightError`；在 `schemas.py` 增加 `ExecutionProfile` 及唯一性校验，并为 `DatasetBundle` 增加两个 Profile 字段。`provider.py` 从 `errors.py` 导入并重新导出，保持现有调用方不变。

- [ ] **Step 4: 实现 `_execution_profiles(manifest, selected_cases, manifest_path) -> tuple[dict[str, ExecutionProfile], Literal["manifest", "legacy_module"]]`**

在 `dataset_loader.py` 中只读取 Manifest 明确声明的 Profile；缺失时仅对筛选后的纯 module Case按其 `execution.tool_profile` 合成空集合。错误携带 Manifest 证据路径，不读取工具名含义。

- [ ] **Step 5: 运行加载器测试**

Run: `.venv/bin/python -m pytest tests/test_protocol_loader_validator.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/eval_framework/errors.py src/eval_framework/provider.py src/eval_framework/schemas.py src/eval_framework/dataset_loader.py tests/test_protocol_loader_validator.py
git commit -m "feat: load manifest execution profiles"
```

### Task 2: Builder 冻结 Execution Profile

**Files:**
- Modify: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/src/dataset_builder/suite_config.py`
- Modify: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/src/dataset_builder/schemas.py`
- Modify: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/src/dataset_builder/pipeline.py`
- Modify: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/src/dataset_builder/freezing.py`
- Modify: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/schemas/suite_definition.schema.json`
- Modify: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/suites/mini_agent_intent_v1/suite.json`
- Modify: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/suites/mini_agent_query_user_intent_v1/suite.json`
- Modify: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/suites/mini_agent_query_gift_intent_v1/suite.json`
- Test: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/tests/test_suite_config.py`
- Test: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/tests/test_lifecycle.py`

**Interfaces:**
- Consumes: Task 1 的 Manifest `execution_profiles` 结构。
- Produces: `ExecutionProfileConfig(allowed_tools: list[str])`；`SuiteConfig.execution_profiles: dict[str, ExecutionProfileConfig]`；`GenerationRequest.execution_profiles: dict[str, ExecutionProfileConfig]`。
- Produces: 冻结 Manifest 的 `execution_profiles`，内容必须等于 Suite 明确声明并经 GenerationRequest/manifest 绑定的值。

- [ ] **Step 1: 写 Suite 配置校验测试**

在 `test_suite_config.py` 增加 `test_execution_profiles_are_explicit_strict_and_unique`，覆盖合法空工具 Profile、空 Profile 名、重复工具和未知字段；断言三份已登记 Suite 的 `compilation.execution.tool_profile` 都存在于 `execution_profiles`。

- [ ] **Step 2: 写生命周期透传与冻结测试**

在 `test_lifecycle.py` 增加：

- `test_prepare_and_generation_manifest_preserve_execution_profiles`
- `test_freeze_writes_execution_profiles_verbatim`
- `test_freeze_rejects_profile_tool_not_in_selected_bundle`
- `test_freeze_rejects_generation_profile_drift`

断言 Profile 从 Suite 到 GenerationRequest、generation manifest 和 frozen manifest 全程一致；引用未选择 Tool Snapshot 的名称时在复制最终 JSONL 前失败。

- [ ] **Step 3: 运行目标测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_suite_config.py tests/test_lifecycle.py -q`

Working directory: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder`

Expected: FAIL，原因是 Suite/GenerationRequest 尚无 Profile 字段。

- [ ] **Step 4: 增加 Suite 与 GenerationRequest 协议并重新生成 Schema**

在 `suite_config.py` 增加 `ExecutionProfileConfig` 和顶层 `execution_profiles` 必填字段；在 `schemas.py` 为 GenerationRequest 增加同名字段。执行项目既有 Schema 生成入口更新 `schemas/suite_definition.schema.json`，不得手工编辑生成 JSON。

- [ ] **Step 5: 透传并校验 Profile**

`prepare_generation()` 将 Suite Profile 固化进 GenerationRequest；`_write_generation_manifest()` 写出相同内容；验证阶段检查 request/manifest 一致；`freeze()` 仅从经验证的 generation metadata 写入 frozen manifest，并用所选 Capability Bundle 的 Tool Snapshot 名称校验所有 `allowed_tools`。

- [ ] **Step 6: 更新现有 Suite**

为现有 module Suite 明确添加其 Case 引用的 Profile，`allowed_tools` 使用空列表；不修改现有 JSONL、版本号或能力选择。

- [ ] **Step 7: 运行 Builder 测试与 Ruff**

Run: `.venv/bin/python -m pytest -q`

Run: `.venv/bin/python -m ruff check .`

Working directory: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder`

Expected: 全部离线测试 PASS，Ruff 无错误。

- [ ] **Step 8: 提交**

```bash
git add src/dataset_builder/suite_config.py src/dataset_builder/schemas.py src/dataset_builder/pipeline.py src/dataset_builder/freezing.py schemas/suite_definition.schema.json suites/*/suite.json tests/test_suite_config.py tests/test_lifecycle.py
git commit -m "feat: freeze execution profiles with datasets"
```

### Task 3: ToolCatalog 与 Native Runtime 移除固定 Profile

**Files:**
- Modify: `src/eval_framework/tool_catalog.py`
- Modify: `src/eval_framework/runtime_factory.py`
- Modify: `src/eval_framework/providers/mini_agent/provider.py`
- Test: `tests/test_tool_catalog.py`
- Test: `tests/test_protocol_loader_validator.py`
- Test: `tests/test_provider_architecture.py`

**Interfaces:**
- Consumes: `DatasetBundle.execution_profiles` from Task 1。
- Produces: `ToolCatalog.from_registry(registry, *, profiles: Mapping[str, ExecutionProfile]) -> ToolCatalog`。
- Produces: `RuntimeFactory.create(execution, *, session_id: str, allowed_tools: frozenset[str]) -> Runtime`；默认 Native ToolRegistry 只接受空工具集合，非空但无显式处理器时在初始化前失败。

- [ ] **Step 1: 写目录联合校验测试**

覆盖 Profile 引用未知工具、Case `allowed_tools` 越权、非法 fault mode，以及无 Profile 的 link/e2e；断言对应错误分别为 `EXECUTION_PROFILE_INVALID` 或 `DATASET_VALIDATION_FAILED`，模型客户端工厂计数保持 `0`。

- [ ] **Step 2: 写 Runtime 去硬编码测试**

在 `test_provider_architecture.py` 增加 AST/行为测试：`runtime_factory.py` 不存在 `MINI_AGENT_TOOL_PROFILES`、`legacy`、`shadow_read`、`shadow_full`；模块兼容 Profile 可以创建空 Registry；非空 Profile 缺少 native handler 时明确初始化失败。

- [ ] **Step 3: 运行目标测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py tests/test_protocol_loader_validator.py tests/test_provider_architecture.py -q`

Expected: FAIL，显示 Provider 仍从常量构建 Profile。

- [ ] **Step 4: 让 ToolCatalog 只消费 Dataset Profile**

删除 Tool Catalog Snapshot 内部 `profiles` 作为执行 Profile 来源的路径；工具合同仍来自冻结 Tool Snapshot。Profile 的结构/未知工具错误转换为 `EvaluationPreflightError("EXECUTION_PROFILE_INVALID", ...)`，Case 级越权和故障模式继续由 `validate_dataset()` 汇总为 `DATASET_VALIDATION_FAILED`。

- [ ] **Step 5: 移除 RuntimeFactory 常量与名称判断**

`MiniAgentProvider.from_dataset()` 把 `dataset.execution_profiles` 注入 ToolCatalog；`create_runtime()` 解析 Profile 和 Case 子集后把 `allowed_tools` 传给 RuntimeFactory。RuntimeFactory 不识别任何 Profile 名称；当前空集合构建空 `ToolRegistry`，非空集合必须由显式 registry factory 提供处理器。

- [ ] **Step 6: 运行目标测试**

Run: `.venv/bin/python -m pytest tests/test_tool_catalog.py tests/test_protocol_loader_validator.py tests/test_provider_architecture.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/eval_framework/tool_catalog.py src/eval_framework/runtime_factory.py src/eval_framework/providers/mini_agent/provider.py tests/test_tool_catalog.py tests/test_protocol_loader_validator.py tests/test_provider_architecture.py
git commit -m "refactor: derive runtime profiles from manifests"
```

### Task 4: ProviderRegistry 驱动 CLI 和 Python 接入

**Files:**
- Create: `src/eval_framework/provider_registry.py`
- Create: `src/eval_framework/composition.py`
- Modify: `src/eval_framework/provider.py`
- Modify: `src/eval_framework/providers/mini_agent/provider.py`
- Modify: `src/eval_framework/providers/mini_agent/__init__.py`
- Modify: `src/eval_framework/cli.py`
- Modify: `src/eval_framework/__init__.py`
- Test: `tests/test_provider_architecture.py`
- Test: `tests/test_reporting_cli.py`

**Interfaces:**
- Produces: `ProviderFactory.create(dataset: DatasetBundle, model_client_factory: ModelClientFactory, *, bundle_override: str | Path | None = None, verify_current: bool = True) -> EvaluationProvider`。
- Produces: `ProviderRegistry.register(provider_id: str, factory: ProviderFactory) -> None` 与 `ProviderRegistry.create(provider_id: str, **kwargs) -> EvaluationProvider`。
- Produces: `default_provider_registry() -> ProviderRegistry` in `composition.py`；`MiniAgentProviderFactory` in provider package。

- [ ] **Step 1: 写 ProviderRegistry 单元测试**

增加 `test_provider_registry_registers_second_provider_without_core_changes`、`test_provider_registry_rejects_duplicate_id`、`test_unknown_provider_has_stable_error`。Fake Factory 必须能被注册并创建，未知 ID 的 code 为 `UNKNOWN_PROVIDER`。

- [ ] **Step 2: 写 CLI 解耦测试**

断言 `cli.py` 不导入 `providers.mini_agent`、不比较字符串 `mini_agent`；通过 monkeypatch 默认注册表，`validate --provider fixture` 能执行；Manifest Provider 和 CLI Provider 不一致时不回退。

- [ ] **Step 3: 运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_provider_architecture.py tests/test_reporting_cli.py -q`

Expected: FAIL，原因是 CLI 仍有 mini_agent 条件分支。

- [ ] **Step 4: 实现显式注册表与 mini_agent Factory**

注册时拒绝空 ID 和重复 ID；创建时不进行动态导入。`MiniAgentProviderFactory.create()` 仅封装现有 `MiniAgentProvider.from_dataset()` 参数，不改变能力兼容行为。

- [ ] **Step 5: 迁移 CLI 到组合根**

CLI 只调用 `default_provider_registry().create(...)`；`composition.py` 是核心外唯一导入内置 Provider 的位置。确保 Provider 解析和能力/Profile 预检发生在 `_model_client_factory()` 真正创建客户端之前。

- [ ] **Step 6: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_provider_architecture.py tests/test_reporting_cli.py -q`

Expected: PASS。

- [ ] **Step 7: 提交**

```bash
git add src/eval_framework/provider_registry.py src/eval_framework/composition.py src/eval_framework/provider.py src/eval_framework/providers/mini_agent/provider.py src/eval_framework/providers/mini_agent/__init__.py src/eval_framework/cli.py src/eval_framework/__init__.py tests/test_provider_architecture.py tests/test_reporting_cli.py
git commit -m "feat: register evaluation providers explicitly"
```

### Task 5: DiagnosticRegistry 按 Intent 分派业务规则

**Files:**
- Modify: `src/eval_framework/diagnostics.py`
- Modify: `src/eval_framework/provider.py`
- Modify: `src/eval_framework/providers/mini_agent/provider.py`
- Modify: `src/eval_framework/runner.py`
- Test: `tests/test_diagnostics.py`
- Test: `tests/test_provider_architecture.py`

**Interfaces:**
- Produces: `DiagnosticRegistry.register(intent_id: str, rule: DiagnosticRule) -> None`。
- Produces: `DiagnosticRegistry.rules_for(case: EvalCase, assertions: Sequence[AssertionResult]) -> tuple[DiagnosticRule, ...]`，优先使用 `oracle.expected_module_output.intent`，缺失时读取 `intent_match.actual`。
- Changes: `EvaluationProvider.diagnostics: DiagnosticRegistry` 取代无路由的 `diagnostic_rules`。

- [ ] **Step 1: 写诊断路由测试**

覆盖一个 Intent 多规则、未注册 Intent 返回空 tuple、无预期 Intent 使用 `intent_match.actual`、预期和实际都未知时返回空，以及重复注册同一规则实例不重复执行。

- [ ] **Step 2: 写业务规则隔离测试**

断言 QueryUser 现有案例诊断代码与顺序不变；QueryGift 或测试 Intent 可注册专用规则而无需修改核心映射；`diagnostics.py` 不出现 `query_user`/`query_gift` 字符串。

- [ ] **Step 3: 运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py tests/test_provider_architecture.py -q`

Expected: FAIL，原因是 Provider 当前直接暴露无路由规则序列。

- [ ] **Step 4: 实现注册表并迁移 Runner**

保留 `build_diagnoses(..., rules=...)` 的通用聚合能力；Runner 改为传入 `provider.diagnostics.rules_for(case, assertions)`。mini_agent Provider 在构造时显式注册 `MiniAgentQueryUserDiagnosticRule` 到 `query_user`，不在核心加入业务分支。

- [ ] **Step 5: 运行诊断与执行回归**

Run: `.venv/bin/python -m pytest tests/test_diagnostics.py tests/test_execution_scoring.py tests/test_provider_architecture.py -q`

Expected: PASS，现有 QueryUser 诊断结果保持不变。

- [ ] **Step 6: 提交**

```bash
git add src/eval_framework/diagnostics.py src/eval_framework/provider.py src/eval_framework/providers/mini_agent/provider.py src/eval_framework/runner.py tests/test_diagnostics.py tests/test_provider_architecture.py
git commit -m "refactor: route diagnostics by intent"
```

### Task 6: 通用化 Agent 版本字段并兼容旧结果

**Files:**
- Modify: `src/eval_framework/schemas.py`
- Modify: `src/eval_framework/runner.py`
- Modify: `src/eval_framework/reporting.py`
- Test: `tests/test_reporting_cli.py`

**Interfaces:**
- Produces: `EvaluationRunResult.agent_version: str`。
- Compatibility: model `before` validator 将仅含 `mini_agent_version` 的旧数据迁移为 `agent_version`；两字段相同则接受并丢弃旧字段；两字段冲突则抛出 ValidationError。
- Output: `results.json` 和 `run_manifest.json` 只写 `agent_version`。

- [ ] **Step 1: 写版本迁移和写出测试**

增加：

- `test_legacy_mini_agent_version_migrates_to_agent_version`
- `test_equal_legacy_and_generic_versions_are_accepted`
- `test_conflicting_version_fields_are_rejected`
- `test_new_results_and_manifest_only_write_agent_version`

- [ ] **Step 2: 运行测试并确认失败**

Run: `.venv/bin/python -m pytest tests/test_reporting_cli.py -q`

Expected: FAIL，现有结果仍要求并写出 `mini_agent_version`。

- [ ] **Step 3: 实现 Pydantic 读取迁移**

将模型字段改为 `agent_version`；使用 `@model_validator(mode="before")` 处理旧 key，且在 `extra="forbid"` 校验前删除已接受的旧字段。Runner 从 `provider.provider_version` 填充新字段。

- [ ] **Step 4: 更新报告产物**

`_manifest()` 仅写 `agent_version`；Markdown 的“Agent 版本”展示不变。确认完整结果、单 Case 和摘要中不引入 Provider 专用字段。

- [ ] **Step 5: 运行报告测试**

Run: `.venv/bin/python -m pytest tests/test_reporting_cli.py -q`

Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add src/eval_framework/schemas.py src/eval_framework/runner.py src/eval_framework/reporting.py tests/test_reporting_cli.py
git commit -m "refactor: use generic agent version metadata"
```

### Task 7: 协议快照、文档和跨项目离线验收

**Files:**
- Modify: `schemas/eval_case.schema.json`
- Modify: `README.md`
- Modify: `docs/evaluation_report_spec.md` only if version-field examples require it
- Test: all Evaluator and Builder tests

**Interfaces:**
- Consumes: Tasks 1–6 的最终公共接口。
- Produces: 可复现的文档示例和完整离线验收记录；不改变评测结论或冻结数据。

- [ ] **Step 1: 更新生成型协议快照和 README**

通过现有 Pydantic Schema 生成方式更新 `schemas/eval_case.schema.json`；README 说明 Manifest `execution_profiles`、历史 module-only 兼容、Provider 显式注册、错误代码和 `agent_version` 迁移。

- [ ] **Step 2: 运行 Evaluator 全量离线测试与 Ruff**

Run: `.venv/bin/python -m pytest -q -m "not openai_eval_smoke"`

Run: `.venv/bin/python -m ruff check .`

Expected: 全部测试 PASS；付费 smoke 被排除；Ruff 无错误。

- [ ] **Step 3: 运行 Builder 全量离线测试与 Ruff**

Run: `.venv/bin/python -m pytest -q -m "not dataset_generation_smoke"`

Run: `.venv/bin/python -m ruff check .`

Working directory: `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder`

Expected: 全部测试 PASS；付费生成 smoke 被排除；Ruff 无错误。

- [ ] **Step 4: 预检现有两个 FROZEN 模块评测集**

Run: `.venv/bin/agent-evaluator validate --dataset datasets/mini_agent/module_query_user_intent_v1_6.jsonl --provider mini_agent`

Run: `.venv/bin/agent-evaluator validate --dataset datasets/mini_agent/module_query_gift_intent_v1_0.jsonl --provider mini_agent`

Expected: 两者 `valid: true`，Case 数分别为 42 和 23；走历史 module-only 空 Profile 兼容，不创建网络模型客户端。

- [ ] **Step 5: 增加并运行无网络离线回放回归**

在现有确定性客户端测试中加载 QueryUser v1.6 与 QueryGift v1.0，并用改造前已保存的结构化结果 fixture 回放模型输出；断言 Case 数、执行状态分布、断言和诊断结果一致。若仓库尚无完整回放 fixture，先从已有正式 `results.json` 提取最小的 `module_output` 与预期统计快照作为只读测试 fixture，不复制 Trace 或报告正文。不得使用 `.env.deepseek`、OpenAI 或 DeepSeek 客户端。

Run: `.venv/bin/python -m pytest tests/test_provider_architecture.py tests/test_reporting_cli.py -q`

Expected: PASS，且测试替身能证明模型客户端网络构造器调用次数为 `0`。

- [ ] **Step 6: 检查硬编码已经移除**

Run: `rg -n "MINI_AGENT_TOOL_PROFILES|args\.provider != \"mini_agent\"|mini_agent_version|shadow_read|shadow_full" src tests README.md`

Expected: `src/` 中无 Profile/CLI/版本字段硬编码；`shadow_read`、`shadow_full` 只允许出现在测试 fixture、历史兼容示例或数据内容中。

- [ ] **Step 7: 提交**

```bash
git add schemas/eval_case.schema.json README.md docs/evaluation_report_spec.md tests
git commit -m "docs: document evaluator extension contracts"
```

- [ ] **Step 8: 最终核验提交范围**

Run: `git status --short`

Run: `git diff --check HEAD~7..HEAD`

Expected: 工作树只保留用户原有未提交修改；本方案文件无空白错误。若 Git HEAD 尚未修复，则改为逐文件校验并在交付说明中明确无法生成提交历史。
