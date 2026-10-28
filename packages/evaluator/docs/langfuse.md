# Inspect、DeepEval、Evaluator 与 Langfuse 的职责和接入

2026-10-28 指标去重已实施：分组与分类计数复用 Inspect grouped/frequency；通过率统一适用性规则，P50/P95 和 Judge Token 汇总保存在正式结果，由比较与 Gate 消费。新口径标识 business-metrics-v2，跨口径比较需重跑基线。Judge 保留整次多维尝试重试，原生请求重试关闭。

2026-10-28 选型更新：Inspect 保持唯一执行和正式评分入口；DeepEval 可作为其 Scorer 内的专项算法库，选定复用 3 个 RAG 指标和 2 个多轮指标。当前仅完成[逐项选型与接入验收清单](metric_dictionary.md)，适配代码、依赖和生产接入尚未实施。此前删除的是已由 Inspect 覆盖的 G-Eval 客户端及重复执行路径，不构成对专项算法复用的限制。

2026-10-24：新增[本地 Langfuse 与评测自动交付](local_langfuse.md)，显式启用本机配置后，每次评测自动同步本地原生看板。正式结果不变，Cloud 仍需独立显式导出。

以下为 2026-10-20 的历史 Cloud 验收记录：生产执行路径统一为 Inspect。Langfuse 使用官方 SDK 5.0.2 接入 Cloud，不 clone、不 fork、不自建网页。Cloud 凭据保存在本机受保护且被 Git 忽略的 `.env.langfuse`。查询用户 v2.0 的 42 个真实模型案例已完成全量执行。当前为一个原生分析看板（9 个组件），配合原生 Tracing、Scores Analytics 和 Experiments；重复的失败页与空工具页已删除。云端回读验证 520 条 Score，其中 42 条是场景分类标签，不是新增判分。人工标注往返仍待验收。

## 唯一职责与权威来源

| 能力 | 主要负责方 | 本项目保留内容及必要性 |
| --- | --- | --- |
| Task、Sample、Solver、Scorer、epochs | Inspect AI | `inspect_engine.py` 仅适配既有 Provider 和冻结契约；没有第二套 Trial 调度 |
| 通用值比较、现有四项 Rubric Judge | Inspect AI | `native_scoring.py` 保留业务类型/空白语义；`judges/inspect.py` 把业务 Rubric 映射到原生 `model_graded_qa` |
| 声明忠实度、检索排序/覆盖、整段对话需求/记忆 | DeepEval 专项算法，经 Inspect Scorer 调用（选定，待接入） | Evaluator 只适配证据、模型传输、状态和结果；不再自研同义算法，不使用 DeepEval Runner、Dataset 管理或托管平台 |
| 正式指标聚合 | Inspect AI 的 Metric 阶段 | `inspect_metrics.py`、`stability.py` 保留业务分母、无效证据、全部 Trial 稳定性语义；原生 mean 处理相同语义的均值 |
| 环境隔离、状态独立核验、确认/权限/副作用 | Evaluator Provider 与业务 Scorer | 原生通用评分无法推导业务数据库事实，必须保留 |
| 执行状态/有效性/质量结论、关键项否决 | Evaluator 的 Scorer 扩展 | 业务判定政策；由 Inspect 调用，不构成另一套运行引擎 |
| 数据生成、审核、冻结 | Builder（外部） | Evaluator 只校验冻结契约、能力快照、Hash 和执行适配，不维护第二份可编辑 Dataset |
| 原始执行记录 | Inspect EvalLog | `.eval` 是执行记录；`results.json` 是正式业务结论快照；报表、JSONL、Langfuse 都是其派生视图 |
| Trace、实验结果、看板、筛选 | Langfuse | `observability.py` 只导出保存的 Trace/Score，带来源 Hash、稳定 ID；不执行实验、不重算指标 |
| 人工复核操作与编辑 | Langfuse Annotation | `adjudication.py` 校验业务标签、来源与修订；本地文件只是不可编辑的导入快照 |
| Error Taxonomy | Evaluator | `taxonomy.py` 是内建标签定义；本次 Provider 诊断可补充标签；导入记录保存版本与有效标签集 Hash |
| 基线选择、可比性、发布门禁 | Evaluator | 唯一基线为 compare 的显式输入；Gate 读取该比较与正式结果，不读取 UI 中临时选择的实验 |
| 额外语义评分实验 | Langfuse（可选） | 使用独立实验分数，不写入正式质量结论或 Gate |

正式评分标准以本地冻结 Rubric/契约为权威，不在 Langfuse 建立另一份可编辑的正式评分标准。人工评分保留 `source=ANNOTATION`；正式导出分数由 API 写入，metadata 带 `authority=immutable_results`。

同一指标只保留一个正式实现。Inspect 原生能力满足同一语义时继续复用；已封装的专项算法优先复用 DeepEval；业务契约、独立证据和发布政策留在 Evaluator。DeepEval 候选验收后可进入正式结果，是否进入 Gate 单独配置；Langfuse 只展示这份已保存结果。Plan Quality / Step Efficiency 的公共 Trace 接入尚未验证，不纳入首批。

Inspect 可能多次请求运行中的指标。本项目在完整的 Case × Trial 到齐之前不发布业务汇总，完成时计算一次并缓存。`agent_case_pass_rate` 是历史字段别名，复用 `strict_assertion_pass_rate` 的值。`stability.trial_pass_rate` 有自己的冻结分母定义，不得在看板上混称为同一通过率。新口径必须改版本并重跑基线。

## 已删除的重复路径

- DeepEval G-Eval 客户端、模型封装、DeepSeek 旧别名、运行设置桥、TestCase 转换、Inspect 中的 DeepEval 桥。
- DeepEval 直接依赖、安装选项，以及只验证已删除实现的测试；替代的评分/隔离/失败/超时测试覆盖真实 Inspect Scorer。
- Runner 在 Inspect 结束后再次执行汇总的路径。
- `adjudicate` CLI、`append_adjudication` Python 写入口及旧写入模型。历史 `adjudications.jsonl` 保留作历史材料，不作为新复核的可编辑来源。

没有自研 Trace 页面或 Dashboard 可删除，因此不新建。保留的 Markdown/JSON 是可离线审计的派生交付文件，不是另一套交互平台。旧 DeepEval 文档标记为历史材料。

## 接入与命令

只在本机环境配置 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL`。Base URL 使用项目所属 Cloud 区域，不能混用项目密钥与区域。密钥不写入仓库或命令行参数，也不发到对话中。

```bash
# 从项目根目录显式加载本机配置；CLI 不自动读取 .env.langfuse。
set -a
source .env.langfuse
set +a

# 显式 Cloud 导出；普通 run 仅按独立本机配置同步本地 Langfuse。
.venv/bin/python -m eval_framework.cli export-langfuse \
  --run-dir artifacts/eval_run_ACTUAL

# 已确认需要上传用户输入与最终输出时，首次导出加 --include-content。
# 在 Langfuse Annotation 完成复核后：
.venv/bin/python -m eval_framework.cli import-reviews \
  --run-dir artifacts/eval_run_ACTUAL
```

默认只上传身份、状态、已计算分数、事件类型和证据关联，不上传业务输入、回复、数据库快照或事件 payload。`--include-content` 只增加用户输入与最终输出；自由文本可能含业务敏感信息，应在首次导出前确认内容。不能用后续导出切换内容模式。

导出采用官方 SDK 的 OTLP 与 Scores API。这样既能保留原始时间，也无需启动 Langfuse 的实验执行循环。每个 Trial 是一个独立 Trace 和实验 item；同一 run 的稳定 experiment ID 将它们关联起来。事件是证据时间点，不伪造模型/工具 duration 或 Agent Graph 的调用边。新结果记录每 Trial 起止时间；旧结果没有该字段时使用 run 时间范围，并明确 `timing_source=run_bounds`，这类数据不能拿 Trace duration 当 Trial 耗时，应读取保存的 `execution.latency_ms`。无有效时间的事件在回执 `omitted_events` 中注明；原始证据仍在本地。

`langfuse_export.json` 在请求前写入 PENDING，绑定结果 Hash、项目指纹、内容模式；全部请求被接收后更新 ACCEPTED。Langfuse v4 的不可变 observation 不会可靠地按 ID 去重，因此导出逐批保存已接收 observation ID，重试只补传尚未接收的批次；成功导出后的再执行仅 upsert Scores。发送中断或部分接收留下 inflight ID，必须先回读核对再恢复，不能盲目重发；旧版 PENDING 回执也必须先核对。OTEL 请求禁用自动重试。Score ID、名称与原始日期保持一致。更换源文件或目标项目会被拒绝。ACCEPTED 仅表示 API 接收，仍需回读及页面验收。网络故障不修改 `results.json`，也不改变质量结论。参考 [Langfuse 数据更新约束](https://langfuse.com/faq/all/tracing-data-updates)。

Langfuse v5 的实验关联使用官方 `langfuse.experiment.*` OpenTelemetry 属性，Cloud 需支持该数据模型。此处没有创建另一份可编辑的 Dataset、Rubric 或基线选择。实验展示可并排查看，但是否允许作正式版本比较仍由本地 `compare` 判定。

## 分数与看板口径

| 分数前缀 | 内容 | 使用方式 |
| --- | --- | --- |
| `execution.*` | 执行状态、原始 Trial 耗时 | 状态筛选、单 Trial 耗时 |
| `context.scenario_type` | 冻结数据集的场景类别 | 供原生覆盖构成图使用；不参与判分或 Gate |
| `evaluation.validity` | VALID / INVALID | 无效证据单独筛选 |
| `quality.*` | 质量结论、确定性分数 | INCONCLUSIVE 保留类别；无效时不上传数值质量分 |
| `assertion.{序号}.{名称}` | 每条业务断言的 PASS / FAIL / UNKNOWN | 同名断言不同参数不会覆盖；证据 ref 映射至对应 observation ID |
| `judge.*` | Inspect Judge 状态与已计算分数 | 与 Langfuse 自行运行的实验 Judge 区分 |
| `run.*`、`stability.*` | 保存的整轮汇总快照 | 仅附着在 `role=run_summary` 的 Trace 上 |

当前验收配置：

1. 原生看板：四张紧凑指标卡读取已保存的案例数、严格断言通过率、中位耗时和最大耗时；下方展示最慢 10 例、六类断言结果表、耗时分布、九类场景覆盖及 42 例精确耗时表。通过率不另算。分布及数量是探索统计，不替代正式 Gate 指标；Langfuse 直方图使用近似分箱，精确耗时以逐例表为准。
2. Tracing 保存视图「查询用户 v2.0 · 本轮42例」：固定 run_id、根 observation、排除汇总 EVALUATOR；一行一个 Trial。展示案例名、耗时、场景类别、评测有效性、执行状态和质量结论，点击案例进入执行记录。
3. Scores Analytics：本轮入口限定 2026-10-20 15:40–15:45（GMT+8），默认选择意图匹配断言，共 42 条。只有同一评分目标、匹配样本上的独立评分才适合做一致性比较；当前没有 Judge 数据，不构造混淆矩阵。单轮批量上传的时间趋势也不代表版本质量趋势。
4. 版本对比：复用原生 Experiments；以本地 comparison.json 的可比性与基线 Hash 为准，Langfuse 的 UI 选择不改变 Gate 基线。

已删除旧失败分析和空工具质量看板及 7 个重复组件。当前只覆盖意图模块，未采集完整工具、Token、费用、权限安全或业务终态数据，不补造“五层能力”评分。看板固定到 `eval_run_efc666b921fe4dfca5bae078ac55cb53`，每项总体指标只读取一条汇总，组件用 max 取唯一值，不跨 run 聚合比例。配置与原生视图链接在 `artifacts/langfuse_full_20261020_154130/cloud_setup.json`。

看板 API 的 filters 使用界面字段名（例如 `Metadata`、`Score Name`、`Score String Value`），不能直接照搬 Metrics API 的 `traceId`。本次通过 `Metadata.run_id` 固定范围。所有展示数值已在页面核对；后续查看历史运行时，时间范围须包含运行日期。

## 结构化人工复核

在 Langfuse 创建 categorical score config `review.decision.v1`，类别为 `UPHOLD`、`OVERRIDE_PASS`、`OVERRIDE_FAIL`、`CONTRACT_DISPUTE`、`INCONCLUSIVE`。通过原生 Annotation 界面给对应 Trial 评分。导入只接受该名称、`source=ANNOTATION`、正确 Trace 关联、有效类别与具名 reviewer。

comment 使用以下结构（这是复核结果的业务结构，不是新的评分 prompt）：

```json
{
  "reason": "根据原始状态与事件确认结论",
  "primary_cause": "PROTOCOL_NAMING_MISMATCH",
  "secondary_causes": [],
  "optimization_direction": "dataset_contract"
}
```

无归因时 primary_cause 为 null。优化方向限 `none`、`prompt`、`tool`、`agent_logic`、`environment`、`dataset_contract`。标签定义与校验权在 Evaluator；非法/缺失字段导致整个批次拒绝导入，不会静默落为合法结论。

`langfuse_reviews.jsonl` 是追加的来源修订快照，以源 score ID 和内容 Hash 去重；`langfuse_review_sync.json` 记录本次完整同步的 active revisions。Cloud 修改产生新修订，Cloud 删除使 active 清单移除旧修订，本地保留历史审计记录。自动结果和 Gate 不被人工分数直接覆盖；争议必须通过契约/代码修正与重新评测解决。

## 验收边界

离线测试使用真实 Inspect Model Grading 与真实 Langfuse SDK，仅替换模型输出或 HTTP 传输。覆盖稳定 ID、失败重试、未知状态、结果不可变、原时间、来源绑定、分页字段、标签、修订与 Cloud 删除。

2026-10-20 已完成 Cloud 实连：先验证 5 个 Trial、71 条评分的冒烟结果，再执行全量 42 个案例，每例 1 次。全量均为 COMPLETED / VALID / PASS。首次验收 478 条评分，改版新增 42 条场景分类后共 520 条，回读值与来源一致。验收发现旧导出会重传不可变 observation，已修复检查点并备份、清理、恢复本轮云端镜像；现为 42 个唯一 Trial、293 条唯一 observation，无重复，结果 Hash 与评分未变，未再次调用模型。原生看板、Tracing 和 Scores Analytics 已验收；5 项 PENDING 复核记录保留。运行说明及证据位于 `artifacts/langfuse_full_20261020_154130/README.md`、`verification.json`。

5 例冒烟与 42 例全量的本地比较正确返回 INVALID_COMPARISON，不能从原生图表推断版本提升。尚未验收真实人工标注往返、多 Trial 稳定性、实际工具执行或语义 Judge；未建立正式发布基线。人工复核时需要结合本地报告，因本次导出未包含业务输入与回复。Inspect 与旧 G-Eval 的评分分布不宣称相同；业务上线前仍需校准语义阈值。

参考：[Inspect Scorers](https://inspect.aisi.org.uk/scorers.html)、[Langfuse OpenTelemetry Experiments](https://langfuse.com/docs/evaluation/experiments/experiments-via-opentelemetry)、[Langfuse Annotation](https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-ui)。
