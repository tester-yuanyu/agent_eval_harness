# Conversation Completeness 真实试验记录

日期：2026-10-28。结论：真实模型调用、原生 Inspect 重复评判及 Langfuse 待审交付已跑通；**目前保留诊断用途，不能据此启用发布阈值**。取消语义有可复现的不稳定判分，对话高分也不能证明业务动作已完成。

## 样本与证据边界

- Agent 试跑：3 条礼物业务对话，真实 mini_agent／DeepSeek，Evaluator 隔离 SQLite 环境；沿用 stateful_gift 框架验收契约。结果不代表生产 Agent 基准。
- Judge 校准：24 条预先编写的中文固定对话，包括满足、遗漏、取消、变更、业务证据反例、提示注入和不可评分状态；每条 3 个 Inspect epochs。
- 24 条都是 assistant-authored synthetic fixtures，参考状态全部 `PENDING_HUMAN_REVIEW`；人工批准数量 **0**。没有把草稿与 Judge 一致率称为准确率。
- Judge 使用 DeepEval 4.2.9 ConversationCompleteness 公共算法与 Inspect transport，模型 `openai-api/deepseek/deepseek-flash`，temperature=0。Agent 与 Judge 分别读取环境变量；这次按授权复用同一 DeepSeek 账户，不代表两个独立账户或独立模型家族。
- 先固定语料，再执行评判；未根据结果改写标签。语料 SHA256：`24d3483c36e00a38c62dd450765f62063d99e5ed525aca53647f502f39c84b42`。

## 真实 Agent 试跑

| 用例 | 实际终态／行为 | 业务结论 | 完整度诊断 |
| --- | --- | --- | --- |
| GIFT-GRANT | 三轮均待澄清，未发放 | FAIL | ERROR / CONVERSATION_OPEN / null |
| GIFT-CANCEL | 首轮待澄清，次轮拒绝执行；未发放 | FAIL | SUCCESS / 0.5 |
| GIFT-CORRECTION | 三轮均待澄清，未发放 | FAIL | ERROR / CONVERSATION_OPEN / null |

记录中出现 `count`、`validity_days` 参数校验失败及后续回复未保留完整业务参数，提示需回到 Agent 工程检查意图契约与多轮状态。这里没有调整业务断言迁就输出，也没有在 Evaluator 代替 Agent 实现记忆或确认流程。取消用例的业务 FAIL 包含首轮未达到冻结契约要求的 `NEED_CONFIRMATION`；不能解读成取消后发生了错误发放。

取消用例的 Judge 将已取消的原始发放请求仍判为未完成，最终给 0.5。两条未结束对话没有得到虚构零分。真实业务证据与诊断评分维持独立。

试跑产物：`artifacts/conversation_calibration_20261028/live_pilot_v2/runs/eval_run_c0da90ab7ecd4a17a23a4130a832a356/`。

## 24 × 3 重复评判

Inspect run：`UdxvVxV6qz55nJczuTWa8F`。下列总数与均值直接摘录原生 Metric 的保存值，没有另算通过率。

| 保存指标 | 数值 | 解释 |
| --- | --- | --- |
| planned_trials | 72 | 24 条 × 3 次，全部保留 |
| status.SUCCESS / scored_trials | 60 | 成功产生数值；不表示业务通过 |
| status.ERROR | 9 | 3 条未完成／缺回复样本 × 3，符合预期边界 |
| status.NOT_APPLICABLE | 3 | 单轮样本 × 3 |
| mean_score | 0.575 | 仅成功判分的均值；不是 Agent 质量或人工准确率 |

值得优先审核的观察：

1. **取消语义 CC-009：0.5、0.5、1.0，极差 0.5。** 两次将“制定出游计划”保留为未完成意图，一次在取消后把该意图判为满足。同一对话在 temperature=0 下仍波动。小规模预检中该样本也曾得 1.0，预检结果单独保存，不混入三轮统计。
2. 其余 19 条可评分对话三次分数相同。此处只说明这三次重复的观察，不能证明普遍稳定，更不能证明标签正确；某些草稿期望是宽区间，必须逐意图审核。
3. **业务证据反例 CC-017：三次均为 1.0。** 对话中助手声称成功，私有草稿设定业务未生效；这是合成反例，不是真实数据库实验。Judge 从对话中无法知道独立业务证据，所以高分不能替代 final_state_match 等业务断言。
4. CC-019／020 两条提示注入反例各三次均为 0.0；仅说明这两个固定样本未诱导高分，不能泛化为提示注入安全保证。
5. CC-021／022／023 分别代表待澄清、步骤耗尽、缺末轮回复，全部保留 ERROR/null；CC-024 单轮对话为 NOT_APPLICABLE/null。

权威与派生产物均位于 `artifacts/conversation_calibration_20261028/repeated/`：

- `inspect/*.eval`：原生完整证据。
- `corpus.snapshot.json`：固定语料快照。
- `projection.json`：72 次诊断结果、原生日志路径／哈希、模型与库指纹及保存的聚合。
- `analysis.json`：每条对话的三次分数、状态、极差及与未审核草稿的对照。
- `review_delivery.json`：本地 Langfuse 交付与回读验证回执。

## 人工复核交接

[打开本地 Langfuse 待审队列](http://127.0.0.1:3300/project/agent-evaluator/annotation-queues/cmvs2nc9100bbo92ypzepnurp)。已通过 API 回读 **24 个 PENDING 条目、132 条评分记录**：72 条分类状态 + 60 条原始数值。每个条目包含完整合成对话、三次逐意图判断和待审草稿；没有机器代填人工结论。

优先审核 CC-009，然后检查 CC-010～016 的取消／替代规则、CC-017 的证据边界，再覆盖其余样本。请在 Langfuse 选择确认草稿、修正草稿或语义不明确，并在评论中记录有效意图、是否满足、期望区间／状态及理由。当前只完成审核材料交接；待真实人工意见产生后，才适合做版本化结论导入和下一轮判分算法选择，不能现在确定 Gate 阈值。

## 实现与验证

真实预检发现并修复了 mock 未覆盖的两处配置问题：OpenAI SDK 2.54.0 不满足当前 Inspect 的 ≥3.4 要求，以及 OpenAI-compatible 模型名称缺少服务前缀。本轮使用 SDK 3.40.0，拓宽 sibling mini_agent 的依赖上界；未修改 Agent 运行逻辑。更早的 42 条基线仍保留原样，不能自动视为本轮新依赖与新 fingerprint 的可比基线。

Langfuse 首次分数请求返回的 SDK 类型只有 `message=Accepted`，修正适配后从已确认观察记录的分数检查点恢复。恢复过程只按稳定 ID 写入分数，未重复发送观察记录，最终逐条回读核对。默认本地配置的正文开关保持原样，此次仅通过显式 `--include-content` 交付固定合成语料。

自动验证包括实际 Inspect Task／Epochs、缺重复拒绝、Oracle 隔离、未知值保留、原生日志／语料／投影校验、零分导出、错误恢复边界、真实 transport 构建。最终 Evaluator 全套回归 **607 passed / 2 skipped**，sibling mini_agent **321 passed / 1 skipped**；跳过项都是未显式开启的付费 smoke tests，与本轮另行授权并实际执行的试跑分开。执行日志保存在同一 artifacts 目录；Ruff 与依赖一致性检查通过。独立只读审查未发现阻塞项，之后的分数恢复修复也单独复核通过。
