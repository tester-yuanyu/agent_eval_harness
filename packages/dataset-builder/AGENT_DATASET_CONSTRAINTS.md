# Agent 能力快照读取与评测集生成约束

本文保留 2026-10-13 整理的 v2 意图 Suite 生产约束；共享契约路径按当前仓库更新。规则以对应能力快照、Suite JSON、Policy 和 Coverage Plan 为准；v3 和独立全量生成入口的差异见 [README](README.md)。

本文用于指导能力包接入、候选生成、校验、审核和交付。**能力事实由快照确定，评测组织规则由 Suite 与 Policy 确定；模型生成候选，代码编译为评测案例，人工确认语义后才可冻结。**

下文“硬约束”表示当前代码直接校验；“生成／审核要求”表示需要生成模型遵守或人工复核，不代表已经存在完整自动判定器。本文为说明文档，运行时执行依据仍是代码和 JSON 配置。

## 1. 职责与评测边界

1. Builder 生产评测数据，不运行被测 Agent，不根据 Agent 实际回答反推标准答案。
2. 生成入口只使用完整 Capability Bundle，不依赖 Agent 源码、内部 Prompt、YAML、CLI 或 `capability_specs/`。
3. 快照经过可信校验与确定性 Adapter 转换为 Capability IR；Source Pack、候选编译和业务契约校验以 IR 为能力输入。
4. 当前内置编译器是 `compile_intent_candidates`，生成 `expected_module_output`。能力协议可描述 Scope、Chain 和 Tool，不表示当前编译器已实现通用端到端评测生成。
5. 理解层案例中的 `CALL_TOOL` 是预期决策标签，不能据此断言工具已经执行、返回正确结果或数据库终态正确。
6. 已声明支持的能力即使实际 Agent 做错，也应保留案例暴露差距；被选能力整体为 `unsupported` 或 `unknown` 时，当前编译器拒绝据此编译正向 Oracle。两者不能混淆。

代码依据：`source_pack.py`、`prompt_builder.py`、`intent_compiler.py`、`validation.py`。

## 2. 能力快照输入硬约束

### 2.1 入口与协议

- 输入必须是存在的目录，根入口固定为 `agent.json`，根类型必须为 `agent`。
- 当前内置可信 Profile 固定为 `capability-snapshot / 3.0`；Suite 不选择协议版本或 Adapter。
- 所有快照的 `snapshot_format_version` 必须一致且为 `"3.0"`。
- 支持的快照类型由 Profile 定义，包括 Agent、Scope、Chain、Module、Intent、Tool、Evidence、Boundary。
- 不依赖 `bundle_manifest.json`；加载器会跳过此文件。
- 加载器扫描包内 JSON，除 Schema 目录和上述特殊文件外，都按快照检查。不要混放生成响应、草案或其他业务 JSON。

### 2.2 可信 Schema 与完整性

- Profile 必须存在于 Builder 的 `trust_store.json`，其规范化 JSON Hash 必须与信任记录匹配。
- 包内 Schema 必须与 Profile 固定的**文件字节 SHA-256** 一致，不能由 Agent 自行替换成宽松 Schema。
- 各快照必须是 JSON object，通过对应 JSON Schema 校验；`snapshot_id` 全包唯一。
- 引用路径必须为安全相对路径，拒绝绝对路径、父目录跳转和反斜杠。
- 引用目标必须存在；引用中的 ID、类型、格式版本、契约版本和 Hash 均须与目标一致。
- 引用图必须无环；所有加载的快照必须可从 `agent.json` 沿引用到达，不允许孤立快照。
- 任一 Schema、Hash、引用、闭包或图结构校验失败，都直接拒绝能力包，不能降级成 `unknown` 后继续。

### 2.3 Hash 的准确含义

| 对象 | 当前计算规则 |
|---|---|
| 单快照 `snapshot_sha256` | 删除顶层自身 Hash 字段后，对排序键、紧凑分隔符、UTF-8 的规范化 JSON 求 SHA-256 |
| Bundle Hash | 取根快照的引用，投影为 ID、类型、格式版本、契约版本、路径、快照 Hash 六字段，按 ID 排序后求规范化 JSON SHA-256 |
| Schema、来源文件、草案 | 对文件字节求 SHA-256 |
| Capability IR | Adapter 构造确定性内容后，对不含自身 `canonical_sha256` 的对象求规范化 JSON SHA-256 |

Bundle Hash 不是目录打包后的 Hash。Agent 根 Hash、Schema Hash 和文件字节 Hash 另行保存，不能相互替代。

代码依据：`capability_profiles.py`、`capability_bundle.py`、`capability_adapters.py`。

## 3. 能力选择与支持状态

Suite 的 `capability_input` 必须提供 Bundle 路径、预期 Bundle Hash、`scope_or_chain_id`、`intent_id`，可选 `tool_id`。

- Suite 声明的 Bundle Hash 必须与实际值一致。
- 所选 Scope／Chain、Intent、Tool 必须存在且类型正确。
- 显式选择 Tool 时，其 `tool_name` 必须匹配 Intent 的 `required_tool_name`。
- IR 包含所选能力、必需条件、能力声明、Evidence、参数 Schema、决策规则、参数语义、语义规则及来源绑定。
- 对各必需条件解析 provider、claim 和所需 Evidence；整体支持状态只聚合 `mandatory=true` 的条件。

| 状态 | 解释与处理 |
|---|---|
| `supported` | 必需条件解析结果均支持；允许进入当前意图案例编译 |
| `unsupported` | 必需条件中存在显式不支持；需要所选工具但未选工具时也产生此状态 |
| `unknown` | 缺少可用 provider、能力声明或 Evidence 等，无法确定支持 |

聚合优先级为 `unsupported > unknown > supported`。Policy 不能把未知或不支持改成支持。这里的 Evidence 是快照声明的观测接口及可用性，不是 Builder 现场运行 Agent 获得的成功证据。

代码依据：`SuiteDefinition.capability_ir`、`CapabilityAdapter.convert`、`_resolve_requirements`。

## 4. Suite、Policy 与生成资料

Suite 负责装配元数据、文件路径、能力选择、执行 Profile 和六类 Policy。JSON 配置拒绝未声明字段；Policy 必须存在、类型与引用角色一致，并通过对应模型校验。

| Policy | 职责 |
|---|---|
| Source | 允许的来源根目录、保留未知状态、要求 Hash 绑定 |
| Coverage | 需要统计和精确匹配的覆盖分布 |
| Generation | 候选枚举、案例编号、标签、执行默认值、断言和固定 reason |
| Validation | 契约校验、状态规则、参数约束、质量规则、启用的 Gate |
| Review | 中文逐条审核及可展示字段 |
| Freeze | 禁止覆盖、复制冻结能力包、显式新版本约定 |

当前内核不允许关闭来源 Hash 绑定、逐条审核、冻结不覆盖和冻结能力包要求；未知能力必须保留，内置审核语言为 `zh-CN`。

Source Pack 实际内容为：**Capability IR + Suite 显式列出的来源文件**。三个专用 v2 Suite 使用 Generation JSON Policy 和 Coverage Plan；通用 `mini_agent_intent_v2` 使用 `generation_policy.md` 和 Coverage Plan。Markdown 被显式列入时可参与 Prompt，但不作为可执行 Policy；未列入的历史约束文档不会自动生效，seed catalog 也不会自动作为完整案例喂给生成模型。

生成／审核要求：不把历史 Agent 回答、PASS/FAIL、标准答案数据集、真实生产数据或隐藏推理混入出题资料。当前来源校验检查配置和来源根目录，并非能够自动识别所有数据污染的内容扫描器。

代码依据：`suite_definition.py`、`policies.py`、`source_pack.py`。

## 5. 模型输出：只允许语义候选

模型必须返回一个 JSON object，顶层为 `candidates` 数组。不允许 Markdown 代码块、解释文字、思维过程或多余字段。解析器不抽取正文中的 JSON，也不自动修复格式。

| 字段 | 约束 |
|---|---|
| `slot_id` | 非空；每个 Coverage Slot 恰好一条 |
| `user_input` | 非空自然语言；还须满足质量 Policy |
| `expected_intent` | Generation Policy 允许值，并与对应 Slot 相同 |
| `expected_status` | Generation Policy 允许值，并与对应 Slot 相同 |
| `expected_next_action` | Generation Policy 允许值；后续契约校验检查与状态的关系 |
| `expected_parameters_json` | **JSON 字符串**，解析结果必须是 object；不能直接传嵌套 object |
| `missing_parameters` | 字符串列表，具体允许名称受契约约束 |
| `scenario_type` | Generation Policy 允许的场景枚举 |
| `difficulty` | Generation Policy 允许的难度枚举 |
| `coverage_tags` | 字符串列表 |
| `rule_refs` | Policy 要求时必填且非空；Plan 指定时必须与其完全一致 |

候选 `slot_id` 集合必须与 Plan 完全一致，无缺失、额外或重复。原始响应的 `prompt_version` 必须与当前 Suite 一致。

模型不得输出 `case_id`、执行层标识符、`tool_profile`、cleanup、断言权重、评分理由或完整 EvalCase。这些字段由编译器根据 Policy 装配。

代码依据：`candidate_protocol.py`、`candidate_parser.py`、`prompt_builder.py`。

## 6. 编译与 Oracle 约束

编译器按 Coverage Plan 的 Slot 顺序生成案例；输入候选数组顺序不决定案例编号。案例固定使用 EvalCase Schema `1.0`，由共享契约包 `eval_contracts` 的 `EvalCase` 模型校验。

编译器注入：案例编号、任务 ID、评测目标、场景映射、标签、执行 Profile、工具许可、故障注入、步数与超时、预置回复、cleanup、固定 reason 和断言配置。

Oracle 的 `expected_module_output` 包含 `intent`、`status`、`next_action`、`parameters`、`missing_parameters`、`reason`。其中前五项主要来自候选，编译器并不通过运行 Agent 重新推导语义答案。

当前专用 v2 Suite 的状态约定：

| 场景 | 状态 | 下一步 |
|---|---|---|
| 读意图参数完整合法 | `READY` | `CALL_TOOL` |
| 缺参、非法或需要消歧 | `NEED_CLARIFICATION` | `ASK_USER` |
| 写意图参数完整、等待确认 | `NEED_CONFIRMATION` | `ASK_CONFIRMATION` |

参数校验依据 IR 的 `parameters_schema`，缺参名称依据 IR 的公开词表。是否省略 `null`、最少参数数量以及缺参列表是否必须为空，由具体 Validation Policy 决定，不应跨 Suite 套用旧文档规则。

代码依据：`intent_compiler.py`、`intent_validation.py`。

## 7. 当前 v2 覆盖基线与业务重点

下表来自当前 Coverage Plan，各 Suite 的目标数据集版本均为 `2.1`。数字属于当前配置，不是框架固定上限。

| Suite | 条数 | 状态分布 |
|---|---:|---|
| `mini_agent_query_user_intent_v2` | 42 | READY 25；NEED_CLARIFICATION 17 |
| `mini_agent_query_gift_intent_v2` | 23 | READY 13；NEED_CLARIFICATION 10 |
| `mini_agent_add_backpack_gift_intent_v2` | 28 | NEED_CONFIRMATION 12；NEED_CLARIFICATION 16 |
| `mini_agent_intent_v2` | 15 | READY 6；NEED_CLARIFICATION 6；NEED_CONFIRMATION 2；REJECTED 1 |

专用 Suite 覆盖正常表达、表达变体、有效边界、非法参数、缺参和多条件；QueryUser 另覆盖语义歧义、纠正冲突和不支持的批量请求。分布应以对应 `coverage_plan.json` 为准。

### QueryUser 用户查询

- `user_id`、`room_id` 为正整数；邮箱恰好一个 `@` 且两边非空；手机号为恰好 11 位 ASCII 数字字符串。
- 明确字段优先于值形态；裸整数不能直接猜作用户 ID。不同字段组合表示 AND。
- 明确纠正采用最终唯一值。当前快照将批量、OR、同字段多值定义为追问并清空参数；重复裸整数仍需消歧。
- 专用 v2 Policy 要求未提供字段省略，不允许用 `null` 占位；READY 至少有一个参数且无缺参。

### QueryGift 礼物查询

- `gift_id`、`gift_ids`、`gift_name` 三种模式恰好选择一种；`limit` 是可选正整数。
- ID 为正整数，`gift_ids` 非空，名称非空；完整请求 CALL_TOOL，缺失、非法或模式冲突应追问。

### AddBackpackGift 赠礼

- 用户模式 `user_id/user_ids` 恰好一种；礼物模式 `gift_id/gift_ids/gift_nums` 恰好一种；必须明确 `environment`。
- 数量和天数范围为 1–1000；快照声明默认数量 1、默认天数 7，1000 天表示永久。
- 完整写请求必须先 ASK_CONFIRMATION，不能把识别成功当作已完成发放。

上述语义规则进入 IR，但当前通用契约校验器并不逐条执行所有 `semantic_rules`。模式互斥、纠正选择、AND/OR 与输入含义的对应关系仍需要人工核对。

## 8. 自动 Gate 与实际能力

当前内置 Suite 配置启用以下七类 Gate；候选 Schema／Slot 解析发生在编译前，不是这七项中的独立报告。

| Gate | 实际自动检查 |
|---|---|
| `evaluator` | 加载 JSONL、调用共享契约包的数据集校验、数量与 Schema 版本；并非运行被测 Agent |
| `capability_snapshot` | 生成时绑定、工作区能力包、当前能力包及 IR 等的一致性 |
| `contract` | 参数 Schema、缺参词表、状态／动作、状态规则、Slot 标签、配置要求的场景与 rule_refs 对齐 |
| `coverage` | 总数和 Policy 配置的分布精确匹配 Plan，检查禁用意图 |
| `duplicate` | case_id 和完全相同输入重复阻断；规范化近重复只报告 |
| `leakage` | 执行字段中的答案／评分关键词，以及输入中的答案提示模式 |
| `quality` | 最短输入长度、禁用／敏感短语、配置指定的疑似复合意图模式 |

只有执行的 Gate 全通过，报告才为 `VALIDATED`；能力绑定 Gate 失败时为 `STALE`；其他未通过情况为 `DRAFT`。

**校验通过不等于自然语言标准答案已经被证明正确。** 自动程序不能完整判断输入是否自然、答案能否唯一推出、是否存在真实隐私信息、所有语义规则是否落实；这些必须纳入人工审核。

代码依据：`validation.py`、`intent_validation.py`、`coverage.py`、`leakage.py`。

## 9. 生命周期、审核和冻结

流程：`prepare → generate/ingest → compile → validate → review → 人工批准 → freeze`。

- `prepare` 复制经过校验的能力包到工作区，复验其 Hash，写出 IR、Prompt、来源清单和生成请求。
- `generate` 或 `ingest` 之后，CLI 自动调用编译，形成候选文件与草案；不会自动完成审核或冻结。
- 审核文件必须绑定当前草案 SHA-256；每个 case_id 必须且只能勾选一次。
- reviewer 不能空白；修改草案后必须重新生成和复核与之匹配的审核资料。
- `freeze` CLI 从审核文件构造 Approval，然后重新校验草案。审核勾选本身不能绕过自动校验。
- 冻结核对生成与当前能力包、根快照、IR 和执行 Profile；Profile 允许工具不得超出所选 Tool。
- JSONL、Manifest 或 Coverage 任一目标文件已存在即拒绝覆盖。
- 冻结复制可移植能力包到 `capability_bundles/<bundle_hash>/`；已有同 Hash 目录须再次通过完整性验证。

人工必须确认：输入含义明确；expected 可由绑定契约唯一推出；不依赖 Agent 实际输出或生产数据；缺参、冲突、批量和写入确认语义正确；近重复有保留价值。

当前没有独立 `approve` CLI 子命令，也没有单独持久化 `APPROVED` 阶段的命令；Approval 在 freeze 流程中构造。`explicit_new_version` 是配置约定，当前代码不维护跨数据集版本注册表，也不自动校验版本递增。

代码依据：`pipeline.py`、`schemas.py`、`freezing.py`、`cli.py`。

## 10. 交付产物与追溯

| 阶段 | 产物 |
|---|---|
| 准备 | `capability_bundle/`、`capability_ir.json`、`prompt.md`、`source_manifest.json`、`generation_request.json` |
| 生成与编译 | `raw_response.json`、`candidates.json`、`draft.jsonl`、`generation_manifest.json` |
| 校验与审核 | 校验结果、覆盖／重复／泄漏报告、`review.md`；报告落盘行为见下方说明 |
| 冻结 | 数据集 JSONL、同名 `.manifest.json`、`.coverage.json`、相对路径能力包 |
| 阶段追踪 | 使用 PipelineEngine 的阶段在 `stage_ledger.jsonl` 记录输入与 Policy 等信息 |

生成请求与 Manifest 记录 Profile、可信 Schema、Adapter 实现、Bundle、Agent 根快照、IR、能力选择、Suite、Policy、Coverage Plan、Source Pack 和 Prompt 等信息及相应 Hash。冻结 Manifest 另记录草案／数据集、审核人、时间、审核文件 Hash 和已审核案例列表。

CLI `validate` 当前将结果输出到标准输出，未传入工作区参数；不会自动写出各报告文件或更新生成 Manifest。调用 `validate_draft(..., workspace=...)` 才会执行这些落盘动作。不要仅凭缺少报告文件推断没运行校验，也不要假设运行 CLI 后一定存在全部报告。

## 11. 需要明确保留的实现边界

1. **Hash 已记录不等于已逐项校验。** 当前 `capability_snapshot_gate` 对 Profile、Schema、Adapter、IR、能力选择、快照来源、Bundle、根快照以及执行 Profile 做一致性核对；对 Source Manifest 主要比较 request 与 manifest。没有逐项重算并比较当前 Suite、Policy、Coverage Plan、Prompt 和全部 Source 文件 Hash。因此 README 中“任一绑定变化均进入 STALE”应理解为设计目标，不能作为当前全面实现的保证。
2. **语义规则没有通用自动解释器。** 参数 Schema 合法不代表三种查询模式满足互斥，也不代表标准答案与输入中的纠正或否定关系吻合。
3. **IR 并未完整展开 Boundary 正文。** 当前保留所选节点的 Boundary ID 与来源闭包，但不将所有 Boundary 内容转成结构化生成约束。
4. **“只读 IR”限定于出题与契约编译路径。** evaluator 兼容层 `_runtime_contracts` 仍从已验证快照构造运行时 CapabilityRegistry；不应声称全项目任何代码都不读原始 payload。
5. **历史 Markdown 可能落后于机器配置。** 例如通用意图旧说明与专用 v2 的 null、缺参规则并不一致；应依次核对当前能力快照／IR、Suite JSON、Policy 和 Coverage Plan。

上述内容是代码核对结论，本次仅整理文档，没有修改实现或重新生成、批准、冻结评测集。

## 12. 代码定位

以下文件均位于 `src/dataset_builder/`：

| 约束 | 文件／函数 |
|---|---|
| 可信协议与 Schema | `capability_profiles.py`：`load_trusted_profile`、`verify_bundle_schemas` |
| 完整能力包校验 | `capability_bundle.py`：`load_validated_bundle` |
| 能力选择与 IR | `capability_adapters.py`：`CapabilityAdapter`；`suite_definition.py`：`SuiteDefinition` |
| 六类 Policy 的底线 | `policies.py`：`validate_kernel_policy_compatibility` |
| Prompt 与来源 | `source_pack.py`：`build_source_pack`；`prompt_builder.py`：`build_prompt` |
| 候选结构与覆盖 | `candidate_protocol.py`：`build_candidate_protocol`；`candidate_parser.py`：`parse_candidates` |
| 编译与业务契约 | `intent_compiler.py`：`compile_intent_candidates`；`intent_validation.py`：`validate_module_intent_contract` |
| 七类 Gate 与过期 | `validation.py`：`validate_draft_file`、`capability_snapshot_gate`；`coverage.py`；`leakage.py` |
| 审核与冻结 | `pipeline.py`：`approval_from_review`、`freeze_dataset`；`freezing.py`：`freeze` |
| CLI 行为 | `cli.py`：`main` |

覆盖与业务配置位于 `suites/<suite_id>/suite.json`、`policies/*.json` 和 `coverage_plan.json`。v2 Suite 的能力来源映射到本仓库 `examples/mini_agent/exports/trace_v1/`；历史 v1 Suite 保留旧能力包绑定。
