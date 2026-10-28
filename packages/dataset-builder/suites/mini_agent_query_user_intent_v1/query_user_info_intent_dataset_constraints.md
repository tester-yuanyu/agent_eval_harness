# QueryUserInfo 意图理解模块评测集生成约束 v5

## 一、文档目的

本文定义 `query_user_info` 对应的意图理解 Module 评测集生产规则。评测集用于独立
检验 Agent 是否能够：

1. 将不同自然语言表达稳定识别为 `query_user`；
2. 将用户表达映射到 `user_id`、`room_id`、`email`、`phone`；
3. 根据明确字段、中文同义表达、上下文和值格式完成参数提取；
4. 对非法格式、缺参、语义歧义、未消解冲突和批量请求作出确定性追问；
5. 把多个不同字段理解为同一用户查询的 AND 条件，而不是批量或 OR 查询；
6. 在 Agent 当前能力不足时稳定暴露差距，而不是根据 Agent 实际输出修改 expected。

本文只定义评测生产与覆盖规则，不自行定义业务真相。Agent 能力事实以
`capabilities/agent.json` 为唯一根入口，并选择 `module.intent_router` 与
`intent.query_user` 作为 Oracle 来源。`required_tool_name` 只描述意图完成后的下一步
工具名称；Intent-only Suite 不要求默认能力包已经注册对应 Tool 快照。Builder 不扫描
mini_agent 源码或 Prompt 文件。后续只有经过逐条人工复核并绑定审核文件 hash 的案例
才能进入冻结数据集。

## 二、Suite 身份和范围

```text
suite_id: mini_agent_query_user_intent_v1
dataset_version: 1.6
module_contract_version: intent-router-module-v3
capability_contract_version: query-user-intent-contract-v3
target_agent: mini_agent
test_scope: module
target: intent_router
intent: query_user
related_tool: query_user_info
```

第一版只评测 `run_intent_only()` 返回的 `IntentResult`，不执行
`query_user_info`，不验证工具返回数据，也不依赖 SQLite Mock 数据中是否存在对应
用户。

第一版不覆盖：

- Tool 是否实际调用；
- 多条件是否在数据库中匹配同一用户；
- `QUERY_CONDITION_CONFLICT`、`USER_NOT_FOUND` 等工具结果；
- 联系方式脱敏；
- Tool error、timeout 或 empty result；
- 多轮补参后的最终执行；
- Link、End to End、安全和故障注入评测。

以上内容后续必须作为独立 Link 或 End to End Suite 建设，不能混入本 Module
数据集。

## 三、独立评测原则

1. expected 只能由能力快照与 Coverage Slot 推出，不能来自 Agent 实际回答。
2. Agent 当前不具备某项能力时，案例仍应保留并在执行阶段稳定判为 FAIL。
3. 不得为提高通过率删除格式识别、语义歧义、冲突或批量边界案例。
4. 不得把工具执行结果、Mock 数据终态或历史 PASS/FAIL 放入生成 Prompt。
5. 不得让生成模型输出 `case_id`、断言权重、`reason`、`tool_profile` 或 cleanup。
6. 生成后必须经过自动 Gate 和逐条人工审核，不能自动批准或冻结。

## 四、公开意图输出契约

每条案例的 `expected_module_output` 必须包含：

```text
intent
status
next_action
parameters
missing_parameters
reason
```

本 Suite 只允许以下两种状态：

```text
READY              → CALL_TOOL
NEED_CLARIFICATION → ASK_USER
```

规则：

- 能唯一确定查询字段，且所有已提供值均合法时，使用 `READY`。
- 缺少查询条件、字段类型无法唯一确定、值格式非法、同一字段存在未消解冲突，
  或请求包含工具不支持的批量条件时，使用 `NEED_CLARIFICATION`。
- 本 Suite 不生成 `NEED_CONFIRMATION` 或 `REJECTED`。
- `READY` 的 `missing_parameters` 必须为空。
- `NEED_CLARIFICATION` 的 `missing_parameters` 必须非空。
- `reason` 由 Compiler 固定注入，不参与评分。

## 五、四种查询字段

### 1. user_id

- 规范字段名：`user_id`。
- 合法值：大于 0 的 JSON integer。
- 明确表达包括但不限于：`user_id`、`user id`、`UserID`、`用户 ID`、
  `用户id`、`用户编号`、`用户号`。
- 出现“用户”“账号用户”等明确用户语义且跟随正整数时，可以映射为
  `user_id`。
- 不得接受 0、负数、小数、布尔值或非数字文本。
- 正常示例：“查询 UserID 为 9075333 的用户信息”，expected 提取
  `user_id=9075333`。

### 2. room_id

- 规范字段名：`room_id`。
- 合法值：大于 0 的 JSON integer。
- 明确表达包括但不限于：`room_id`、`room id`、`RoomID`、`房间 ID`、
  `直播间 ID`、`房间号`、`直播间号`。
- 出现“房间”“直播间”等明确房间语义且跟随正整数时，可以映射为
  `room_id`。
- 不得接受 0、负数、小数、布尔值或非数字文本。
- 正常示例：“查询 RoomID 为 8800123 的用户信息”，expected 提取
  `room_id=8800123`。

### 3. email

- 规范字段名：`email`。
- 合法值：字符串中恰好包含一个 `@`，且 `@` 前后均有非空内容。
- 明确表达包括但不限于：`email`、`e-mail`、`邮箱`、`电子邮箱`、
  `邮件地址`。
- 没有字段提示但值符合上述格式时，可以自动识别为 `email`。
- 第一版不额外要求域名包含点号，不引入 RFC 全量邮箱校验。
- 正常示例：“查询 Email 为 reviewer@example.com 的用户信息”，expected
  提取 `email="reviewer@example.com"`。

### 4. phone

- 规范字段名：`phone`。
- 合法值：由 11 个十进制数字组成的字符串。
- 明确表达包括但不限于：`phone`、`phone number`、`手机号`、`手机号码`、
  `电话`、`电话号码`。
- 没有字段提示但值为 11 位纯数字时，可以自动识别为 `phone`。
- 必须以 JSON string 保存，不能转为 JSON number，以免丢失前导零。
- 第一版只冻结“11 位纯数字”规则，不增加号段、国家码或运营商规则。
- 正常示例：“查询 Phone 为 15000000200 的用户信息”，expected 提取
  `phone="15000000200"`。

## 六、字段提示和格式推断的优先级

参数识别按以下优先级处理：

1. 明确字段名；
2. 中文或英文同义字段表达；
3. 上下文语义；
4. 值格式；
5. 无法唯一判断时追问。

明确字段名优先于值格式。例如：

- “用户 ID 为 15000000200”明确表示 `user_id`，不能因为它是 11 位数字而改成
  `phone`。
- “手机号为 9075333”明确表示用户想提供 `phone`，但值不是 11 位，应要求其
  重新提供合法手机号，不能改成 `user_id`。
- “查询 15000000200 的用户信息”没有字段提示，值为 11 位纯数字，应自动识别
  为 `phone`。
- “查询 test@example.com 的用户信息”没有字段提示，应自动识别为 `email`。
- “查询用户 9075333 的信息”根据“用户”语义识别为 `user_id`。
- “查询直播间 9075333 对应的用户”根据“直播间”语义识别为 `room_id`。
- “查询 9075333 的用户信息”只有裸正整数，无法仅凭格式区分 `user_id` 和
  `room_id`，必须追问。

不得为了让当前 Agent 通过而把裸正整数固定猜测成 `user_id`。

## 七、标准参数表示

### 1. READY

`READY` 必须在四个规范字段中至少输出一个合法查询条件。只保留用户
实际提供并成功提取的字段；未提供的字段必须省略，不得用 JSON `null`
占位。

示例：

```json
{
  "user_id": 9075333
}
```

手机号必须保持字符串：

```json
{
  "phone": "15000000200"
}
```

### 2. NEED_CLARIFICATION

- 保留已经明确且格式合法的单值参数。
- 非法值不得放入 `parameters`。
- 无法确定属于哪个字段的值不得擅自放入 `parameters`。
- 同一字段出现多个未消解值时，不得任意选择其中一个。
- 批量值无法映射到当前单值协议时，不得静默截断为第一个值。

## 八、缺参名称规范

统一使用以下名称：

| 场景 | `missing_parameters` |
|---|---|
| 完全没有查询条件 | `user_id_or_room_id_or_email_or_phone` |
| 裸正整数无法区分用户或房间 | `user_id_or_room_id` |
| `user_id` 格式非法 | `user_id` |
| `room_id` 格式非法 | `room_id` |
| `email` 格式非法 | `email` |
| `phone` 格式非法 | `phone` |
| 多个 user_id，要求单个值 | `single_user_id` |
| 多个 room_id，要求单个值 | `single_room_id` |
| 多个 email，要求单个值 | `single_email` |
| 多个 phone，要求单个值 | `single_phone` |
| 混合批量、OR 或多个用户请求 | `single_user_query_condition` |

这些名称属于 `mini_agent` 的公开 QueryUserInfo 能力契约
`query-user-intent-contract-v3`，不是 Benchmark 私有命名。评测集必须使用与该
版本完全一致的词表；若 Agent 契约升级，必须同步提升数据集版本并重新审核。

## 九、多条件 AND 规则

`query_user_info` 的不同字段组合固定表示 AND。Module 只负责提取所有条件，
不能查询数据库判断它们是否属于同一用户。

例如：

```text
查询用户 ID 为 9075333、手机号为 15000000200 的用户信息
```

应输出：

```json
{
  "intent": "query_user",
  "status": "READY",
  "next_action": "CALL_TOOL",
  "parameters": {
    "user_id": 9075333,
    "phone": "15000000200"
  },
  "missing_parameters": []
}
```

无论两个值在真实数据中是否属于同一用户，Module expected 均保持不变。是否匹配
同一用户以及是否返回 `QUERY_CONDITION_CONFLICT` 属于 Link Suite。

以下表达不是 AND 单用户查询：

```text
分别查询用户 ID 9075333 和手机号 15000000200 对应的两个用户
```

用户明确要求两个用户，属于当前工具不支持的批量或 OR 查询，应返回
`NEED_CLARIFICATION`，不能拆成两组结果，也不能把两个条件错误地当成同一用户
的 AND 条件。

## 十、格式错误规则

格式错误时，Benchmark 期望 Agent 在 Module 阶段请求用户修正。即使 mini_agent
当前实现仅在 Tool Schema 中检查部分格式，这些案例仍必须保留，用于暴露意图层
能力差距。

| 输入类型 | 非法示例 | expected |
|---|---|---|
| `user_id` | `0`、`-7`、`9.5` | `NEED_CLARIFICATION`，缺参 `user_id` |
| `room_id` | `0`、`-9`、`3.14` | `NEED_CLARIFICATION`，缺参 `room_id` |
| `email` | `example.com`、`@example.com`、`a@` | `NEED_CLARIFICATION`，缺参 `email` |
| `phone` | `1500000020`、`150000002000`、`15000A00200` | `NEED_CLARIFICATION`，缺参 `phone` |

若字段标签明确，格式非法时不得改猜成其他字段。

## 十一、语义模糊和缺参

以下情况必须追问：

1. “查询一下用户信息”：没有任何查询条件；
2. “查询这个用户的信息”：没有可解析的指代上下文；
3. “查询 9075333 的用户信息”：裸正整数无法区分 `user_id` 和 `room_id`；
4. “按 ID 查用户”：没有给出 ID 值，也没有说明用户 ID 或房间 ID；
5. “查手机号对应的用户”：字段明确但没有提供值；
6. 含有无法消解的省略、代词或多个可能指向时。

不得虚构用户 ID、房间 ID、邮箱或手机号。

## 十二、表达变体

每个字段至少覆盖正式表达和自然口语，并覆盖以下变化：

- 字段在前、值在后；
- 值在前、字段在后；
- 请求动作在句首或句尾；
- 中英文大小写和空格变化；
- “帮我看看”“麻烦查一下”“我想找”等自然口语；
- “请查询”“检索”“获取用户资料”等正式表达；
- 不改变业务语义的标点和语序变化。

表达变体不能只是机械替换一个语气词；每条案例必须验证不同的语言理解点。

## 十三、前后语义冲突和纠正

### 1. 明确纠正

存在“不对”“改成”“应该是”“刚才说错了”等清晰纠正标志时，以最终值为准。

```text
查询用户 ID 9075333，不对，改成 9075334
```

expected 为 `READY`，只保留 `user_id=9075334`。

### 2. 否定后重述

```text
不要查用户 ID 9075333，查 9075334
```

若字段继承关系唯一，expected 为 `READY`，提取 `user_id=9075334`。

### 3. 未消解冲突

```text
查询用户 ID 9075333，用户 ID 9075334
```

没有 AND 不同字段语义，也没有纠正关系，必须 `NEED_CLARIFICATION`，缺参为
`single_user_id`。

### 4. 重复一致

同一字段重复出现相同值不构成冲突，可以去重后返回 `READY`。

如果重复的是没有字段绑定上下文的裸正整数，则重复本身不能消除
`user_id`/`room_id` 歧义，仍应返回 `NEED_CLARIFICATION`，缺参名称为
`user_id_or_room_id`。该场景归类为“裸整数歧义”，而不是“重复一致字段”。

## 十四、批量查询边界

当前工具参数均为单值，不支持：

- 多个 `user_id`；
- 多个 `room_id`；
- 多个 `email`；
- 多个 `phone`；
- 使用 OR 连接的多个条件；
- 明确要求返回多个用户。

批量请求统一使用 `NEED_CLARIFICATION`，要求用户一次查询一个用户。不得：

- 自动选择第一个值；
- 把列表塞入单值字段；
- 将 OR 请求错误转换为 AND；
- 伪造 `user_ids`、`room_ids`、`emails` 或 `phones` 字段；
- 自动拆分成多个 Tool Call。

## 十五、第一版 Coverage Plan

第一版固定生成 42 条 Module 案例，每个 slot 恰好一条：

| 覆盖类别 | 数量 | 状态要求 |
|---|---:|---|
| 明确英文参数名，四字段各一条 | 4 | `READY` 4 |
| 中文字段翻译，四字段各一条 | 4 | `READY` 4 |
| 自动格式或上下文识别 | 4 | `READY` 4 |
| 合法格式边界，四字段各一条 | 4 | `READY` 4 |
| 非法格式 | 6 | `NEED_CLARIFICATION` 6 |
| 多条件 AND | 4 | `READY` 3，`NEED_CLARIFICATION` 1 |
| 缺参与语义模糊 | 4 | `NEED_CLARIFICATION` 4 |
| 表达变体 | 4 | `READY` 4 |
| 前后冲突、纠正和重复 | 4 | `READY` 2，`NEED_CLARIFICATION` 2 |
| 批量查询边界 | 4 | `NEED_CLARIFICATION` 4 |
| 合计 | **42** | `READY` 25，`NEED_CLARIFICATION` 17 |

建议 slot 如下：

```text
explicit_user_id
explicit_room_id
explicit_email
explicit_phone
translated_user_id
translated_room_id
translated_email
translated_phone
inferred_user_id_from_context
inferred_room_id_from_context
inferred_email_from_format
inferred_phone_from_format
valid_user_id_minimum
valid_room_id_minimum
valid_email_minimal_shape
valid_phone_eleven_digits
invalid_user_id_zero
invalid_user_id_negative
invalid_room_id_non_positive
invalid_email_shape
invalid_phone_length
invalid_phone_non_digit
and_user_id_phone
and_room_id_email
and_three_conditions
explicit_two_users_not_and
missing_all_conditions
ambiguous_bare_positive_integer
missing_value_after_field
unresolved_pronoun
variant_value_before_field
variant_colloquial
variant_formal
variant_word_order
correction_latest_value
negation_then_restatement
conflicting_same_field_values
repeated_bare_positive_integer_ambiguous
batch_user_ids
batch_room_ids
batch_phones
batch_mixed_or_conditions
```

## 十六、候选协议

生成模型只输出语义候选，不输出完整 EvalCase。候选至少包含：

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

固定要求：

- `expected_intent` 必须为 `query_user`；
- `expected_status` 只允许 `READY` 或 `NEED_CLARIFICATION`；
- `expected_next_action` 必须与状态机一致；
- `expected_parameters_json` 必须解析为 JSON object；
- `difficulty` 只允许 `easy` 或 `medium`；
- `scenario_type` 必填且只能使用 `normal`、`valid_boundary`、
  `invalid_parameter`、`missing_parameter`、`ambiguous_expression`、
  `multi_condition`、`expression_variant`、`correction_conflict`、
  `unsupported_batch` 之一；
- 每条候选只能有一个主 `scenario_type`；
- `slot_id` 必须来自 Coverage Plan；
- 不允许额外字段；
- 不输出思维过程、评分理由或对 Agent 当前实现的猜测。

## 十七、Compiler 规则

Compiler 按 Coverage Plan 顺序生成：

```text
MINI-QUSER-001 至 MINI-QUSER-042
```

固定字段：

```text
schema_version: 1.0
task_id: intent-query-user
scenario_type: 候选中明确指定的唯一主场景类型
test_scope: module
target: intent_router
execution.tool_profile: shadow_read
execution.allowed_tools: null
execution.fault_injection: {}
execution.max_steps: 4
execution.timeout_seconds: 30.0
cleanup: null
```

固定断言策略：

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

`params_match` 使用完整、类型敏感的精确比较，不启用 `expected_subset`。

## 十八、标签规范

每条案例至少包含：

```text
mini_agent
module
intent_understanding
shadow
query_user
query_user_info
bootstrap_generated
对应 status
对应 difficulty
对应 coverage category
slot:<slot_id>
```

`slot:<slot_id>` 是案例与 Coverage Plan 之间的稳定追溯标识，例如
`slot:explicit_user_id`。每条案例必须恰好包含一个 slot 标签；该标签由
Compiler 根据 Coverage Plan 注入，不由生成模型提供。全部 42 个 slot 标签必须
完整、唯一，且与 Coverage Plan 一一对应。

## 十九、自动 Gate

### 1. Candidate Schema Gate

- 批次和候选均通过 Pydantic；
- 42 个 slot 每个恰好一条；
- 无缺少或额外 slot；
- parameters JSON 是 object；
- 字段、枚举和类型合法；
- 不允许额外属性。

### 2. Contract Gate

- intent 固定为 `query_user`；
- status 和 next_action 一致；
- 每条案例恰好包含一个合法的 `slot:<slot_id>` 标签；
- 42 个 slot 标签完整且唯一，不允许缺失、重复或 Coverage Plan 外的值；
- `READY` 没有缺参；
- `NEED_CLARIFICATION` 至少有一个规范缺参名称；
- 参数只能包含 `user_id`、`room_id`、`email`、`phone`；
- READY 参数必须至少包含一个合法查询字段；
- 未提供的查询字段必须省略，不允许用 `null` 占位；
- user_id、room_id、email、phone 类型和格式符合本文规则；
- 多条件遵循 AND；
- 批量值没有被截断或塞入单值字段。

### 3. Evaluator Gate

Compiler 写入临时 JSONL 后，必须真实调用 evaluator：

```python
bundle = load_dataset(draft_path)
report = validate_dataset(bundle)
```

要求：加载成功、`report.valid is True`、案例数为 42、Schema version 为 1.0。

### 4. Coverage Gate

- 42 个 slot 全覆盖；
- 状态分布严格为 `READY=25`、`NEED_CLARIFICATION=17`；
- 四个字段在明确表达、翻译、格式和变体中均有覆盖；
- 不包含 Link、Legacy 或其他意图案例。

### 5. Duplicate Gate

检查 case_id、slot_id、完全重复输入和规范化近重复。近重复只报告，不自动删除。

### 6. Leakage Gate

execution 和 user_input 不得包含 expected、标准答案、断言、评分、case_id 或提示
Agent 如何作答的内容。

### 7. Quality Gate

- 输入自然且表达目的明确；
- 每条案例只有一个主要验证点；
- expected 能由本文唯一推出；
- 不依赖实时数据或 SQLite 中是否存在用户；
- 不包含真实个人信息、密钥或生产数据；
- 变体不是无意义的语气词替换；
- 不根据当前 Agent 的 PASS/FAIL 修改 expected。

任一 Gate 失败都不能进入冻结流程。

## 二十、人工审核要求

审核人必须逐条确认：

1. 输入是否像真实用户表达；
2. 字段提示、上下文和格式推断优先级是否使用正确；
3. explicit label 是否覆盖四个字段；
4. 中文翻译是否覆盖四个字段；
5. 自动识别是否没有错误猜测裸正整数；
6. 格式错误是否要求修正，而非发送非法参数；
7. 多条件是否严格按 AND；
8. 批量和 OR 请求是否没有被误判为 AND；
9. 明确纠正是否采用最终值；
10. 未消解冲突是否要求追问；
11. expected 是否独立于 Agent 当前输出；
12. 案例是否值得保留在正式 Benchmark 中。

人工审核可以拒绝歧义案例，但不得为了提高 Agent 分数而修改 expected。若审核发现
本文规则本身不合理，应先修订约束文档和版本，再重新生成候选，不能只改单条标准
答案。

## 二十一、生命周期和产物

生命周期保持：

```text
DRAFT → VALIDATED → APPROVED → FROZEN
  └──── 快照变化或绑定缺失 ────→ STALE
```

生成运行应保留 Prompt、Source Manifest、原始响应、候选、草案、各 Gate 报告和
人工审核清单。只有所有 Gate 通过且 reviewer 批准精确 draft hash 后才能冻结。

建议冻结文件名：

```text
datasets/mini_agent/module_query_user_intent_v1.jsonl
datasets/mini_agent/module_query_user_intent_v1.manifest.json
datasets/mini_agent/module_query_user_intent_v1.coverage.json
```

当前 42 条 v1.3 案例需要重新生成、自动校验并完成人工审核，不能复用 v1.2
的批准记录或 SHA-256。
