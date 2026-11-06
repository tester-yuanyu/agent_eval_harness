# Conversation Completeness 对话完整性评测

> 本文属于旧 Suite／Provider 兼容路径；其中 Inspect 评分、指标和产物约定不适用于当前任务基准。新基准由 Inspect 执行与记录、DeepEval 正式评分，入口见[包说明](../README.md)。以下包内命令在 `packages/evaluator` 目录执行。

2026-10-28：首个 DeepEval 专项指标已通过 Inspect Scorer 接入。它是可选的正式诊断结果，默认关闭；没有业务校准前不改变断言、质量结论或发布 Gate。Knowledge Retention 与 RAG 指标仍为候选。

## 使用

在现有项目环境安装可选依赖（必须保留 Inspect 与业务 SDK 的现有安装方式）：

```sh
../../.venvs/evaluator/bin/python -m pip install 'deepeval==4.2.9'
```

DeepEval 已是 `agent-evaluator` 的必装评分依赖，重复的 `conversation` extra 已移除；启用本诊断仍需显式配置 Judge。依赖版本必须为 4.2.9；不支持静默升级。项目 pytest 配置禁用 DeepEval 自动插件，避免引入第二套测试运行流程。

当前 Inspect 的模型接口要求 `openai>=3.4,<4`；本轮在 SDK 3.40.0 上验证。mini_agent 的兼容范围扩展为 `>=2,<4`，其独立测试通过。Judge 使用 Inspect 的 `openai-api/deepseek/<model>` 服务前缀，已增加不发请求的真实 transport 构建测试，防止仅 mock 注册表掩盖配置错误。

通过环境设置 `DEEPSEEK_JUDGE_API_KEY`、`DEEPSEEK_JUDGE_MODEL`，可选 `DEEPSEEK_JUDGE_BASE_URL`。指标不会自动借用 Agent API Key，也不加载 dotenv 或旧 DeepEval 密钥文件。Agent 配置照常独立设置。

Suite 的 `run_config` 增加：

```json
{
  "conversation_completeness": {"timeout_seconds": 90}
}
```

然后运行原有 `run --suite ... --output-dir ...`。兼容 dataset CLI 可增加 `--conversation-completeness`。不要把这个兼容标志与 `--suite` 或 candidate intake 混用；Suite 以自身配置为准。缺少可选依赖或 Judge 凭据在执行 Agent 前报预检错误。

## 唯一执行路径

Inspect Solver 执行 Provider → 现有 Inspect Scorer 评业务断言与专项诊断 → Inspect Metric 聚合 → 不可变 `results.json` → 报告与 Langfuse。

仅调用 DeepEval 公共 `a_measure` 和 `DeepEvalBaseLLM`；后者使用 Inspect 模型传输。每 Trial 新建 Metric 与模型适配实例，固定 `eval_mode=llm`、temperature=0、strict_mode=false、无请求重试，使用整项超时预算。单个意图判分失败时取消并等待其余在途请求，避免请求越过 Trial 边界。关闭 DeepEval 遥测和内部 Trace，不调用其 Runner、Cloud 上传或数据集执行器。

输入仅由实际 `turn_results` 与对应执行输入组成，保留所有实际 user/assistant 轮次和顺序；不用首问+末答代替完整对话，不补入尚未执行的用户回应，不传入 Oracle。

## 状态与权威数据

| 状态 | 条件 | 分数 |
| --- | --- | --- |
| SUCCESS | 完整有效意图集合，每个意图均有有效 yes/no 判断 | DeepEval 原始 0–1，零分保留 |
| ERROR | 执行或评测无效、缺轮次、仍待澄清/确认、步骤耗尽或运行失败、超时、抽取为空、缺判分或结果无效 | null |
| NOT_APPLICABLE | module 场景，或只有一个实际用户轮次 | null |

按 Trial 保存于 `cases[].diagnostic_metrics.conversation_completeness`：分数、状态、原因、输入 SHA256、轮次数、逐意图判断、已知 token 用量。证据文件为 `diagnostics/<case>/<trial>.json`。不会用缺失值补零或丢弃失败意图后重算得分。

运行级 `diagnostic_metadata` 固定库版本、库与模板源码哈希、模型、端点哈希、参数和适配器版本；`summary.diagnostic_metrics` 使用 Inspect 原生 frequency/mean 计算一次。均值仅描述成功判分，必须与 SUCCESS/ERROR/NOT_APPLICABLE 计数和成功样本数一起阅读，不能当作总体通过率。诊断 token 用量独立保留，不改变既有语义 Judge token Gate 的口径。

`summary.json`、Markdown 报告与 Langfuse 仅读取已保存结果。Langfuse 导出 `diagnostic.conversation_completeness.status/score`，运行汇总导出 `mean_score/scored_trials/<status>`；缺失分数不上传数值，默认不导出对话、意图或原因正文。沿用显式 hosted 导出和已启用的本地 loopback 交付规则。

比较要求诊断配置与 fingerprint 一致；与旧基线或不同配置比较会明确拒绝，不混合指标语义。历史结果缺少新字段时仍可只读加载。

## 验收范围

自动测试使用真实 DeepEval 与 Inspect mock 模型验证 public API、0/1 得分、空意图/部分判断、超时、逐 Trial 隔离、环境凭据不触发联网、实际多轮映射、正式落盘和 SDK 导出。状态化 mini_agent/SQLite 用例验证业务 FAIL 不受诊断分数影响。它们是框架验收，不能替代真实 Judge 的准确性校准。

下一道验收是人工标注需求遗漏、取消、变更和提示注入等样本，核对逐意图判断。此前不配置诊断发布阈值，也不因该分数高就宣布业务动作成功。

## 真实校准试验与复核入口

2026-10-28 已执行真实 Agent 小样本试跑和 **24 条固定对话 × 3 次真实 Judge 评判**。数据为预先编写的合成样本，参考标签仍待人工审核；不能称为人工金标或准确率。结果和局限见[试验记录](conversation_calibration_20261028.md)。

复现实验（会调用付费 Judge，须显式提供独立环境文件；输出目录须不存在）：

```sh
../../.venvs/evaluator/bin/python examples/conversation_calibration.py \
  --corpus datasets/calibration/conversation_v1.json \
  --judge-env .env.deepseek_judge \
  --epochs 3 --output-dir artifacts/my_calibration
```

示例使用原生 Inspect Task、Epochs、Scorer 和 Metric。对话已固定，不运行 Agent；`mockllm/model` 仅是无需生成的 Task 宿主，Scorer 内部调用真实 Judge。参考意图和期望区间只用于保存结果之后的对照，Sample target 为空。Inspect `.eval` 是权威结果；`projection.json` 为投影，`analysis.json` 保存每条对话的重复分数和与草稿的差异，不计算人工准确率。

明确把本次合成正文交付给已启用的本地 Langfuse：

```sh
../../.venvs/evaluator/bin/python examples/conversation_calibration_review.py \
  --run-dir artifacts/my_calibration \
  --corpus datasets/calibration/conversation_v1.json \
  --local-config .env.langfuse.local.json --include-content
```

交付前验证原生日志哈希、原始语料与快照、投影与日志中的分数。该适配器不运行评测、不重新计算均值、不创建人工评分。它创建待审队列，分别上传每次评判的状态和已保存分数；null 不补零。仅成功回读全部分数和待审条目后记录 `VERIFIED`。

`review_delivery.json` 保存进度；同一进程持有文件锁。若仅分数写入中断，可在确认观察记录已接受的三个检查点使用 `--resume-scores`，以相同 ID 更新分数且跳过观察记录。观察记录、配置或队列创建的接受状态不确定时，必须核对服务端后再恢复，不可删除回执盲目重传。已完成的交付不重复创建队列。

人工在 Langfuse 选择 `CONFIRM_DRAFT`、`CORRECT_DRAFT` 或 `AMBIGUOUS`，并用评论写明有效意图、取消／替代关系、期望分数区间或非数值状态及理由。此次实现只负责复核交接；校准专用人工结论的不可变导入与发布阈值审批尚未实施，不会把队列完成状态自动当成 Gate 依据。已有业务 verdict 的复核导入保持原有用途。
