# 通用意图契约注册表实施计划

> **执行要求：** 必须使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`，按任务逐项实施本计划。所有步骤使用复选框（`- [ ]`）跟踪。

**目标：** 为 mini_agent 的全部现有意图增加可复用的意图契约层，统一完成参数规范化、参数校验、不支持语义保护、决策生成和可观测 Trace。

**架构：** 模型继续返回 `IntentResult` 候选。`IntentRouter` 将候选结果和原始用户输入交给默认 `IntentRegistry`；每个已注册的 `IntentDefinition` 依次执行可复用的规范化器、语义约束、严格 Pydantic 参数校验和读、写或不支持决策策略，最终返回规范的公共 `IntentResult`。工具 Schema 仍是执行前的最终校验边界。

**技术栈：** Python 3.11+、Pydantic v2、Pytest、Ruff，以及现有 OpenAI 兼容 Responses 客户端

**设计文档：** `docs/superpowers/specs/2026-10-07-intent-contract-registry-design.md`

## 全局约束

- 保持 `run_intent_only(user_input) -> IntentResult`、`run(...) -> AgentResult` 和 `store.snapshot(run_id)` 兼容。
- 不新增依赖、工具、意图、SQLite 表、评测器逻辑或评测集逻辑。
- 不编码 case ID、完整固定评测输入、预期分数或标准答案。
- 所有默认意图必须使用同一套注册表控制流；意图特有行为放在定义和可复用策略中。
- 工具 Schema 保持严格，继续拒绝未声明字段和类型强制转换。
- Trace 可以包含输入、规范化值、公开校验失败和决策，但不能包含隐藏推理。
- 非法模型外壳和非法注册表配置必须明确失败；用户可修正的参数或语义问题返回 `NEED_CLARIFICATION`。
- 当前仓库没有基线提交，全部现有文件都未被跟踪。未经用户明确授权，不创建初始提交，也不暂存无关文件；使用测试检查点代替任务提交。

## 重点复核项

- ASCII 数字字符串规范化器不能误接收带符号、小数、布尔值、纯空白或 Unicode 数字形式的 ID；任务 1 分别覆盖这些输入。
- 只有一个已提取查询条件时，普通文本中的“或/or”不能被误判为 OR 查询；任务 3 覆盖该误报边界。
- 同时包含一个合法字段和一个非法字段时，必须保留合法字段并要求修正非法字段；任务 2 覆盖部分校验。
- 意图参数模型与工具参数模型必须在共享字段的类型、范围以及 email、phone 格式上保持一致；任务 2 增加一致性测试。
- 连续直接调用意图模块时，Trace 快照不能相互泄漏；完整 `run()` 不能创建第二套意图 Trace；任务 4 覆盖这两种行为。

---

### 任务 1：搭建通用契约框架

**文件：**
- 新建：`src/minimal_agent/intent_contracts.py`
- 新建：`tests/test_intent_contracts.py`
- 修改：`src/minimal_agent/model_client.py`

**接口：**
- 产出：`IntentContractError(IntentModuleError)`。
- 产出：`IntentDefinition`、`IntentRegistry`、`ParameterNormalizer`、`SemanticConstraint`、`CompletionPolicy`。
- 产出：`IntegerStringNormalizer`、`TrimStringNormalizer`、`RequiredFields`、`AtLeastOneFieldGroup`、`ExactlyOneFieldGroup`、`MutuallyExclusiveFields`、`ReadIntentPolicy`、`WriteIntentPolicy` 和 `UnsupportedIntentPolicy`。
- 产出：`IntentRegistry.validate(user_input: str, candidate: IntentResult, *, trace: TraceCollector | None = None) -> IntentResult`。
- 契约：意图参数模型使用可选字段支持部分提取；注册表逐字段执行 Pydantic 校验，保留独立合法的字段，并把规范缺参名称交给决策策略。

- [ ] **步骤 1：编写注册表生命周期失败测试**

增加以下测试：

```python
def test_registry_rejects_duplicate_intent_definition(): ...
def test_registry_rejects_unknown_intent(): ...
def test_registry_rejects_definition_with_contradictory_configuration(): ...
```

断言明确的 `IntentContractError` 信息能够指出对应意图和配置错误。

- [ ] **步骤 2：运行生命周期测试并确认处于 RED**

执行：`.venv/bin/pytest -q tests/test_intent_contracts.py -k 'registry'`

预期：测试收集阶段失败，因为 `minimal_agent.intent_contracts` 尚不存在。

- [ ] **步骤 3：实现注册表类型和生命周期校验**

实现上述接口。定义保持不可变；拒绝重复名称；注册时拒绝缺少策略、缺少模型或配置不兼容的定义。

- [ ] **步骤 4：运行生命周期测试并确认处于 GREEN**

执行：`.venv/bin/pytest -q tests/test_intent_contracts.py -k 'registry'`

预期：全部选中测试通过。

- [ ] **步骤 5：编写可复用规范化器和约束的失败测试**

增加以下测试：

```python
def test_integer_string_normalizer_converts_ascii_digits_only(): ...
def test_integer_string_normalizer_rejects_signed_decimal_boolean_and_unicode_digits(): ...
def test_trim_string_normalizer_trims_declared_fields_only(): ...
def test_required_fields_reports_canonical_missing_names(): ...
def test_at_least_one_and_exactly_one_groups_are_reusable(): ...
def test_mutually_exclusive_fields_reports_conflicting_fields(): ...
def test_read_write_and_unsupported_policies_choose_canonical_state(): ...
```

整数测试必须覆盖 `"9075333"`、`" 9075333 "`、`"-7"`、`"9.5"`、`True` 和全角数字。只有经过明确去空白处理的 ASCII 数字字符串可以转换为整数。

- [ ] **步骤 6：运行可复用组件测试并确认处于 RED**

执行：`.venv/bin/pytest -q tests/test_intent_contracts.py -k 'normalizer or required or group or mutually or policies'`

预期：测试失败，因为可复用组件行为尚未实现。

- [ ] **步骤 7：实现最小可复用组件**

规范化器返回复制后的字典和结构化公开变更记录。约束返回结构化通过/失败结果、规范缺参名称和公开原因。决策策略必须依据校验结果，而不是模型提出的状态。

- [ ] **步骤 8：运行任务 1 的全部测试**

执行：`.venv/bin/pytest -q tests/test_intent_contracts.py`

预期：全部测试通过且没有警告。

### 任务 2：注册全部现有意图并对齐参数 Schema

**文件：**
- 修改：`src/minimal_agent/intent_contracts.py`
- 修改：`src/minimal_agent/shadow_schemas.py`
- 修改：`src/minimal_agent/__init__.py`
- 修改：`tests/test_intent_contracts.py`
- 修改：`tests/test_shadow_schemas.py`

**接口：**
- 依赖：任务 1 的注册表、规范化器、约束和决策策略接口。
- 产出：`build_default_intent_registry() -> IntentRegistry`。
- 产出：每个公共意图对应一个支持部分提取的严格 Pydantic 参数模型。
- 产出：由 query-user 意图参数和 `QueryUserInfoArguments` 共同使用的 email、phone 类型注解。
- 契约：`build_default_intent_registry()` 必须恰好注册当前 `IntentResult.intent` 的九个字面量。

- [ ] **步骤 1：编写注册覆盖失败测试**

增加：

```python
def test_default_registry_contains_every_public_intent_literal(): ...
def test_each_definition_has_a_nonempty_contract_version(): ...
def test_read_write_and_unsupported_intents_use_the_expected_policy(): ...
```

断言没有遗漏 legacy 或 shadow 意图，也没有增加未识别意图。

- [ ] **步骤 2：编写共享参数契约失败测试**

覆盖：

```python
def test_query_user_accepts_positive_integer_ids_valid_email_and_phone(): ...
def test_query_user_rejects_invalid_email_shapes(): ...
def test_query_user_rejects_non_eleven_digit_phone_values(): ...
def test_query_user_preserves_valid_phone_when_user_id_is_invalid(): ...
def test_query_user_requires_at_least_one_condition(): ...
def test_query_gift_and_query_pool_enforce_exactly_one_lookup_mode(): ...
def test_write_intents_require_environment_and_selection_fields(): ...
def test_intent_and_tool_models_share_query_user_field_constraints(): ...
```

Email 非法值包括：`example.com`、`@example.com`、`a@` 和 `a@@example.com`。Phone 非法值包括：10 位数字、12 位数字、包含字母、包含符号，以及以 JSON 整数提供的号码。

- [ ] **步骤 3：运行任务 2 测试并确认处于 RED**

执行：`.venv/bin/pytest -q tests/test_intent_contracts.py tests/test_shadow_schemas.py`

预期：新增测试失败，因为默认注册表和共享 email、phone 约束尚不存在。

- [ ] **步骤 4：实现共享类型注解和全部默认意图定义**

使用严格可选字段支持部分提取。字段校验与可复用的完整性约束分开执行。保持现有默认值和模式：query-user 多字段按 AND 组合，query-gift/query-pool 查询模式保持互斥，完整写意图使用 `WriteIntentPolicy`。

- [ ] **步骤 5：只导出稳定的公共注册表接口**

在 `minimal_agent.__init__` 中导出 `IntentContractError`、`IntentDefinition`、`IntentRegistry` 和 `build_default_intent_registry`。除非现有代码确实需要，否则各意图内部参数模型保持私有。

- [ ] **步骤 6：运行任务 2 测试并确认处于 GREEN**

执行：`.venv/bin/pytest -q tests/test_intent_contracts.py tests/test_shadow_schemas.py`

预期：全部选中测试通过。

### 任务 3：将契约接入 IntentRouter 并保护查询语义

**文件：**
- 修改：`src/minimal_agent/intent_router.py`
- 修改：`src/minimal_agent/intent_contracts.py`
- 修改：`src/minimal_agent/prompts.py`
- 修改：`tests/test_intent_router.py`
- 新建：`tests/test_query_user_intent_contract.py`
- 修改：`tests/test_openai_client.py`
- 修改：`tests/test_deepseek_client.py`

**接口：**
- 依赖：任务 2 的 `build_default_intent_registry()` 和 `IntentRegistry.validate(...)`。
- 产出：`IntentRouter(model_client: ModelClient, intent_registry: IntentRegistry | None = None)`。
- 产出：`IntentRouter.run_intent_only(user_input: str, *, trace: TraceCollector | None = None) -> IntentResult`。
- 保持：模块级 `run_intent_only(user_input: str, model_client: ModelClient) -> IntentResult`。
- 契约：先把模型输出解析为合法 `IntentResult` 候选，再由注册表校验生成规范结果。

- [ ] **步骤 1：为报告中的五个案例编写回归测试并固定规范结果**

使用与已观察输出一致的 `ScriptedModelClient` 候选，并增加：

```python
def test_explicit_user_id_string_is_normalized_to_integer(): ...
def test_bare_eleven_digit_number_remains_phone(): ...
def test_zero_user_id_requests_clarification(): ...
def test_and_query_normalizes_id_and_preserves_phone(): ...
def test_or_query_is_not_converted_to_and(): ...
```

对于 OR，断言结果为 `NEED_CLARIFICATION`、`ASK_USER`、`{}`、`["single_user_query_condition"]`，且公开原因同时包含“不支持”和“一次”。

- [ ] **步骤 2：增加语义边界测试**

增加：

```python
def test_explicit_batch_query_requests_single_entity(): ...
def test_two_different_fields_without_or_remain_and_query(): ...
def test_or_word_without_two_extracted_conditions_does_not_false_positive(): ...
def test_invalid_email_and_phone_candidates_request_correction(): ...
def test_candidate_status_is_recomputed_from_contract(): ...
```

误报测试必须在普通文本中包含“或者”，但只提取到一个查询条件，并且不能触发 `single_user_query_condition`。

- [ ] **步骤 3：运行路由和 query-user 测试并确认处于 RED**

执行：`.venv/bin/pytest -q tests/test_intent_router.py tests/test_query_user_intent_contract.py`

预期：报告回归测试和决策重算测试在当前透传路由上失败。

- [ ] **步骤 4：实现路由接入和可复用语义约束**

先按照当前方式解析候选，再调用注册表。`DisallowAlternativeQuery` 必须同时检测到明确 OR 连接词和至少两个已提取查询字段。`DisallowBatchQuery` 必须同时检测到明确的复数/分别查询语义和多个已提取值或实体。两种实现都不得匹配完整固定评测句子。

- [ ] **步骤 5：增强意图 Prompt，但不嵌入评测答案**

在 Prompt 中说明 JSON 类型、正整数 ID、email/phone 格式、AND 语义，以及禁止静默转换 OR/批量请求。Prompt 保持通用，不改变公开原因要求，并递增 `INTENT_PROMPT_VERSION`。

- [ ] **步骤 6：更新旧候选状态与新契约冲突的现有路由测试**

只包含 `environment` 的 JSON 响应测试现在必须因为缺少 `resource_type` 而断言 `NEED_CLARIFICATION`；不能为了保留旧的透传预期而削弱契约。

- [ ] **步骤 7：运行路由和模型客户端测试并确认处于 GREEN**

执行：`.venv/bin/pytest -q tests/test_intent_router.py tests/test_query_user_intent_contract.py tests/test_openai_client.py tests/test_deepseek_client.py`

预期：全部选中测试通过，两个真实模型客户端适配器继续使用相同的公共 `IntentResult` 模型边界。

### 任务 4：在不改变公共结果的前提下增加意图校验 Trace

**文件：**
- 修改：`src/minimal_agent/intent_contracts.py`
- 修改：`src/minimal_agent/intent_router.py`
- 修改：`src/minimal_agent/agent.py`
- 修改：`tests/test_intent_router.py`
- 修改：`tests/test_shadow_agent_integration.py`
- 新建：`tests/test_intent_trace.py`

**接口：**
- 依赖：任务 3 增加的可选 `TraceCollector` 参数。
- 产出：`MinimalAgent.intent_trace_snapshot() -> list[dict[str, Any]]`。
- 保持：调用方继续使用 `MinimalAgent.run_intent_only(user_input: str) -> IntentResult`。
- 契约：直接执行意图模块时创建一个私有 Trace 并替换上一次快照；`run()` 提供已有 Trace，不能创建嵌套运行或重复 Trace。

- [ ] **步骤 1：编写契约事件失败测试**

增加：

```python
def test_intent_trace_records_candidate_definition_normalization_and_decision(): ...
def test_validation_failure_trace_names_public_field_without_hidden_reasoning(): ...
def test_semantic_constraint_failure_trace_records_no_expected_or_case_id(): ...
```

断言事件顺序稳定，并且 payload 字段不包含 `thought`、`reasoning`、`chain_of_thought`、`expected`、`score` 和 `case_id`。

- [ ] **步骤 2：编写 Agent Trace 生命周期失败测试**

增加：

```python
def test_direct_intent_calls_replace_instead_of_append_last_trace_snapshot(): ...
def test_full_run_contains_one_intent_validation_sequence(): ...
def test_intent_trace_snapshot_returns_defensive_copies(): ...
```

- [ ] **步骤 3：运行 Trace 测试并确认处于 RED**

执行：`.venv/bin/pytest -q tests/test_intent_trace.py tests/test_shadow_agent_integration.py -k 'intent or trace'`

预期：测试失败，因为注册表事件和 `intent_trace_snapshot()` 尚不存在。

- [ ] **步骤 4：发送契约事件并接入 Trace 收集器**

发送设计文档中冻结的事件名称。直接调用 `run_intent_only()` 时使用 Agent 的 run-ID 工厂创建 Trace、保存导出副本，并且只返回结果。`run()` 把已有收集器传给路由器，不修改直接调用生成的快照。

- [ ] **步骤 5：运行 Trace 和集成测试并确认处于 GREEN**

执行：`.venv/bin/pytest -q tests/test_intent_trace.py tests/test_intent_router.py tests/test_shadow_agent_integration.py`

预期：全部选中测试通过。

### 任务 5：更新契约文档并验证完整项目

**文件：**
- 修改：`PROJECT_SPEC.md`
- 修改：`README.md`
- 仅当实现暴露出经过复核的命名修正时修改：`docs/superpowers/specs/2026-10-07-intent-contract-registry-design.md`
- 测试：全部 `tests/`

**接口：**
- 依赖：任务 1 至任务 4 的全部接口。
- 产出：面向使用者的注册表职责、参数校验、不支持语义和 Trace 访问文档。
- 产出：最终验证证据；不新增运行时接口。

- [ ] **步骤 1：更新 PROJECT_SPEC 和 README**

记录以下内容：

- 模型候选与规范意图决策的区别；
- 全部已注册意图使用相同注册表流程；
- query-user 的 ID、email、phone、AND、OR 和批量规则；
- 意图 Schema 与工具 Schema 的职责边界；
- `intent_trace_snapshot()` 的用法及其不包含推理的内容；
- 未来意图如何在不修改路由控制流的情况下增加参数模型和 `IntentDefinition`。

- [ ] **步骤 2：运行格式和静态检查**

执行：`.venv/bin/ruff check .`

预期：退出码为 0，没有诊断信息。

- [ ] **步骤 3：运行完整离线测试套件**

执行：`.venv/bin/pytest -q`

预期：全部测试通过，不运行需要显式启用的付费 API 冒烟测试，也不产生警告。

- [ ] **步骤 4：重新运行重点回归测试套件**

执行：`.venv/bin/pytest -q tests/test_query_user_intent_contract.py tests/test_intent_contracts.py tests/test_intent_trace.py`

预期：全部重点回归测试通过。

- [ ] **步骤 5：检查最终工作区**

执行：`git status --short`

预期：只有本计划列出的文件以及原本已存在的未跟踪项目文件；没有修改 evaluator 或 dataset-builder 文件。
