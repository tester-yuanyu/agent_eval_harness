# Contract-Driven Plugin Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立显式插件目录、可信合同存储和 Suite 编译垂直链路，使 JSONL 与第二种数据格式都能编译为同一内部协议，并让 `run --suite` 在不改 Runner 的情况下运行现有 mini_agent 离线评测。

**Architecture:** Suite 文档只引用版本化插件和合同，`PluginCatalog` 精确解析 `(kind, id, version)`，`ContractStore` 在受限根目录内校验路径与哈希，`compile_suite()` 在创建 Runtime 前聚合所有可检测问题并生成不可变 `CompiledSuite`。本里程碑只迁移 Loader 与 Provider 的入口和溯源；Judge/Trace/Pipeline 全面插件化以及断言/报告/门禁规则迁移分别进入后续两个计划。

**Tech Stack:** Python 3.11、Pydantic 2、JSON Schema Draft 2020-12、Pytest、Ruff、JSON/JSONL、SHA-256

**Spec:** `docs/superpowers/specs/2026-10-08-contract-driven-plugin-architecture-design.md`

## Global Constraints

- Constraint 文档是非可信纯数据，不得声明 Python 模块、Entry Point、Shell 命令或内联代码。
- 插件只通过组合根显式注册；本阶段不启用自动扫描或动态 Entry Point 发现。
- 插件按精确 `(kind, id, version)` 解析，不选择“最接近”版本，也不静默回退。
- 所有路径、Schema、版本和哈希错误必须在 Agent Runtime 或模型客户端创建前失败。
- 冻结快照使用键排序、紧凑分隔符和 UTF-8 的 canonical JSON，并以 SHA-256 标识。
- 保留现有 JSONL/Manifest、CLI 参数、Python API 和历史 `results.json` 读取能力；迁移前后固定夹具结果必须等价。
- 所有默认测试离线运行，DeepSeek 与其他付费 Smoke Test 继续显式 opt-in。
- 不添加或修改 CI workflow。

## File Structure

- `src/eval_framework/plugins/models.py`：插件种类、描述符、引用和已解析插件模型。
- `src/eval_framework/plugins/catalog.py`：显式注册、精确解析和插件配置 Schema 校验。
- `src/eval_framework/plugins/protocols.py`：Loader 插件协议与规范化输入。
- `src/eval_framework/plugins/builtin/dataset_loaders.py`：现有 JSONL Loader 适配器和 JSON 文档夹具 Loader。
- `src/eval_framework/contracts/models.py`：Suite、合同引用、编译问题、快照和 `CompiledSuite`。
- `src/eval_framework/contracts/store.py`：受限路径解析、内容加载、canonical JSON 和哈希验证。
- `src/eval_framework/contracts/compiler.py`：确定性预检、Loader 调用和不可变编译产物。
- `src/eval_framework/compatibility/suite_builder.py`：旧参数到内存 Suite 的单向翻译。
- `src/eval_framework/compiled_execution.py`：从 `CompiledSuite` 创建 Provider 并调用现有 Runner。
- `src/eval_framework/composition.py`：唯一登记内置 Loader/Provider 的组合根。
- `schemas/suite_definition.schema.json`：SuiteDefinition 的冻结 JSON Schema。
- `suites/mini_agent_module_v1/suite.json`：现有 JSONL 数据集的示例 Suite。
- `tests/fixtures/json_document_dataset.json`：第二种外部数据格式的离线夹具。
- `tests/test_plugin_catalog.py`：注册、解析、配置和安全边界。
- `tests/test_contract_store.py`：路径、哈希和 canonical JSON。
- `tests/test_suite_compiler.py`：聚合预检、确定性和 Runtime 零创建保证。
- `tests/test_dataset_loader_plugins.py`：两种 Loader 输出同一内部协议。
- `tests/test_suite_cli.py`：新旧 CLI、执行等价和无付费调用。
- `tests/test_architecture_guards.py`：新内核模块不依赖具体 Agent/Judge 或 ID 分支。

## Review Focus

- 合同或数据源通过 `..`、绝对路径或符号链接逃出声明根目录时，编译必须返回 `SOURCE_PATH_OUTSIDE_ROOT`（Task 3）。
- 声明的 source/contract SHA-256 与内容不一致时，编译必须聚合 `SOURCE_FINGERPRINT_MISMATCH`，且 Loader、Provider 和模型客户端调用计数均为零（Task 5）。
- 插件 key 重复、kind 错误、版本不存在或合同版本不兼容时，必须分别产生稳定错误，绝不回退到其他插件（Task 2、Task 5）。
- 插件配置包含未知字段或类型错误时，错误必须包含 Suite JSON 路径，并在执行前返回 `PLUGIN_CONFIG_INVALID`（Task 2、Task 5）。
- 旧参数与 `--suite` 混用必须明确拒绝；仅旧参数生成的兼容 Suite 与显式 Suite 对同一夹具产生等价 canonical Case 结果（Task 7）。

---

### Task 1: 定义插件与 Suite 的严格协议

**Files:**
- Create: `src/eval_framework/plugins/__init__.py`
- Create: `src/eval_framework/plugins/models.py`
- Create: `src/eval_framework/contracts/__init__.py`
- Create: `src/eval_framework/contracts/models.py`
- Create: `schemas/suite_definition.schema.json`
- Test: `tests/test_suite_contracts.py`

**Interfaces:**
- Produces: `PluginKind = Literal["provider", "dataset_loader", "assertion_rule", "trace_rule", "judge_backend", "pipeline_stage", "report_renderer", "gate_check"]`.
- Produces: `PluginDescriptor(plugin_id, kind, version, config_schema, supported_contract_versions, implementation_fingerprint)` and `PluginReference(plugin_id, version, config={})`.
- Produces: `ContractReference(contract_id, version, path, sha256)` and `DatasetSource(path, sha256)`; paths must be non-empty relative POSIX paths.
- Produces: strict `SuiteDefinition(schema_version="1.0", suite_id, suite_version, lifecycle_state, dataset_loader, dataset_sources, provider, capability_bundle, assertion_profile, trace_profile, judge_profile, report_profile, gate_policy, run_config)`.
- Produces: `ResolvedSource(logical_path, filesystem_path, sha256, content)`、`CompilationIssue(code, field_path, message, evidence_refs=[])`、`ResolvedContract`、`ResolvedPluginSnapshot`，以及包含 `dataset`、expanded snapshots、fingerprints 和 `compiled_suite_sha256` 的 frozen `CompiledSuite`；snapshot 不序列化 `filesystem_path` 或原始 `content`。
- Produces: `LoadedSuiteDefinition(definition, source_path, root, source_sha256, origin)`；`origin` 只允许 `"file"` 或 `"legacy_compatibility"`，不进入 frozen Suite 文档。

- [ ] **Step 1: 写协议失败测试**

在 `tests/test_suite_contracts.py` 增加 `test_suite_definition_is_strict_and_rejects_executable_fields`、`test_plugin_descriptor_requires_exact_identity_fields`、`test_compiled_suite_is_frozen`。断言 Suite 中的 `module`、`command`、未知字段被拒绝，相对路径可接受而绝对路径/`..` 被拒绝，对 frozen model 赋值抛出异常。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_suite_contracts.py -q`

Expected: FAIL，协议模块尚不存在。

- [ ] **Step 3: 实现严格 Pydantic 模型**

所有声明模型继承现有 `StrictModel`；集合字段使用 `default_factory`；标识符不能为空；SHA-256 字段必须是 64 位小写十六进制；Plugin config Schema 必须是 object 且 `additionalProperties: false`；`CompiledSuite` 使用 `ConfigDict(frozen=True, extra="forbid")`。Profile 引用当前允许 `None`，但不放入任何可执行默认值。

- [ ] **Step 4: 生成并冻结 Suite Schema**

从 `SuiteDefinition.model_json_schema()` 写出 `schemas/suite_definition.schema.json`；测试断言磁盘 Schema 与运行时生成结果相等，避免手工漂移。

- [ ] **Step 5: 验证并提交**

Run: `.venv/bin/python -m pytest tests/test_suite_contracts.py -q`

Expected: PASS。

```bash
git add src/eval_framework/plugins src/eval_framework/contracts schemas/suite_definition.schema.json tests/test_suite_contracts.py
git commit -m "feat: define plugin and suite contracts"
```

### Task 2: 实现精确解析的 PluginCatalog

**Files:**
- Create: `src/eval_framework/plugins/catalog.py`
- Test: `tests/test_plugin_catalog.py`

**Interfaces:**
- Consumes: Task 1 的 `PluginDescriptor`、`PluginReference`、`PluginKind`、`ResolvedPluginSnapshot`。
- Produces: `PluginRegistration[T](descriptor: PluginDescriptor, implementation: T)`。
- Produces: `PluginCatalog.register(descriptor, implementation) -> None`、`PluginCatalog.resolve(reference, *, expected_kind, contract_version, field_path) -> PluginRegistration[Any]`、`PluginCatalog.snapshot(registration) -> ResolvedPluginSnapshot`。
- Produces: `PluginCatalogError(code, message, *, field_path=None)`，稳定 code 为 `DUPLICATE_PLUGIN`、`PLUGIN_NOT_FOUND`、`PLUGIN_KIND_MISMATCH`、`PLUGIN_CONTRACT_INCOMPATIBLE`、`PLUGIN_CONFIG_INVALID`。

- [ ] **Step 1: 写注册、错误类型和配置 Schema 测试**

增加六个测试：精确 key 解析、重复 key、同 ID 错 kind、版本不存在不回退、合同版本不兼容、Draft 2020-12 Schema 拒绝额外配置字段。最后一个测试断言错误 `field_path == "$.dataset_loader.config.unexpected"`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_plugin_catalog.py -q`

Expected: FAIL，Catalog 尚不存在。

- [ ] **Step 3: 实现 Catalog**

内部只使用 `dict[tuple[PluginKind, str, str], PluginRegistration[Any]]`；解析时先检查精确 kind/id/version，再用 `Draft202012Validator.iter_errors()` 按路径排序并转换为稳定错误。不得导入任何 builtin 或具体 Provider。

- [ ] **Step 4: 验证并提交**

Run: `.venv/bin/python -m pytest tests/test_plugin_catalog.py -q`

Expected: PASS。

```bash
git add src/eval_framework/plugins/catalog.py tests/test_plugin_catalog.py
git commit -m "feat: add explicit versioned plugin catalog"
```

### Task 3: 实现受限 ContractStore 与确定性指纹

**Files:**
- Create: `src/eval_framework/contracts/store.py`
- Test: `tests/test_contract_store.py`

**Interfaces:**
- Consumes: Task 1 的 `ContractReference`、`DatasetSource`、`ResolvedContract`。
- Produces: `canonical_json_bytes(value: Any) -> bytes`，固定为 `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`。
- Produces: `sha256_bytes(value: bytes) -> str`。
- Produces: `ContractStore(root: Path).resolve_source(source) -> ResolvedSource` 与 `.load_contract(reference) -> ResolvedContract`。
- Produces: `ContractStoreError(code, message, *, evidence_refs)`，code 至少为 `SOURCE_PATH_OUTSIDE_ROOT`、`SOURCE_NOT_FOUND`、`SOURCE_FINGERPRINT_MISMATCH`、`CONTRACT_INVALID_JSON`。

- [ ] **Step 1: 写正常解析与安全失败测试**

测试 canonical JSON 对键顺序不敏感、相对文件成功加载、绝对路径和 `..` 被拒绝、指向根外文件的 symlink 被拒绝、内容哈希不一致、非法 JSON。symlink 测试使用 `tmp_path`，不依赖平台固定目录。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_contract_store.py -q`

Expected: FAIL，Store 尚不存在。

- [ ] **Step 3: 实现路径和哈希边界**

先以 `root.resolve(strict=True)` 固定根，再解析目标并用 `Path.is_relative_to(root)` 检查真实路径；读取后立即校验声明 SHA-256。合同 JSON 必须是 object，保存解析值与原始内容哈希，错误不得包含文件内容。

- [ ] **Step 4: 验证并提交**

Run: `.venv/bin/python -m pytest tests/test_contract_store.py -q`

Expected: PASS。

```bash
git add src/eval_framework/contracts/store.py tests/test_contract_store.py
git commit -m "feat: add trusted contract store"
```

### Task 4: 将数据加载封装为插件协议

**Files:**
- Create: `src/eval_framework/plugins/protocols.py`
- Create: `src/eval_framework/plugins/builtin/__init__.py`
- Create: `src/eval_framework/plugins/builtin/dataset_loaders.py`
- Modify: `src/eval_framework/dataset_loader.py`
- Create: `tests/fixtures/json_document_dataset.json`
- Test: `tests/test_dataset_loader_plugins.py`

**Interfaces:**
- Consumes: Task 1 的 `ResolvedSource(logical_path: str, filesystem_path: Path, sha256: str, content: bytes)`。
- Produces: `DatasetLoaderPlugin.load(sources: Sequence[ResolvedSource], *, filters: DatasetFilters | None, config: Mapping[str, Any]) -> DatasetBundle` Protocol。
- Produces: `LegacyJsonlDatasetLoader`，只委托现有 `load_dataset()`，config Schema 禁止额外字段且只允许单 source。
- Produces: `JsonDocumentDatasetLoader`，读取 `{ "metadata": {...}, "cases": [...] }` 夹具并返回相同 `DatasetBundle`；稳定 plugin ID 为 `fixture_json_document_v1`。

- [ ] **Step 1: 写 Loader conformance 测试**

增加可复用 `assert_loader_conforms(loader, sources, expected_case_ids)`；覆盖两种 Loader 都返回严格 `DatasetBundle`、重复 `case_id` 返回 `DatasetLoadError`、JSON 文档 Loader 接受 filters、零 source/多 source 明确拒绝。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_dataset_loader_plugins.py -q`

Expected: FAIL，插件协议和适配器尚不存在。

- [ ] **Step 3: 提取 bytes 输入的现有解析函数**

在 `dataset_loader.py` 增加 `load_jsonl_dataset(source: ResolvedSource, filters=None) -> DatasetBundle`；`load_dataset(path, filters)` 保持签名并负责构造 source 后委托，确保公共 API 和错误文本兼容。

- [ ] **Step 4: 实现两个 Loader**

两者只做外部格式到 canonical `DatasetBundle` 的转换，不调用 Provider、不创建 Runtime、不识别业务断言。JSON 文档夹具与一个现有 JSONL fixture 使用相同 Case 内容供后续等价测试。

- [ ] **Step 5: 验证并提交**

Run: `.venv/bin/python -m pytest tests/test_dataset_loader_plugins.py tests/test_protocol_loader_validator.py -q`

Expected: PASS。

```bash
git add src/eval_framework/dataset_loader.py src/eval_framework/plugins/protocols.py src/eval_framework/plugins/builtin tests/fixtures/json_document_dataset.json tests/test_dataset_loader_plugins.py
git commit -m "feat: load canonical datasets through plugins"
```

### Task 5: 编译 Suite 并聚合全部预检问题

**Files:**
- Create: `src/eval_framework/contracts/compiler.py`
- Test: `tests/test_suite_compiler.py`

**Interfaces:**
- Consumes: Tasks 1–4 的模型、Catalog、Store、Loader Protocol。
- Produces: `load_suite_definition(path: str | Path) -> LoadedSuiteDefinition`，记录 Suite 根目录、原文 SHA-256 和严格模型。
- Produces: `compile_suite(definition: LoadedSuiteDefinition, catalog: PluginCatalog, contract_store: ContractStore) -> CompiledSuite`。
- Produces: `SuiteCompilationError(issues: Sequence[CompilationIssue])`，issues 按 `(field_path, code, message)` 稳定排序，异常 code 为 `SUITE_COMPILATION_FAILED`。

- [ ] **Step 1: 写成功编译和确定性测试**

`test_compile_suite_resolves_loader_provider_contracts_and_sources` 断言 Loader 输出进入 `CompiledSuite.dataset`；`test_compiled_suite_hash_is_deterministic` 用不同 JSON 键顺序编译两次，断言 canonical snapshot 与 SHA-256 相同。

- [ ] **Step 2: 写聚合失败和零执行测试**

用计数 Fake Loader/Provider 同时制造 source 哈希错误、未知 Provider、非法 Loader config 和合同哈希错误；断言一次异常含全部独立 issue，Loader/Provider/model-client 计数均为 `0`。另测 Loader 返回非 `DatasetBundle` 时为 `LOADER_OUTPUT_INVALID`。

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_suite_compiler.py -q`

Expected: FAIL，compiler 尚不存在。

- [ ] **Step 4: 实现两阶段编译**

第一阶段只解析文档、Plugin、config、source 和 contract 并聚合错误；只在 issues 为空时调用 Loader。第二阶段校验 canonical Dataset、Provider/Capability 身份和 Profile 引用，再生成 expanded snapshot；任何第二阶段错误仍不得创建 Provider Runtime。

- [ ] **Step 5: 固化快照内容**

快照必须包含 Suite 全展开值、每个 source/contract 的 ID/version/SHA-256、每个已解析 Descriptor 的 kind/id/version/implementation fingerprint，以及 Loader 产生的 Dataset 身份；不得包含绝对路径、环境变量或 secret 值。

- [ ] **Step 6: 验证并提交**

Run: `.venv/bin/python -m pytest tests/test_suite_compiler.py tests/test_contract_store.py tests/test_plugin_catalog.py -q`

Expected: PASS。

```bash
git add src/eval_framework/contracts/compiler.py tests/test_suite_compiler.py
git commit -m "feat: compile suites before runtime creation"
```

### Task 6: 组合根注册内置插件并执行 CompiledSuite

**Files:**
- Modify: `src/eval_framework/composition.py`
- Modify: `src/eval_framework/provider_registry.py`
- Create: `src/eval_framework/compiled_execution.py`
- Modify: `src/eval_framework/schemas.py`
- Modify: `src/eval_framework/reporting.py`
- Test: `tests/test_compiled_execution.py`

**Interfaces:**
- Produces: `default_plugin_catalog() -> PluginCatalog`，登记 `legacy_jsonl_eval_case_v1@1.0.0`、`fixture_json_document_v1@1.0.0` 和 `mini_agent_provider_v1@1.0.0`；现有 `default_provider_registry()` 保留。
- Produces: `execute_compiled_suite(compiled: CompiledSuite, catalog: PluginCatalog, *, model_client_factory=None, legacy_judge_client=None) -> EvaluationRunResult`；执行前重新解析精确 Provider key 并校验 descriptor fingerprint 与编译快照一致，不允许 Catalog 漂移。
- Extends: `EvaluationRunResult` 新增兼容默认字段 `compiled_suite_sha256: str | None`、`compiled_suite_snapshot: dict[str, Any] | None`、`plugin_fingerprints: list[dict[str, str]]`、`contract_fingerprints: list[dict[str, str]]`。

- [ ] **Step 1: 写执行边界与溯源测试**

使用 Fake Provider Factory 断言 compiler 成功后才调用 `create()`，Runner 接收 Loader 生成的 Dataset，不读取源格式；结果和 report manifest 包含相同 compiled hash/插件/合同指纹；旧结果缺少新字段仍可加载。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_compiled_execution.py -q`

Expected: FAIL，执行桥和结果字段尚不存在。

- [ ] **Step 3: 实现内置描述符和执行桥**

仅 `composition.py` 可导入 builtin Loader 与 `MiniAgentProviderFactory`；`compiled_execution.py` 通过 Catalog 解析已编译的精确 Provider key，创建 Provider 后调用现有 `run_provider_evaluation()`，再以 `model_copy(update=...)` 附加溯源。

- [ ] **Step 4: 持久化新增溯源**

`write_report()` 继续写历史文件，并在 manifest/results 中保留新增字段。不得修改 Case、断言、Judge 或质量结论逻辑。

- [ ] **Step 5: 验证并提交**

Run: `.venv/bin/python -m pytest tests/test_compiled_execution.py tests/test_result_loader.py tests/test_reporting_cli.py -q`

Expected: PASS。

```bash
git add src/eval_framework/composition.py src/eval_framework/provider_registry.py src/eval_framework/compiled_execution.py src/eval_framework/schemas.py src/eval_framework/reporting.py tests/test_compiled_execution.py
git commit -m "feat: execute compiled suites with provenance"
```

### Task 7: 增加 `--suite` 并把旧入口翻译为兼容 Suite

**Files:**
- Create: `src/eval_framework/compatibility/__init__.py`
- Create: `src/eval_framework/compatibility/suite_builder.py`
- Modify: `src/eval_framework/cli.py`
- Create: `suites/mini_agent_module_v1/suite.json`
- Test: `tests/test_suite_cli.py`

**Interfaces:**
- Produces: `build_legacy_suite(*, dataset, provider, capability_bundle, filters, run_config) -> LoadedSuiteDefinition`，使用 builtin stable IDs 和已读取文件 SHA-256，并把 `origin` 标为 `"legacy_compatibility"`。
- CLI: `validate` 和 `run` 新增 `--suite`；`--suite` 与 `--dataset/--provider/--capability-bundle` 互斥，`run --suite ... --output-dir ...` 为首选入口。
- Compatibility: 旧 `--judge-config` 只允许 `origin == "legacy_compatibility"`，继续创建现有 Judge client、通过 `legacy_judge_client` 传给执行桥并发出 `DeprecationWarning`；文件 Suite 中的 `run_config.judge` 或非空 `judge_profile` 以 `PROFILE_STAGE_NOT_MIGRATED` 预检失败，待里程碑 2 接入 Judge plugin 后移除此限制。

- [ ] **Step 1: 写 CLI 参数和无 Runtime 失败测试**

覆盖：只给 `--suite` 可 validate；`--suite` 与旧 source flags 混用返回 2；未知插件/坏哈希返回结构化 compilation issues；这些失败下 Provider Factory 计数为零。

- [ ] **Step 2: 写新旧路径等价测试**

同一离线 Fake Provider 分别运行显式 Suite 和 `build_legacy_suite()`；去掉 run ID、时间和绝对输出路径后，断言 Dataset identity、Case results、summary 和 conclusion 相等。另用 JSON 文档 Suite 证明无需修改 Runner 即可运行第二种格式。

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_suite_cli.py -q`

Expected: FAIL，CLI 尚无 `--suite`。

- [ ] **Step 4: 实现兼容翻译器**

翻译器只构造内存声明，不调用 Loader/Provider；所有路径在 Suite 根下表达，临时兼容根由调用者明确传入。旧入口打印一次 deprecation 到 stderr，stdout 继续保持机器可读 JSON。

- [ ] **Step 5: 重构 CLI 为统一编译入口**

`validate/run` 均依次调用 `load_suite_definition()`、`compile_suite()`；run 再调用 `execute_compiled_suite()`。CLI 不直接实例化 Loader 或 Provider；Judge 旧分支保持隔离并在里程碑 2 删除。

- [ ] **Step 6: 验证并提交**

Run: `.venv/bin/python -m pytest tests/test_suite_cli.py tests/test_reporting_cli.py -q`

Expected: PASS。

```bash
git add src/eval_framework/compatibility src/eval_framework/cli.py suites/mini_agent_module_v1/suite.json tests/test_suite_cli.py
git commit -m "feat: run compiled suites from the cli"
```

### Task 8: 架构守卫、文档和全量离线回归

**Files:**
- Create: `tests/test_architecture_guards.py`
- Modify: `README.md`
- Modify: `PHASE_END_REPORT.md`
- Modify: `src/eval_framework/__init__.py`

**Interfaces:**
- Consumes: Tasks 1–7 的公开入口。
- Produces: 对外导出 `PluginCatalog`、`SuiteDefinition`、`CompiledSuite`、`load_suite_definition`、`compile_suite`、`execute_compiled_suite`。
- Produces: 文档化的插件接入清单：描述符、实现、配置 Schema、Suite 引用、conformance tests、显式注册；不要求修改 Runner。

- [ ] **Step 1: 写 AST 架构守卫**

断言 `contracts/`、`plugins/catalog.py`、`compiled_execution.py` 不导入 `providers.mini_agent`、`judges.deepseek`；`contracts/compiler.py` 不包含 builtin plugin IDs；Runner 不导入 Loader plugin。Suite Schema 不含 `module`、`command`、`entry_point` 字段。

- [ ] **Step 2: 运行守卫并修正越界依赖**

Run: `.venv/bin/python -m pytest tests/test_architecture_guards.py -q`

Expected: PASS；如失败，仅移动注册到 `composition.py` 或改为协议依赖，不增加字符串豁免。

- [ ] **Step 3: 更新 README 和阶段报告**

记录 `run --suite` 示例、旧入口弃用状态、如何增加 Agent/Loader、可信代码边界、已实现的里程碑 1 和尚未迁移的 Judge/Trace/Assertion/Report/Gate；明确 CI 未实施。

- [ ] **Step 4: 执行全量离线验证**

Run: `.venv/bin/python -m pytest -q`

Expected: 全部 PASS，DeepSeek/OpenAI smoke tests 为 SKIPPED。

Run: `.venv/bin/python -m ruff check .`

Expected: 无错误。

Run: `.venv/bin/python -m build`

Expected: sdist 和 wheel 构建成功；wheel 包含 Python 模块，示例 Suite 继续作为仓库文档资产而非隐式运行时资源。

- [ ] **Step 5: 提交**

```bash
git add tests/test_architecture_guards.py README.md PHASE_END_REPORT.md src/eval_framework/__init__.py
git commit -m "docs: complete plugin foundation milestone"
```

## Deferred Milestones

- **Milestone 2 — Execution Pipeline migration:** Provider/Judge/Trace 全部通过 Catalog 与 Profile 接入；移除 CLI 对 `DeepSeekJudgeClient` 的直接构造和 Runner 的具体 Provider 兼容导入；加入第二个 fixture Agent。
- **Milestone 3 — Declarative policy migration:** 拆分 assertion engine/rules，配置化 report labels、Trace vocabulary 和 Gate checks，并完成无业务 rule ID 分支的架构验收。

本计划完成后即形成可运行、可验证的第一条合同驱动垂直链路，但不宣称整个架构设计已全部完成。
