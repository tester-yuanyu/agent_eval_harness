# mini_agent 评测集生产框架和意图识别数据集生成约束

你需要新建一个独立、可复用的评测集生产框架，并使用它生成第一份 mini_agent 意图识别模块评测集。框架必须能在后续通过新增 Suite Definition 生成 Link、End to End、异常和安全评测集，不能写成一次性的意图数据脚本。

本任务包含两个交付目标：

1. 建设 Dataset Authoring Framework，完成生成请求组装、模型调用或外部响应导入、候选解析、编译、校验、覆盖分析、人工审核和冻结；
2. 使用该框架生成并冻结 15 条 mini_agent Shadow 意图识别 Module 案例，使现有 `agent_evaluator` 可以直接加载和校验。

完整链路为：

```text
能力契约 + EvalCase Schema + Suite 定义 + Coverage Plan
→ 构建生成请求
→ 模型生成语义候选
→ 候选协议校验
→ Suite Compiler 编译 EvalCase
→ agent_evaluator 结构与语义校验
→ 覆盖、重复、泄漏和质量检查
→ 人工审核
→ 冻结 JSONL、Manifest 和 Coverage Report
```

框架不得执行被测 Agent，不得根据 Agent 实际回答修改 expected，不得把未经审核的候选集标记为正式评测集。

## 一 项目和资料地址

### 1 新建生产框架

在以下路径新建独立项目：

```text
/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder
```

依赖方向固定为：

```text
agent_dataset_builder → agent_evaluator
agent_dataset_builder → mini_agent 公开能力契约
```

禁止 `agent_evaluator` 或 `mini_agent` 反向依赖 builder。目标目录若已存在，先阅读并保留已有无关文件。不要擅自初始化 Git、创建远端仓库、提交代码或配置 CI。

### 2 已有评测框架

评测执行框架位于：

```text
/Users/yuanyu/Documents/ChatGPT/agent_evaluator
```

开始实现前必须阅读：

```text
README.md
pyproject.toml
schemas/eval_case.schema.json
src/eval_framework/schemas.py
src/eval_framework/dataset_loader.py
src/eval_framework/dataset_validator.py
src/eval_framework/assertions.py
datasets/fixtures/
tests/
```

以上路径均相对于 `agent_evaluator`。生产框架必须复用其公开 `EvalCase`、`load_dataset()` 和 `validate_dataset()`，不能复制或重新实现另一套 EvalCase 协议。

除本文允许新增冻结数据集文件外，不得修改 evaluator 的源码、Schema、Fixture、断言或测试。发现 evaluator 问题时记录复现和影响，不得在 builder 中伪造兼容结果。

### 3 被测 Agent

被测 Agent 位于：

```text
/Users/yuanyu/Documents/ChatGPT/mini_agent
```

开始实现前必须阅读：

```text
PROJECT_SPEC.md
README.md
src/minimal_agent/schemas.py
src/minimal_agent/prompts.py
src/minimal_agent/shadow_schemas.py
src/minimal_agent/tool_registry.py
AUTOMATED_EVALUATION_TECHNICAL_PLAN.md
PHASE1_EVALUATION_FRAMEWORK_BUILD_CONSTRAINTS.md
```

允许读取公开协议和实现以核对意图、状态、参数与工具能力。实际发送给生成模型的 Source Pack 只能包含整理后的能力契约、EvalCase Schema、Coverage Plan 和生成规则，不得包含 mini_agent 测试、Scripted 响应、Agent 实际运行结果或 evaluator Fixture 标准答案。

不得修改 mini_agent。

## 二 建设目标

最终必须实现：

1. 独立、可测试、可扩展的评测集生产框架；
2. 简单显式的 Suite Definition 注册机制；
3. 人工外部模型模式：生成 Prompt、导入原始响应；
4. OpenAI Responses API 自动生成模式；
5. 严格候选协议和全部原始产物留存；
6. 候选到 evaluator EvalCase 的确定性编译；
7. 直接调用 evaluator 的结构和语义校验；
8. Coverage、Duplicate、Leakage、Quality Gate；
9. DRAFT、VALIDATED、APPROVED、FROZEN 生命周期；
10. Manifest、Validation Report、Coverage Report 和 Review 文档；
11. 首个 `mini_agent_intent_v1` Suite；
12. 15 条冻结 Module 案例；
13. 冻结 JSONL 可被 evaluator CLI 直接 validate；
14. 后续新增 Suite 不修改公共生产流水线。

## 三 技术栈和依赖

必须使用：

- Python 3.11+；
- Pydantic v2；
- Pytest；
- Ruff；
- OpenAI Python SDK 和 Responses API；
- `argparse`、`json`、`pathlib`、`hashlib`、`datetime`、`uuid`；
- `pyproject.toml`。

可以 editable 安装本地 `agent_evaluator` 和 `mini_agent`。不得复制它们的源码。

不得擅自引入 LangChain、AgentLite、CrewAI、ORM、数据库服务、Web/前端框架、消息队列、分布式任务系统、Pandas、YAML 依赖、Judge 或向量数据库。新增依赖前必须获得用户确认。

## 四 工程结构

建议结构：

```text
agent_dataset_builder/
├── pyproject.toml
├── README.md
├── .env.example
├── src/dataset_builder/
│   ├── __init__.py
│   ├── schemas.py
│   ├── suite_definition.py
│   ├── source_pack.py
│   ├── prompt_builder.py
│   ├── generation_client.py
│   ├── candidate_parser.py
│   ├── compiler.py
│   ├── validation.py
│   ├── coverage.py
│   ├── leakage.py
│   ├── freezing.py
│   └── cli.py
├── suites/mini_agent_intent_v1/
│   ├── capability_contract.md
│   ├── generation_policy.md
│   ├── coverage_plan.json
│   └── seed_catalog.json
├── schemas/module_intent_candidate.schema.json
├── workspaces/.gitkeep
└── tests/
```

后续 Suite 只新增 Suite Definition、能力契约、Coverage Plan、候选协议和 Compiler，不复制公共模型客户端、校验器或冻结器。

## 五 公共架构

### 1 固定流水线

```text
load_suite_definition
→ build_source_pack
→ build_generation_request
→ generate 或 ingest_external_response
→ parse_candidates
→ compile_eval_cases
→ evaluator_schema_validation
→ evaluator_semantic_validation
→ coverage_validation
→ duplicate_validation
→ leakage_validation
→ quality_validation
→ write_review_artifacts
→ explicit_approval
→ freeze_dataset
```

公共流水线不得包含针对固定 case_id、固定用户输入或当前模型行为的分支。

### 2 Suite Definition

每个 Suite Definition 至少提供：

- suite_id、dataset_version、target_agent、test_scope、target；
- Source Pack 列表；
- Coverage Plan；
- 候选 Pydantic 类型；
- Prompt 模板；
- Candidate Compiler；
- Suite 特有校验器；
- evaluator 断言策略；
- 建议冻结路径。

使用简单显式注册表：

```text
mini_agent_intent_v1 → MiniAgentIntentSuiteDefinition
```

不要实现动态插件发现或复杂依赖注入。

### 3 首个 Suite

```text
suite_id: mini_agent_intent_v1
dataset_version: 1.0
target_agent: mini_agent
test_scope: module
target: intent_router
```

第一版只覆盖 Shadow 意图：

```text
query_user
query_gift
query_pool
add_backpack_gift
unsupported
```

Legacy 的 `query_information` 和 `prepare_resource` 后续作为独立 Suite，不混入本数据集。

## 六 Generation Client

### 1 公共协议

定义：

```python
class GenerationClient(Protocol):
    def generate(self, request: GenerationRequest) -> RawGeneration:
        ...
```

公共流水线只能依赖该协议。

### 2 人工外部模型模式

必须支持：

1. `prepare` 生成完整 Prompt 和 Request Manifest；
2. 用户把 Prompt 发给外部模型；
3. 用户把原始响应保存为文件；
4. `ingest` 导入响应；
5. 进入与自动模式相同的解析、编译、校验和冻结流程。

人工模式不得跳过原始响应保存或任何 Gate。

### 3 OpenAI 自动模式

- 使用 Responses API；
- API Key 只读 `OPENAI_API_KEY`；
- 模型只读 `DATASET_GENERATOR_MODEL`；
- 不硬编码模型和密钥；
- 不提供 CLI API Key 参数；
- 设置明确超时；
- 重试必须有限、显式且有记录；
- 保存模型名、Prompt 版本、时间和原始响应；
- 默认 Pytest 不联网、不产生费用；
- 真实生成必须由显式命令触发。

### 4 严格候选协议

不要让模型直接输出完整 EvalCase。模型只输出语义候选，固定样板由 Compiler 注入。

首个 Suite 的 `ModuleIntentCandidate` 包含：

```text
slot_id
user_input
expected_intent
expected_status
expected_next_action
expected_parameters_json
missing_parameters
scenario_type
difficulty
coverage_tags
```

规则：

- slot_id 必须来自 Coverage Plan；
- expected_parameters_json 必须能解析为 JSON object；
- intent、status、next_action、scenario_type 和 difficulty 使用严格枚举；
- difficulty 只允许 easy、medium；
- 不让模型输出 reason、断言权重、tool_profile、cleanup 或 case_id；
- 不要求模型输出思维过程或评分理由。

批次模型 `GeneratedIntentBatch` 的所有属性 required，所有 object 设置 `additionalProperties=false`，用于 Responses API Strict Structured Output。实现时以 [OpenAI Structured Outputs 官方文档](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses) 为准；模型或 SDK 不支持时必须明确失败，不能从自然语言猜测案例。

## 七 Source Pack

首个 Source Pack 只包含：

1. Shadow 意图能力契约；
2. IntentResult 状态机；
3. 参数、必填条件、互斥规则和默认语义；
4. EvalCase Schema 摘要；
5. evaluator 支持的 Module 断言；
6. Coverage Plan；
7. 生成规则；
8. 一个只展示格式、不复用正式输入的非黄金示例。

不得包含：

- mini_agent 测试；
- evaluator Fixture 输入和 Scripted 响应；
- Agent 实际运行结果；
- 历史 PASS/FAIL；
- 为提高当前 Agent 分数而设计的答案；
- API Key；
- 其他正式 Benchmark 标准答案。

每个 Source Pack 文件计算 SHA-256 并写入 Manifest。

## 八 意图能力契约

### 1 IntentResult

expected_module_output 必须包含：

```text
intent
status
next_action
parameters
missing_parameters
reason
```

状态机：

```text
READY              → CALL_TOOL
NEED_CLARIFICATION → ASK_USER
NEED_CONFIRMATION  → ASK_CONFIRMATION
REJECTED           → REJECT
```

READY 和 NEED_CONFIRMATION 的 missing_parameters 为空；NEED_CLARIFICATION 必须非空；unsupported 使用 REJECTED。reason 不评分。

### 2 query_user

查询条件为 `user_id`、`room_id`、`email`、`phone`，至少一个；多条件表示 AND。

### 3 query_gift

支持 `gift_id`、`gift_ids`、`gift_name` 三种互斥模式。第一版只生成边界明确的单一模式，不生成冲突模式。

### 4 query_pool

支持 `pool_id` 或 `gift_id` 两种互斥模式。第一版不生成冲突模式。

### 5 add_backpack_gift

完整写意图需要：

- `user_id` 或 `user_ids`；
- `gift_id`、`gift_ids` 或 `gift_nums`；
- 明确 environment；
- 用户明确给出 num、duration_days 时正确提取；
- duration_days 为 1 至 1000，1000 表示永久。

完整写意图返回 NEED_CONFIRMATION；缺少必要参数返回 NEED_CLARIFICATION。不得生成 request_id、confirmation_id、session_id、run_id 或 internal_version。

### 6 unsupported

```text
intent: unsupported
status: REJECTED
next_action: REJECT
parameters: {}
missing_parameters: []
```

输入必须明显超出能力范围，不使用业务边界模糊请求。

## 九 Coverage Plan

冻结数据集固定 11 条，每个 Coverage Slot 恰好一个候选：

| 覆盖类别 | 数量 |
| --- | ---: |
| query_user READY | 2 |
| query_user NEED_CLARIFICATION | 1 |
| query_gift READY | 2 |
| query_gift NEED_CLARIFICATION | 1 |
| query_pool READY | 1 |
| query_pool NEED_CLARIFICATION | 1 |
| add_backpack_gift NEED_CONFIRMATION | 1 |
| add_backpack_gift NEED_CLARIFICATION | 1 |
| unsupported REJECTED | 1 |

状态分布固定为：

```text
READY: 5
NEED_CLARIFICATION: 4
NEED_CONFIRMATION: 1
REJECTED: 1
```

中文输入至少包含正式表达和自然口语。第一版不包含 Legacy、工具执行、故障注入、Prompt Injection、多轮补参、多意图复合、查询模式冲突、依赖 SQLite 终态或实时知识的案例。

## 十 Candidate Compiler

### 1 固定 EvalCase 模板

Compiler 注入：

```text
schema_version: 1.0
test_scope: module
target: intent_router
execution.tool_profile: shadow_full
execution.allowed_tools: null
execution.fault_injection: {}
execution.max_steps: 4
execution.timeout_seconds: 30.0
oracle.expected_agent_status: null
oracle.expected_tool_calls: []
oracle.forbidden_tools: []
oracle.goal_state: null
oracle.process_constraints: {}
oracle.expected_response: null
cleanup: null
```

候选提供 user_input、意图决策、parameters、missing_parameters 和标签语义。

### 2 Case ID 和 Task ID

Compiler 按 Coverage Plan 顺序生成：

```text
MINI-INTENT-001 至 MINI-INTENT-011
```

模型不得生成 case_id。task_id 映射：

```text
query_user               → intent-query-user
query_gift               → intent-query-gift
query_pool               → intent-query-pool
add_backpack_gift        → intent-add-backpack-gift
unsupported              → intent-unsupported
```

### 3 写意图兼容字段

当前 evaluator 会对 Module 写意图要求 `user_responses` 和 `cleanup`。因此 add_backpack_gift 案例由 Compiler 注入：

```json
"user_responses": ["确认"],
"cleanup": {
  "required": true,
  "strategy": "temporary_directory"
}
```

这些字段只满足当前 EvalCase 语义校验，`run_intent_only()` 不会执行它们。不得放入 user_input 或 expected parameters。

### 4 固定断言策略

每条案例统一使用：

```json
[
  {"name":"output_schema_valid","weight":10,"critical":true,"config":{}},
  {"name":"intent_match","weight":30,"critical":true,"config":{}},
  {"name":"status_match","weight":20,"critical":true,"config":{}},
  {"name":"next_action_match","weight":10,"critical":true,"config":{}},
  {"name":"params_match","weight":20,"critical":true,"config":{}},
  {"name":"missing_params_match","weight":10,"critical":true,"config":{}}
]
```

params_match 使用完整、类型敏感的精确匹配，不启用 expected_subset。能力契约无法给出唯一参数表示时，拒绝该案例或移出 V1，不通过放宽断言掩盖歧义。

### 5 Reason 和标签

reason 由 Compiler 固定为：

```text
Expected decision defined by the benchmark contract.
```

标签至少包含：

```text
mini_agent
module
intent_understanding
shadow
bootstrap_generated
对应 intent
对应 status
scenario_type
difficulty
```

## 十一 参数和缺参规范

- 整数使用 JSON number，不能使用数字字符串；
- null 使用 JSON null；
- 列表保持用户输入顺序；
- 参数名必须来自公开协议；
- 不得生成执行层字段；
- READY 和 NEED_CONFIRMATION 包含完整规范参数；
- NEED_CLARIFICATION 保留已提供参数，只列真正缺失字段；
- unsupported parameters 固定 `{}`；
- 不猜测用户未表达的 ID、环境、数量和期限。

missing_parameters 必须在 `capability_contract.md` 冻结规范名称。对于复合选择条件，可以使用：

```text
user_id_or_room_id_or_email_or_phone
gift_id_or_gift_ids_or_gift_name
pool_id_or_gift_id
user_id_or_user_ids
gift_id_or_gift_ids_or_gift_nums
```

若 mini_agent 公开协议没有冻结唯一复合名称，应明确标注这是 Benchmark 约定，不得声称是代码强制规则。全部案例必须使用同一套名称。

## 十二 校验 Gate

### 1 Candidate Schema Gate

- 批次和候选通过 Pydantic；
- slot_id 唯一且都在 Coverage Plan；
- 每个 slot 恰好一条；
- parameters JSON 可解析为 object；
- 无额外字段；
- 枚举和类型正确。

### 2 Contract Gate

- intent、status、next_action 一致；
- 必填和缺参规则一致；
- 完整写意图为 NEED_CONFIRMATION；
- unsupported 为 REJECTED；
- 参数不含执行字段。

### 3 Evaluator Gate

Compiler 写入临时 JSONL 后必须直接调用：

```python
bundle = load_dataset(draft_path)
report = validate_dataset(bundle)
```

必须满足：加载成功、`report.valid is True`、案例数为 15、schema_version 为 1.0。不得复制 evaluator 的校验结果。

### 4 Coverage Gate

验证 15 个 slot、意图分布和状态分布完全符合 Coverage Plan，没有 Legacy 或计划外场景。

### 5 Duplicate Gate

检查 case_id、slot_id、输入完全重复、规范化输入近重复，以及只有无意义措辞变化的重复案例。近重复只报告，不自动删除。

### 6 Leakage Gate

序列化 execution 后不得出现：

```text
expected oracle goal_state answer score assertion golden rubric case_id
```

同时检查 user_input 不包含答案提示、expected JSON 或评分指令，Frozen 文件不包含生成模型隐藏推理。

### 7 Quality Gate

- 输入自然明确；
- 每个案例只验证一个主要决策；
- expected 可由契约唯一推出；
- 不依赖实时信息和 SQLite 终态；
- 不含真实个人信息、密钥或生产数据；
- 不根据当前 Agent 能否通过调整 expected。

任一 Gate 失败都不能冻结。

## 十三 生命周期和审核

状态：

```text
DRAFT → VALIDATED → APPROVED → FROZEN
```

- 所有自动 Gate 通过才能 VALIDATED；
- 人工检查 Coverage Report、Review 文档和全部案例并填写 reviewer 后才能 APPROVED；
- Freeze 校验输入 hash、reviewer 和版本后才能 FROZEN；
- 框架不得自动声称人工审核完成；
- Frozen 内容变化必须生成新版本和新 hash，不能原地覆盖。

## 十四 产物

每次生成运行保存：

```text
workspaces/generation_run_xxx/
├── generation_request.json
├── prompt.md
├── source_manifest.json
├── raw_response.json
├── candidates.json
├── draft.jsonl
├── validation_report.json
├── coverage_report.json
├── duplicate_report.json
├── leakage_report.json
├── review.md
└── generation_manifest.json
```

冻结产物写入：

```text
/Users/yuanyu/Documents/ChatGPT/agent_evaluator/datasets/mini_agent/module_intent_v1.jsonl
/Users/yuanyu/Documents/ChatGPT/agent_evaluator/datasets/mini_agent/module_intent_v1.manifest.json
/Users/yuanyu/Documents/ChatGPT/agent_evaluator/datasets/mini_agent/module_intent_v1.coverage.json
```

本文只授权在 evaluator 的 `datasets/mini_agent/` 新增上述产物，不授权修改 evaluator 代码。

Manifest 至少记录 suite、版本、状态、文件 hash、案例数、生成模式、模型名、Prompt 版本/hash、Source Pack hash、EvalCase Schema hash、evaluator 版本、Coverage Plan hash、时间、校验结果、reviewer 和批准时间。不得记录 API Key 或隐藏推理。

## 十五 CLI 和 Python 接口

### 1 CLI

至少提供：

```bash
python -m dataset_builder.cli prepare --suite mini_agent_intent_v1 --workspace PATH
python -m dataset_builder.cli generate --request PATH/generation_request.json --workspace PATH
python -m dataset_builder.cli ingest --request PATH/generation_request.json --response PATH/raw_response.json --workspace PATH
python -m dataset_builder.cli validate --suite mini_agent_intent_v1 --draft PATH/draft.jsonl
python -m dataset_builder.cli review --suite mini_agent_intent_v1 --draft PATH/draft.jsonl --output PATH/review.md
python -m dataset_builder.cli freeze --suite mini_agent_intent_v1 --draft PATH/draft.jsonl --reviewer NAME --output PATH/module_intent_v1.jsonl
```

要求：prepare 不调用模型；generate 才调用 OpenAI；ingest 保留原始响应；validate 不修改 draft；review 不自动批准；freeze 只有全部 Gate 通过且 reviewer 非空时成功；失败返回非 0；CLI 不接受 API Key；默认不覆盖 Frozen 文件。

### 2 Python 接口

至少暴露：

```python
load_suite(suite_id)
prepare_generation(suite, workspace)
generate_candidates(request, client)
ingest_response(request, response_path)
compile_candidates(suite, raw_generation)
validate_draft(suite, draft)
build_review(suite, draft, reports)
freeze_dataset(suite, draft, approval, output_path)
```

具体名称可调整，但准备、生成、导入、编译、校验、审核和冻结必须分离。

## 十六 测试要求

默认测试完全离线，不调用真实 OpenAI、不执行被测 Agent、不修改 mini_agent 或 evaluator 代码。

至少覆盖：

### 1 协议和生成客户端

- 候选合法与非法字段；
- Strict Schema 所有字段 required、object 禁止额外属性；
- parameters JSON 非法或非 object；
- 枚举错误和 slot 重复；
- ScriptedGenerationClient 正常、超时、异常和非法输出；
- 人工 ingest 与 OpenAI generate 进入相同后续流程；
- 日志和产物不含 API Key。

### 2 Suite 和编译

- suite_id 注册和未知 suite；
- Source Pack 缺失与 hash；
- Coverage Plan 恰好 15 个 slot；
- case_id、task_id 和固定字段稳定；
- 写意图注入 user_responses 和 cleanup；
- reason、断言权重、critical 和标签正确；
- 不根据具体 user_input 或 case_id 特判 expected。

### 3 Gate

- evaluator load_dataset 和 validate_dataset 真实调用；
- 状态分布为 6、6、2、1；
- 意图覆盖符合计划；
- 重复和泄漏可发现；
- 缺少或多余 slot 不能冻结；
- Quality Gate 拒绝歧义 expected。

### 4 生命周期和冻结

- DRAFT 不能直接冻结；
- Gate 全过才能 VALIDATED；
- 无 reviewer 不能 APPROVED；
- 失败报告存在时不能 FROZEN；
- 现有 Frozen 路径默认不能覆盖；
- Manifest hash 与 JSONL 一致。

### 5 真实生成 Smoke

真实生成必须显式启用，例如 `RUN_DATASET_GENERATION_SMOKE=1`。模型读取 `DATASET_GENERATOR_MODEL`。缺少 Key 或模型名明确失败，不使用 fallback。

## 十七 禁止事项

不得：

- 修改 mini_agent 或 evaluator 源码；
- 复制 EvalCase 协议；
- 让模型决定断言权重、critical 或 case_id；
- 把 Agent 实际输出作为 expected；
- 运行 Agent 后自动修正答案；
- 根据 PASS 率删除案例；
- 把 expected 或评分规则放入 execution；
- 记录或要求隐藏推理；
- 根据 case_id 或固定输入写特殊逻辑；
- 静默修复非法候选；
- 自动删除近重复；
- 未经人工批准冻结；
- 覆盖已有 Frozen 版本；
- 默认测试调用真实 API；
- 实现 Judge、评测执行、Trial、CI、Dashboard 或 Web 服务；
- 提前实现 Link 或 End to End Suite。

只为未来 Suite 预留扩展接口，当前仅实现 `mini_agent_intent_v1`。

## 十八 工作方式

1. 先完整阅读本文列出的 evaluator 和 mini_agent 文件；
2. 先说明对现有 EvalCase、validator、断言和任务边界的理解；
3. 先实现公共框架，再实现首个 Suite；
4. 每完成一个模块运行对应测试；
5. 测试失败先定位并修复；
6. 不擅自增加依赖、目录和功能；
7. 先用 ScriptedGenerationClient 跑通离线全链路；
8. 再执行人工 ingest 或显式 OpenAI generate；
9. 冻结前展示 Coverage Report 和 Review；
10. 没有真实模型配置时明确报告未执行，不得伪造模型生成结果；
11. 不为提高 mini_agent 得分调整 expected；
12. 记录所有实际命令和结果。

建议顺序：

```text
项目骨架
→ 公共协议和 Suite Definition
→ Source Pack 和 Coverage Plan
→ Prompt Builder
→ GenerationClient 和离线客户端
→ prepare 与 ingest
→ OpenAI Responses Client
→ Candidate Parser 和 Compiler
→ evaluator Gate
→ Coverage、Duplicate、Leakage、Quality Gate
→ Review、Approval 和 Freeze
→ CLI 和测试
→ 显式生成并冻结首个数据集
```

## 十九 最终验收标准

- 项目位于 `/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder`；
- mini_agent 和 evaluator 源码未修改；
- 不复制 EvalCase；
- 支持 prepare、generate、ingest、validate、review、freeze；
- 支持离线客户端和 OpenAI Responses Client；
- 默认测试离线；
- 首个 Suite 通过显式注册表接入；
- 新增未来 Suite 不修改公共流水线；
- 15 个 Coverage Slot 全部覆盖；
- 候选和 EvalCase 都经过 Pydantic；
- 冻结前真实调用 evaluator loader 和 validator；
- 所有 Gate 通过；
- 冻结 JSONL 恰好 15 条；
- 状态分布为 READY 6、NEED_CLARIFICATION 6、NEED_CONFIRMATION 2、REJECTED 1；
- 正式产物位于 evaluator `datasets/mini_agent/`；
- evaluator CLI validate 成功；
- Manifest hash 正确；
- execution 无 expected 泄漏；
- 未根据 Agent 输出修改 expected；
- Pytest、Ruff 通过；
- README 包含人工模式、OpenAI 模式、审核、冻结和 Suite 扩展示例。

真实模型配置缺失时，必须把“框架完成”和“正式数据集未生成”分别报告，不能宣称全部完成。

## 二十 阶段结束报告

完成后必须报告：

1. 新建和修改文件；
2. 项目路径；
3. 公共流水线和 Suite 扩展机制；
4. Source Pack 和 hash；
5. Coverage Plan；
6. 候选协议和 Strict Schema；
7. Compiler 规则；
8. 生成模式和模型名；
9. 原始响应路径；
10. 各 Gate 结果；
11. Review 和 reviewer；
12. 冻结 JSONL、Manifest、Coverage Report 路径；
13. evaluator validate 命令和结果；
14. Pytest、Ruff 命令和结果；
15. 未完成项和风险；
16. 未来 Link、End to End、异常和安全 Suite 的接入方式。

必须提供可复核的文件、命令、hash、案例数、覆盖分布和真实校验结果，不能只描述代码结构。
