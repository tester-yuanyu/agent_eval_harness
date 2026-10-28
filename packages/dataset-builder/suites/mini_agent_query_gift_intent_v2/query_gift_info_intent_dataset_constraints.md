# QueryGiftInfo 意图理解模块评测集生成约束 v1

本 Suite 评测 `query_gift` 的单轮意图识别、参数提取、参数 Schema 校验、查询模式
互斥及缺参追问。业务依据为当前能力包中的 `intent.query_gift`；关联工具名
`query_gift_info` 只表示下一步动作，不要求默认能力包存在 Tool 快照。

范围限定为 `module.intent_router` 的 understanding 层和 `intent_router_only` Boundary。
不覆盖多轮 Context、工具调用、查询结果、权限、超时、重试或端到端终态。

正式参数为 `gift_id`、`gift_ids`、`gift_name`、`limit`。前三者是查询模式，必须且
只能选择一种；`gift_id` 和 `gift_ids` 中的 ID 必须大于零，`gift_ids` 至少包含一项，
`gift_name` 不得为空，`limit` 若出现必须大于零。完整请求为 `READY/CALL_TOOL`，
非法、缺失或多模式冲突为 `NEED_CLARIFICATION/ASK_USER`。

所有 Case 必须绑定唯一 Coverage Slot，经过 Schema、能力契约、覆盖、重复、泄漏、
质量和 Evaluator Gate，并在人工审核后才能冻结。
