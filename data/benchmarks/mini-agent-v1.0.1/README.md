# mini_agent 评测集 v1.0.1

105 条开发集任务：93 条意图模块（query_user 42、query_gift 23、add_backpack_gift 28），6 条查询工具链，6 条礼物发放确认/状态流程。新增场景为合成数据，未做人工盲审；不是 holdout，不代表线上业务环境。

93 条源用例的 Oracle 保持原文，执行 profile 和预算规范化。查询工具使用公开合成用户 fixture；礼物工具使用隔离 SQLite 账本。模型真实调用，工具是真实执行的测试实现。确认、多轮续接属于能力探测，适配器不得补齐 Agent 缺失能力。

v1.0.0 在付费执行前被离线检查发现预期工具参数遗漏必填 nullable 字段，且缺少回答一致性检查。保留原资产，正式运行采用 v1.0.1；修订未改变历史93条 Oracle。新增查询检查校验工具返回数据和最终回答中的用户姓名/未找到措辞；规则不是开放语义 Judge，合法同义表述可能被严格判为失败。

`manifest.json` 绑定 tasks 和 v3 capability bundle 的全部文件 Hash。生成器拒绝覆盖既有目录。执行输入仅含 execution、scope、environment；Oracle 仅由评分侧读取，Inspect Sample target 为空。

运行：在仓库根目录使用 Evaluator 环境，显式通过 `--env-file .env` 读取凭据。先 `python -m eval_framework.benchmark.mini_cli run --pilot --output artifacts/mini-agent/pilot --env-file .env`，再去掉 `--pilot`，改为独立 full 输出目录。已完成的相同身份运行直接复用保存结果。

正式评分由 DeepEval BaseMetric 执行既有确定性断言，不调用额外裁判模型。每条模型 token 上限 16384、120秒，Agent最多4步；全量每题1次，pilot不计入全量分母。
