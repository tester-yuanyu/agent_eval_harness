# mini_agent Shadow 意图能力契约 v1

本文是依据公开协议整理的 Source Pack，不包含 mini_agent 测试、Scripted
响应、evaluator Fixture、历史运行结果或评测集标准答案。

## IntentResult 状态机

每个 expected module output 必须包含 `intent`、`status`、`next_action`、
`parameters`、`missing_parameters` 和 `reason`。

- `READY` 对应 `CALL_TOOL`，且 `missing_parameters` 为空。
- `NEED_CLARIFICATION` 对应 `ASK_USER`，且至少有一个缺失参数。
- `NEED_CONFIRMATION` 对应 `ASK_CONFIRMATION`，且 `missing_parameters` 为空。
- `REJECTED` 对应 `REJECT`。

Compiler 注入固定且不参与评分的 `reason`。参数中的整数使用 JSON number，
空值使用 JSON null，列表保持用户输入顺序。

## 参数和缺参名称规范

- `query_user`：至少使用 `user_id`、`room_id`、`email`、`phone` 中的一个
  条件查询；多个条件表示 AND。完整参数 object 包含以上四个字段，未提供的
  可选条件使用 null。复合缺参名称为
  `user_id_or_room_id_or_email_or_phone`。
- `query_gift`：`gift_id`、`gift_ids`、`gift_name` 三种模式恰好选择一种；
  V1 不生成模式冲突。完整参数 object 还包含可空的 `limit`。复合缺参名称为
  `gift_id_or_gift_ids_or_gift_name`。
- `query_custom_gift_record`：正整数 `element_id` 必填；`custom_type` 可空，
  非空时只能为 2 或 3。完整参数 object 包含这两个字段。
- `query_pool`：`pool_id`、`gift_id` 两种模式恰好选择一种；完整参数 object
  包含两个字段，未使用的模式为 null。复合缺参名称为 `pool_id_or_gift_id`。
- `add_backpack_gift`：用户模式 `user_id` 或 `user_ids` 恰好选择一种；礼物
  模式 `gift_id`、`gift_ids` 或 `gift_nums` 恰好选择一种；必须明确提供
  `environment`。完整参数 object 包含 `gift_id`、`gift_ids`、`gift_nums`、
  `user_id`、`user_ids`、`num`、`duration_days` 和 `environment`，未使用的
  模式或采用默认语义的可选值使用 null。`gift_nums` 的每项为
  `{gift_id: integer, num: integer}`。`duration_days` 范围为 1..1000，1000
  表示永久。复合缺参名称为 `user_id_or_user_ids`、
  `gift_id_or_gift_ids_or_gift_nums` 和 `environment`。
- `update_pool_weight`：完整参数 object 包含 `pool_id`、`gift_id`、可空的
  `gift_num` 和明确的 `environment`。缺参名称直接使用对应字段名。
- `unsupported`：`parameters` 固定为 `{}`，`missing_parameters` 固定为 `[]`。

以上复合缺参名称属于 Benchmark 约定。公开 Pydantic 协议只强制
`NEED_CLARIFICATION` 的缺参列表非空，并不强制这些具体名称。

完整写意图使用 `NEED_CONFIRMATION`；不完整写意图使用
`NEED_CLARIFICATION`。不得创建或输出 `request_id`、`confirmation_id`、
`session_id`、`run_id` 或 `internal_version`。

## EvalCase 与断言契约摘要

EvalCase 的 Module 固定结构、`shadow_full` execution profile、六项精确断言、
标签和写意图兼容字段均由 Compiler 注入，模型不得生成。
`params_match` 使用完整且类型敏感的相等比较。evaluator 通过公开的
`IntentResult` 校验 expected module output。

## 非黄金格式示例说明

对于一个不在正式 Coverage Plan 中的虚构 slot，候选 JSON 只使用候选协议
要求的字段；`expected_parameters_json` 存放编码为字符串的 JSON object；
不得包含 `case_id` 或断言配置。该说明只展示格式，不提供正式案例输入。
