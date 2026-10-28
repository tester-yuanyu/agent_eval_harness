# 生成规则 v1

为 Coverage Plan 中的每个 slot 生成且只生成一个候选，并原样保留 `slot_id`。
所有用户输入使用中文，同时覆盖正式表达和自然口语。每条案例只验证一个主要
路由或完整性决策，其 expected 必须能够由能力契约唯一推出。

不得生成 Legacy 意图、工具执行、故障注入、Prompt Injection、多轮补参、
多意图复合、查询模式冲突、实时数据依赖、生产数据、个人信息、凭据、隐藏推理
或评分指令。不得查看或模仿 Agent 的实际答案。不得输出 EvalCase 固定样板。
`difficulty` 只允许 `easy` 或 `medium`。

批次输出必须是严格符合所给 Schema 的裸 JSON object。所有属性均为 required，
不允许额外属性，不得使用 Markdown 代码块或附加解释文字。
