# QueryUserInfo 意图候选生成规则 v3

Agent 能力事实只来自 Source Pack 中锁定的 `intent_router` 1.0 与
`query_user` 2.0 快照。本文只定义评测生产方式，不自行扩展 Agent 能力。

为 Coverage Plan 中的每个 slot 生成且只生成一条候选，并原样保留
`slot_id`。用户输入以中文为主，同时覆盖正式表达、自然口语、语序变化和
英文字段名。每条候选必须原样保留 Coverage Plan 中的 `rule_refs`；expected
必须能够由能力快照与 Coverage Slot 唯一推出。

固定要求：

- intent 只能为 `query_user`；
- status 只能为 `READY` 或 `NEED_CLARIFICATION`；
- 明确字段名优先于值格式；
- 不同字段组合表示 AND，同字段多值、OR 和明确多用户请求必须追问；
- `phone` 必须保持 11 位数字字符串，不能转为 JSON number；
- `READY` 必须至少输出一个合法查询字段，只保留实际提取到的参数；
- 未提供的字段必须省略，不得用 `null` 占位；
- 非法值、模糊值和批量列表不得进入单值参数。
- `scenario_type` 必须显式填写，且只能使用 `normal`、
  `valid_boundary`、`invalid_parameter`、`missing_parameter`、
  `ambiguous_expression`、`multi_condition`、`expression_variant`、
  `correction_conflict`、`unsupported_batch` 之一；
- 每条候选只能有一个主 `scenario_type`，细粒度特征继续放在
  `coverage_tags` 中。

不得运行 Agent 或 Tool，不得依据 Agent 当前输出修改 expected，不得生成
Link、End to End、故障注入、Prompt Injection、生产数据、凭据或评分指令。
生成模型不输出 `case_id`、断言权重、`reason`、`tool_profile` 或 cleanup。

批次输出必须是严格符合所给 Schema 的裸 JSON object，不允许额外属性、
Markdown 代码块或附加解释。
