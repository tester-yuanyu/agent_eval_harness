# 全层级评测集生成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从指定完整能力包生成覆盖全部模块、意图、工具、关键链路和端到端目标的待审核数据集，区分可消费 EvalCase、待适配契约案例与阻塞项。

**Architecture:** 新增独立 `full_generation` 包，复用原有能力包可信校验，不修改历史 Suite 或冻结集。全量能力目录经过确定性覆盖规划与分层编译，输出两种明确区分的案例格式；所有覆盖项均关联案例或 blocker。契约案例表达当前 evaluator 无法执行的直接测试，绝不混入 EvalCase 文件。

**Tech Stack:** Python 3.11+、Pydantic 2、jsonschema、现有 agent-evaluator、pytest、Ruff；首次本地确定性生成，不使用付费 API。

**Spec:** `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/FULL_DATASET_GENERATION_DESIGN.md`（用户已确认）。

## Global Constraints

- 输入：`/Users/yuanyu/Documents/ChatGPT/mini_agent/exports/full_tools_fixture_v1/bundle`。
- Bundle Hash：`215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c`。
- 目标：7 Module + 7 Intent + 6 Tool + 3 Chain，共 23；Scope／Boundary／Evidence 保留为约束依赖。
- 输出：`workspaces/full_tools_fixture_v1_full_eval_20261020/`；拒绝覆盖已存在的完整交付目录。
- 不修改 Agent 业务实现，不修改 evaluator 公共协议，不覆盖旧数据集，不复用旧批准。
- 不通过运行 Agent 推导 Oracle；数据集保持 DRAFT，审核清单不勾选。
- 所有工具均按 test_fixture 对待；确认后恢复、上下文、生产绑定缺口按已批准方案处理。
- 新增代码与现有 Suite 流程并存；执行时先按 using-git-worktrees 技能检查隔离方式，保留当前未提交工作，禁止 reset/clean。

## Review Focus

- 包或辅助资料在生成过程中变化：不得交付绑定旧 Hash 的新内容（任务 1、6）。
- 缺少 fixture 初始状态：不得凭空假定 ID 存在或制造精确返回记录（任务 3、4）。
- unsupported/unknown 或业务争议：不得通过正常案例掩盖缺口（任务 2、4）。
- evaluator 结构接收但无执行适配：不得将静态合法误记为 runtime-ready（任务 4、5）。
- 生成中途失败／目标已存在：不得覆盖历史文件或暴露伪完整目录（任务 6）。

## 文件与数据接口

新增文件均位于 `src/dataset_builder/full_generation/`：

| 文件 | 职责 |
|---|---|
| `models.py` | 冻结模型、覆盖项、案例、阻塞及交付协议 |
| `inventory.py` | 可信输入加载、全量目录、来源引用解析 |
| `planner.py` | 能力与约束到稳定覆盖项的映射 |
| `contract_cases.py` | 直接模块／工具及待适配链路案例 |
| `intent_cases.py` | 七种意图的确定性候选与 EvalCase |
| `runtime_cases.py` | 当前 evaluator 可表达的链路／端到端子集 |
| `validation.py` | 双协议校验、来源、覆盖和可执行状态检查 |
| `delivery.py` | 事务式目录交付、报告、未勾选审核清单 |
| `__init__.py` | 暴露生成函数 |

修改 `src/dataset_builder/cli.py` 增加入口；新增 `tests/test_full_generation_*.py`。Schema 写入 `schemas/full_generation/`。不重构现有单意图编译器。

公共模型使用 Pydantic `extra="forbid"`：

- `SourceRef(snapshot_id, relative_path, snapshot_sha256, pointer)`：pointer 为 JSON Pointer，必须实际可解析。
- `FullInventory(bundle_sha256, targets, artifacts, external_bindings, gaps)`：artifacts 保存所有已验证快照的结构化视图。
- `CoverageSlot(slot_id, target_id, layer, dimension, source_refs, support_status, case_kind, blocker_ids)`。
- `Blocker(blocker_id, affected_slot_ids, reason, source_refs, required_action)`。
- `ContractCase(schema_version="1.0", dataset_format="capability_contract_case", case_id, slot_id, target_id, layer, preconditions, input, oracle, source_refs, runner_requirements)`。
- `CompiledCase(slot_id, dataset_format, payload, validation_status, execution_readiness, coverage_mode, blocker_ids)`：payload 为 EvalCase 或 ContractCase 的对象；`execution_readiness` 为 `not_run/needs_runner/blocked`，任何值均不表示 PASS。
- `GenerationResult(inventory, slots, cases, blockers)`；`DeliveryReport(output_path, file_count, case_counts, blocker_count, valid)`。

前置条件和 Oracle 必须分字段；契约谓词只使用有明确定义的操作：`schema_valid`、`equals`、`subset`、`sequence`、`count`、`unchanged`。没有对应运行适配时一律 `needs_runner`，不凭自定义谓词声称 evaluator 支持。

### Task 1: 环境基线与可信全量目录

**Files:** 新增 `models.py`、`inventory.py`、`tests/test_full_generation_inventory.py`。

**Interfaces:** `load_inventory(bundle: Path, delivery_root: Path, expected_hash: str) -> FullInventory`；其他任务只通过该目录读取能力事实。

- [ ] 检查本地 Python 环境与依赖声明，按现有 evaluator 项目声明恢复缺失依赖；不改 evaluator 源码。记录安装前后包版本。
- [ ] 运行 `.venv/bin/python -m pytest -q -m 'not dataset_generation_smoke'`，保存实际基线；若失败，先定位是否已有兼容问题，不能把旧结果当成本次结果。
- [ ] 编写失败测试：`test_full_inventory_has_23_targets` 断言目标类型数量为 7/7/6/3；`test_tampered_bundle_rejected`、`test_changed_auxiliary_manifest_rejected` 断言 ValueError；`test_missing_source_pointer_rejected` 断言非法来源不能进入目录。
- [ ] 执行 `.venv/bin/python -m pytest tests/test_full_generation_inventory.py -q`，确认失败来自缺少新增实现。
- [ ] 实现模型与 loader，复用可信 Profile、安全内核、原始文件 Hash 与外层 Manifest 核验；不采用隔离导入绕过主包作为正式实现。
- [ ] 重跑任务测试，全部通过后检查仅本任务文件差异，并形成独立提交；不把用户已有改动一并暂存。

### Task 2: 确定性覆盖规划

**Files:** 新增 `planner.py`、`tests/test_full_generation_planner.py`。

**Interfaces:** `plan_coverage(inventory: FullInventory) -> tuple[list[CoverageSlot], list[Blocker]]`。

- [ ] 编写失败测试：`test_all_targets_accounted_for` 断言 Slot 覆盖全部 23 个目标；`test_plan_is_stable` 断言相同输入及字典重排后稳定 ID 相同；`test_unknown_is_not_positive` 断言未知和不支持项不生成正向成功分支。
- [ ] 添加 `test_all_declared_results_and_parameters_accounted_for`，逐工具核对 declared_results、参数约束、权限、幂等和副作用都有 Slot 或明确 blocker；嵌套 `$ref` 与 anyOf 不能遗漏。
- [ ] 执行 `.venv/bin/python -m pytest tests/test_full_generation_planner.py -q`，确认红灯。
- [ ] 实现按目标 ID、JSON Pointer、维度生成稳定 Slot；正常、边界和非法值只从 Schema 约束推导。链路为适用 Intent／Tool 组合展开；缺少工具的 unsupported Intent 保留提前拒绝或 blocker，不强行要求工具成功。
- [ ] 对宽泛模块 object Schema、上下文不支持、确认恢复、资源 policy 争议、环境绑定和缺少 runner 明确生成阻塞记录。
- [ ] 重跑测试至通过，核对全部来源 Pointer 后仅提交本任务文件。

### Task 3: 直接模块与工具契约案例

**Files:** 新增 `contract_cases.py`、`schemas/full_generation/contract_case.schema.json`、`tests/test_full_generation_contract_cases.py`。

**Interfaces:** `compile_contract_cases(inventory: FullInventory, slots: list[CoverageSlot]) -> list[CompiledCase]`。

- [ ] 编写失败测试：`test_tool_case_has_structured_arguments` 断言直接工具案例包含工具输入且不伪装成 user_input；`test_invalid_argument_case_is_intentional` 断言非法样本不通过参数 Schema 且 Oracle 指向拒绝；`test_unknown_fixture_record_requires_precondition` 断言具体结果依赖显式初始状态。
- [ ] 添加 `test_confirmation_is_external_fixture_only` 和 `test_resource_idempotency_sequence`，检查外部单次授权、相同 request_id 同参数返回原结果、冲突不变更状态的序列语义；不能根据实际 handler 输出填写 Oracle。
- [ ] 执行 `.venv/bin/python -m pytest tests/test_full_generation_contract_cases.py -q`，确认红灯。
- [ ] 实现测试输入构造与谓词生成，区分 JSON Schema 的 nullable required 字段与意图层省略规则；模块无独立输入接口时仅生成声明支持的观察定义并注明 needs_runner。
- [ ] 模式互斥、AND、去重、all-or-nothing 等按快照显式规则映射；无法解释的规则输出 blocker，不静默跳过。
- [ ] 输出并验证契约 Schema，重跑测试通过后仅提交本任务文件。

### Task 4: 意图及现有 EvalCase 子集

**Files:** 新增 `intent_cases.py`、`runtime_cases.py`、`tests/test_full_generation_evalcases.py`。

**Interfaces:** `compile_intent_cases(inventory: FullInventory, slots: list[CoverageSlot]) -> list[CompiledCase]`；`compile_runtime_cases(inventory: FullInventory, slots: list[CoverageSlot]) -> tuple[list[CompiledCase], list[Blocker]]`。

- [ ] 编写失败测试：`test_all_seven_intents_have_cases`；`test_gift_stops_for_confirmation_without_write` 断言不期待礼物发放；`test_prepare_resource_dispute_blocks_positive_e2e`；`test_no_fake_fault_injection_support`。
- [ ] 添加 `test_critical_path_serializes_as_link`，断言 EvalCase 使用 link；`test_e2e_requires_real_supported_goal_assertion`，没有可执行终态 scorer 的案例转契约定义／blocker，禁止填空 goal_state 只为过 Schema。
- [ ] 执行 `.venv/bin/python -m pytest tests/test_full_generation_evalcases.py -q`，确认红灯。
- [ ] 从各 Intent IR、显式规则与经过复核的现有候选生成案例；对旧候选重新校验参数、状态、缺参和 Slot 语义，并重新绑定新包。
- [ ] 读取 evaluator 当前 ASSERTION_SCOPES、配置和 Evidence 要求，只使用已实现断言；预期工具调用使用包中真实名称，执行 Profile 从可信工具集合构建。
- [ ] 不修改 evaluator 的 write case 规则，不人为注入 user_responses 绕过“确认恢复不支持”；无法满足真实消费者约束时保留契约案例与阻塞。
- [ ] 用真实 `EvalCase`、`load_dataset`、`validate_dataset` 验证输出子集，重跑任务测试通过后提交本任务文件。

### Task 5: 完整性、覆盖和审核报告

**Files:** 新增 `validation.py`、`tests/test_full_generation_validation.py`。

**Interfaces:** `validate_generation(result: GenerationResult) -> dict`，返回包含 `valid`、`issues`、`coverage` 和 `counts` 的报告。

- [ ] 编写失败测试：`test_uncovered_slot_fails`、`test_dangling_case_reference_fails`、`test_duplicate_id_fails`、`test_changed_source_fails`。
- [ ] 添加 `test_static_pass_never_means_runtime_pass`、`test_indirect_coverage_not_counted_as_direct`、`test_contract_jsonl_not_sent_to_evalcase_loader`；分别验证状态与协议分离。
- [ ] 执行 `.venv/bin/python -m pytest tests/test_full_generation_validation.py -q`，确认红灯。
- [ ] 实现双协议校验、正负参数样本区分、所有来源 Pointer 和 Hash 校验、覆盖项到案例／blocker 的闭包检查；检查答案不进入执行输入、完全重复案例与重复 ID。
- [ ] 报告分别统计定义覆盖率、可消费数量、直接／间接／契约覆盖和阻塞数；不生成运行成功率。
- [ ] 重跑任务测试通过后提交本任务文件。

### Task 6: CLI、正式生成与交付

**Files:** 新增 `delivery.py`、`tests/test_full_generation_delivery.py`；修改 `cli.py`、`README.md`。

**Interfaces:** `generate_full_dataset(bundle: Path, delivery_root: Path, output: Path, expected_hash: str) -> DeliveryReport`。

- [ ] 编写失败测试：`test_existing_output_is_not_overwritten`、`test_mid_generation_failure_does_not_publish`、`test_bundle_mutation_before_publish_rejected`、`test_review_starts_unchecked`。
- [ ] 添加 CLI 测试，验证 `generate-full --bundle ... --delivery-root ... --expected-bundle-hash ... --workspace ...` 可独立调用、失败返回非零且不会覆盖旧集。
- [ ] 执行 `.venv/bin/python -m pytest tests/test_full_generation_delivery.py -q`，确认红灯。
- [ ] 在输出同父目录临时目录生成全部文件，复制并复验输入能力包，复验来源及报告通过后重命名发布；失败只清理本次临时目录。
- [ ] JSONL 按层级、目标和协议分别输出；Manifest 列出 dataset_format、文件 Hash、数量、依赖／运行状态。写出全部覆盖矩阵、blockers、未勾选审核清单和 README。
- [ ] 运行新增全部测试、现有回归测试和 Ruff；对 evaluator 现有兼容问题单独记录，不能放宽 Gate 获取通过。
- [ ] 执行以下完整生成命令：

```bash
.venv/bin/python -m dataset_builder.cli generate-full \
  --bundle /Users/yuanyu/Documents/ChatGPT/mini_agent/exports/full_tools_fixture_v1/bundle \
  --delivery-root /Users/yuanyu/Documents/ChatGPT/mini_agent/exports/full_tools_fixture_v1 \
  --expected-bundle-hash 215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c \
  --workspace workspaces/full_tools_fixture_v1_full_eval_20261020
```

- [ ] 从磁盘重新加载交付，验证 23 个目标全部有记录、JSONL 行数与 Manifest 相同、无悬空引用、文件 Hash 匹配、没有 APPROVED/FROZEN 或伪造 PASS。
- [ ] 审查最终改动，仅提交本次实现；保留用户原有工作。最终回复提供 README、各层入口、覆盖矩阵与 blocker 地址，并列明实际案例数量、可消费数量和未执行限制。

## 自审结论

六项任务覆盖已批准方案的输入、规划、编译、双协议、校验、审核和交付；五类 Review Focus 均有对应测试。模块和工具运行适配不在本次隐式扩展范围，端到端案例是否可消费以真实 evaluator 校验和 scorer 能力为准。

建议在当前会话由主代理顺序实施，完成后独立审查：任务间依赖紧密，共用目录、Slot 和案例接口，顺序执行更容易保持一致。实施前按项目技能要求请用户审阅计划并选择执行方式。

## 实施记录（2026-10-20）

六项任务已实施，具体测试与裁决见 `.superpowers/sdd/2026-10-20-full-dataset-generation/progress.md`。
执行使用 `PYTHONPATH=src ../agent_evaluator/.venv/bin/python`；当前仓库环境缺少 evaluator 所需的 langfuse。
为保留原有未提交工作，未执行任务提交或切换工作树。意图案例采用从本次能力契约编写的明确样本，未复制旧候选。
独立审查的两项缺陷已加入失败回归测试并修复；全仓 210 项测试通过，新增包、CLI、测试 Ruff 通过。
正式交付：`workspaces/full_tools_fixture_v1_full_eval_20261020`，所有案例保持 DRAFT / NOT_RUN / PENDING。
生成定义 365 条、静态检查 202 条、阻塞义务 280 条；后者明确记录能力或适配缺口，不视为已可执行评测。
