# QueryGiftInfo 意图候选生成规则 v1

能力事实只来自 `capabilities/agent.json` 所引用的 `module.intent_router` 与
`intent.query_gift`。本 Suite 只验证单轮意图理解，不运行 Agent、Tool 或 Context。

每个 Coverage Slot 生成且只生成一条候选，并原样保留 `slot_id`、`rule_refs` 与主
`scenario_type`。`query_gift` 的查询模式为 `gift_id`、`gift_ids`、`gift_name`，完整
请求必须且只能提供一种模式；`limit` 是可选正整数。未提供的参数必须省略，不能用
`null` 占位。非法值和模式冲突必须进入 `NEED_CLARIFICATION → ASK_USER`。

不得推断快照未声明的裸数字、别名、更正、上下文继承或工具结果规则。生成模型不得
输出 case ID、断言、reason、执行配置或 cleanup；批次输出必须是严格候选 JSON。
