# mini_agent 场景覆盖与代表集

本轮目标是验证框架可评测 Agent、保存完整执行证据、正式评分并交付本地报告及 Langfuse 展示。Agent 的行为失败保留原样，不通过更改 Oracle 或修复 Agent 来制造全绿。

## 覆盖口径

范围限定 `query_user`、`query_gift`、`add_backpack_gift`。正常、边界、表达变体、非法参数、缺参、歧义、条件冲突、批量限制、注入文本、工具限制、工具错误、确认与取消分别登记。以模块、关键链路、端到端划分执行层级。

覆盖清单位于版本化数据目录的 `coverage.json`，与 `tasks.jsonl` 一起受外层 `manifest.json` Hash 约束。能力 bundle 保持 v3 结构，不在 bundle 内添加清单。历史 1.0.1 的 105 条数据及 Oracle 不改动；1.1.0 增加 10 条，共 115 条，代表集为 30 条。1.1.1 保留同一批 115 条，仅修正重复确认用例：通过已有 adapter_input 显式要求成功后继续，并要求持久化证据证明完成 3 轮。历史 1.1.0 不变。

必须区分：已构造、已选择、已执行、证据完整、判定以及后续链路是否实际到达。多标签统计可交叉，不得相加作为用例总数。合成用例没有人工验收，不声称覆盖所有自然语言表达或所有业务组合。

## 运行与产物

执行 `scripts/mini_agent_coverage.py --output <新的输出目录>`，使用 Evaluator 独立环境的 Python。脚本从本地 `.env` 读取 OpenCode 模型、端点和密钥，密钥不进入运行配置文件。每例一次、并发 2、最多 60 次模型调用，模型与桥接客户端不自动重试。拒绝复用已存在的输出目录，避免重新启动重置预算。

使用 `scripts/mini_agent_coverage_report.py --dataset <冻结数据目录> --run <运行目录>` 从已有结果生成 `coverage.html` 和 `coverage-results.json`。详细 `report.html` 由原领域报告生成器生成，保留逐项评分和原始 Trace。HTML 的变更不修改原始结果或 verdict。

Inspect 负责执行和原生日志；DeepEval 使用确定性断言评分；不启用 LLM Judge。回复只验证必要/禁止内容、事实和工具结果一致性。开放式语义质量另列限制。

## 适配和异常边界

`providers/mini_agent/benchmark_environment.py` 提供 `read_fixture_v2` 的礼物查询及错误 handler。公开环境配置中的 `fault` 仅支持单一受控工具的 `timeout`、`execution_failure`、`business_failure`、`rate_limit`。工具真实经过参数校验、注册表调用和 Agent 错误处理，不连接生产服务，也不等待真实网络超时。

通用 `ExecutionSpec.fault_injection` 仍拒绝；不能据此宣称支持任意工具或任意故障。SQLite 写入环境独立读取逐轮状态，并记录所有写入，不替 Agent 实施确认保护。禁止把状态快照单独当成通过证据。

通用 runner、评分与报告不依赖 mini_agent 的具体业务。具体工具契约、环境和事件映射留在可选适配器。公开执行投影只有 execution、scope、environment；Oracle、评分配置、覆盖标签不进入模型或 worker 输入。

## Langfuse

显式执行 benchmark `export-langfuse`、`export-langfuse-evidence`、`verify-langfuse`，携带本地 `--env-file`、运行目录和冻结数据目录。先导出已保存结果，再回读核对事件父子关系、输入输出、评分关联和 token 用量；不重新调用 Agent 或 Judge。保留导出收据和回读结果。

Inspect 的 input_tokens 不含缓存读取/写入，用量分别导出；未知值不补零。Langfuse 故障不影响本地执行、评分或报告。

## 明确不包含

角色/租户/资源所有权授权、生产服务验证、动态用户模拟、开放式语义质量、其他意图，以及未声明的重试/回滚/跨工具恢复策略。不将工具白名单解释成 RBAC，也不将模型声明成功视为发生了真实副作用。

## 本次发现的覆盖修复

默认会话在 SUCCESS 后结束，不能据首次发放成功就认为重复确认已经测试。mini 适配器增加显式布尔 adapter_input.continue_after_terminal，默认行为不变；worker 从持久化 run_finished 事件计数 completed_turns，评分使用 observations_match 要求 3。这个控制不进入 Agent 的模型消息，不修改共享 ExecutionSpec 或历史 Hash 规则。成功发放本身未实现时，重复确认的业务前置条件仍未到达，报告必须说明。

Langfuse 元数据 API 会省略空对象。补充证据协议 v3 对空对象也保存原始 JSON 字节、Hash、来源和父节点绑定；只有证明完整且其余非空叶子一致时才允许回读空对象省略形式。v1/v2 生成规则保留。补充证据不算模型调用、工具执行或正式评分。
