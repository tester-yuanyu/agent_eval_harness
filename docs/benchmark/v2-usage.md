# 三层评测与轨迹评分

此版本沿用 Inspect 调度与日志、DeepEval 正式评分和 Langfuse 展示。GEval 是显式事后调用的 LLM Judge，当前只作未完成人工校准的诊断。历史 file-tools-v1 数据与 1,800 次执行保持不变。新资产是 file-tools-v2（程序模块 60、关键链路 60、E2E 300）及 model-decisions-v1（独立模型决策 24）；参数变体和任务族分别报告。

本轮已完成 444 个任务实例、112 个任务族、612 次原始执行与 v2.1 复评：程序模块 60/60、模型决策 72/72、链路 151/180、端到端 273/300 通过。[作品集已生成](../../reports/file-tools-v2/index.html)，[七项问题清单](status-v2.md)记录证据与剩余工作。六组已导出的 Langfuse 运行均完成服务端回读验证；链路与端到端分别补存 179 / 479 个原文证据子节点，不增加 Agent 或 Judge 执行次数。

GEval 主评审 3,274 个适用项中 3,273 项已评分，1 项因 ValidationError 未评分；稳定性运行另含 69 个相同证据项 × 2 次，共 138 条分数，平均极差 0.031884、最大极差 0.4。作品集显示主评审与重复评审合计 3,411 条有效分数；两者都不增加 Agent 执行次数。

## 各层真实执行边界

| 层次 | 执行方式 | 结果含义 |
| --- | --- | --- |
| 程序模块 | 在 nanobot 解释器中调用真实 ToolRegistry 和文件工具，不调用模型 | 注册、参数校验、读取范围、编辑保护、文件与目录行为 |
| 模型决策模块 | 真实 nanobot Provider 一次 chat 调用，提供真实工具 Schema，不执行工具 | 工具选择、参数类型与语义、应该不调用工具时的弃权 |
| 关键链路 | 真实 AgentLoop，采集每次工具前后状态和每轮快照 | 指定步骤参数、轮次状态、调用依赖、错误恢复及最终结果 |
| 端到端 | 从完整请求到独立工作区终态 | 文件任务完成、过程约束、调用成本和时延 |

模型决策、程序模块与完整 Agent 的成功率分别计算。Provider 内部可能重试，一次 chat 调用不保证恰好一个 HTTP 请求。pytest 框架回归数量不计作这些 Benchmark 题目。

## 运行

根目录执行；复制 [nanobot.example.json](../../configs/benchmark/nanobot.example.json) 为本地配置并填写源码、解释器和服务信息，密钥只通过环境变量读取。模型决策、链路、端到端及 Judge 命令会调用真实服务，程序模块和静态校验不调用模型。可用 `--env-file /path/to/local.env` 显式读取本地环境文件，不能把凭据写进跟踪配置。

专用数据生成器分别位于 `data/benchmarks/file-tools-v2/build_dataset.py` 和 `data/benchmarks/model-decisions-v1/build_dataset.py`，可确定性重建相同字节；不同内容不能覆盖已冻结版本。原通用 `packages/dataset-builder` 仍保留，但本轮数据不通过该入口生成。

```bash
# 静态结构/冻结Hash；只对Agent任务做参考终态检查，不冒充模块实跑。
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli validate --dataset data/benchmarks/file-tools-v2

# 程序模块，不需要模型密钥。
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli run \
  --dataset data/benchmarks/file-tools-v2 --level module \
  --config configs/benchmark/nanobot.local.json --output artifacts/modules

# 真实模型决策；关键链路和E2E换成file-tools-v2及相应--level。
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli run \
  --dataset data/benchmarks/model-decisions-v1 --level module --repeats 3 \
  --config configs/benchmark/nanobot.local.json --output artifacts/decisions

# 关键链路，每个实例 3 次真实执行。
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli run \
  --dataset data/benchmarks/file-tools-v2 --level chain --repeats 3 \
  --config configs/benchmark/nanobot.local.json --output artifacts/chains

# 端到端，本例每个实例 1 次；--repeats 3 才是 3 次稳定性实验。
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli run \
  --dataset data/benchmarks/file-tools-v2 --level e2e \
  --config configs/benchmark/nanobot.local.json --output artifacts/e2e

# 在保存的 Agent / 模型决策轨迹上调用 GEval；不重新执行 Agent。
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli judge \
  --source artifacts/decisions --dataset data/benchmarks/model-decisions-v1 \
  --config configs/benchmark/judge.local.json --repeats 3 \
  --output artifacts/decision-judge

# 从保存证据生成报告，或导出并验证Langfuse。
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli report --run artifacts/decision-judge
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli export-langfuse \
  --run artifacts/decision-judge --dataset data/benchmarks/model-decisions-v1
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli verify-langfuse \
  --run artifacts/decision-judge --dataset data/benchmarks/model-decisions-v1
```

复制 [judge.example.json](../../configs/benchmark/judge.example.json) 为本地 Judge 配置，并设置其 `api_key_env` 指定的环境变量。Judge 的 `dimensions` 配置可选择 `action_appropriateness`、`recovery_appropriateness`、`response_groundedness`。模型决策专项建议仅选择动作合理性。`--repeats` 重新评价同一执行证据，用于测量 Judge 波动；它不增加 Agent 执行次数。每个评分包含版本、范围、对应事件ID、分数、依据及真实Judge调用。失败/证据不足记录为空分，恢复不适用需有完整证据支持。

## 评分与Trace

确定性检查使用 DeepEval BaseMetric：任务终态、工作区策略、模块结果、模型决策工具/参数/Schema、工具允许性/Schema、逐轮状态和指定调用检查点。GEval 评价可观察动作、恢复片段和回复事实依据，分数为0–1评价尺度，不是正确概率，也不读取隐藏思维链。

事件级分数绑定实际 generation/tool/turn 节点；任务级汇总绑定根节点。每次工具的前后快照和每轮快照保存在观察证据中。Langfuse 接收已计算分数，没有另一套正式评分。没有明确语义预期的工具调用，其Schema分只代表结构正确，不能称全部参数语义均有真值。

Langfuse 的 V2 读接口可能将文件正文中的 JSON 字符串解析为对象，丢失字符串类型和空白。此时普通导出仍保留可见内容，但严格回读不能据此宣称逐字相同。可显式补存原始字段的编码证据，然后再次回读：

```bash
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli export-langfuse-evidence \
  --run artifacts/my-chain-pilot --dataset data/benchmarks/file-tools-v2
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli verify-langfuse \
  --run artifacts/my-chain-pilot --dataset data/benchmarks/file-tools-v2
```

补充证据以 `saved-exact-metadata` 子节点保存完整字段的 Base64 与 SHA256，并绑定原节点、结果来源 Hash 和独立回执。验证同时检查原结构化内容、补充原文与父子关系；缺失或篡改不能通过。补充节点只用于展示保存的证据，不是新 Agent 步骤、模型调用、Judge 评分或 trial。原执行、原分数和原始导出回执保留不变。

评分 v2.1 强化了模块读取输出与目录条目的独立校验、模型决策参数类型 / Schema 校验以及声明过的恢复依赖。旧执行通过 `regrade` 写入新目录，保留原始观察、原评分及执行来源 Hash。评分规则变化后的数字不得直接解释成模型能力提升。

```bash
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli regrade \
  --source artifacts/chains --dataset data/benchmarks/file-tools-v2 \
  --output artifacts/chains-scored
```

复评不重跑 Agent。后续 Judge 的 `--source` 可使用完成的 `chains-scored`，但不能使用已经附加 Judge 输出的另一份 Judge 运行。输出目录不得放在来源运行目录内；恢复时要求来源、配置和代码身份一致。`.running` 表示运行锁，不能在未确认进程结束时删除。

## Judge量化与独立人工校准

输出适用数、已评分数、缺失/错误数、覆盖率、分布、各维度均值、相同证据重复评分范围和独立Judge用量。事实正确和硬约束由确定性Oracle决定；未经人工校准的GEval分数只作诊断。

```bash
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli calibration-sheet \
  --run artifacts/decision-judge --output artifacts/human-labels.json
# 独立人工完成human_score等字段后，显式提供待检验阈值及版本。
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli calibration-check \
  --run artifacts/decision-judge --labels artifacts/human-labels.json \
  --threshold 0.8 --threshold-version exploratory-example \
  --output artifacts/calibration-check.json
```

示例0.8不是已校准通过线。空白表不构成人工审核；没有独立标签时不能报告人类一致性、误放率或误杀率。标注页省略 Judge 预测以减少锚定，同一证据重复评分只标注一次。

已提供 [calibration-sample.json](../../reports/file-tools-v2/calibration-sample.json)：从 chain-judge 按稳定 Hash 抽取动作、恢复、回复依据三个维度各 12 条，共 36 条空白标注。所有 human_score 均未填写，不能视为人工校准结果。完成独立标签后仍需在另外的留出样本上验证阈值。


## 生成公开作品集

只将已完成、唯一且完整的运行交给生成器。`--runs` 放正式执行或确定性复评；`--judge-runs` 放事后诊断。不要同时把同一次执行的原版和复评版作为两份新执行，也不要把 Judge 运行放进 `--runs`。

```bash
python3 scripts/build_layered_report.py \
  --runs artifacts/benchmark-v2/modules60-scored \
    artifacts/benchmark-v2/decisions24x3-scored \
    artifacts/benchmark-v2/chains60x3-scored artifacts/benchmark-v2/e2e300-scored \
  --judge-runs artifacts/benchmark-v2/decision-judge \
    artifacts/benchmark-v2/chain-judge artifacts/benchmark-v2/e2e-judge \
    artifacts/benchmark-v2/judge-stability \
  --output reports/file-tools-v2 \
  --tau-run artifacts/benchmark-v2/tau-retail-pilot/official/summary.json
```

以上路径对应本轮已完成的实际目录。τ 试点的官方摘要通过 `--tau-run` 独立汇总，不把其包装结果加入文件套件的 `--runs`。没有官方摘要时省略该选项，报告会标记缺少 τ 运行证据。尚未完成的执行会被拒绝，不用缺行报告充当完整运行。

输出包含：

- `index.html`：离线可读，按四类执行方式显示结果、轨迹评分、Judge 统计与七项问题状态。
- `summary.json`：实例 / 任务族 / trial 数、分层判定、适用分母、重复波动、独立用量及来源 SHA256。
- `results.jsonl`：公开逐 trial 摘要，只保留身份与评分元数据，不复制原始提示词、工具结果或凭据。
- `README.md`：可用于作品集正文的结果与限制说明。

本地详细报告链接依赖原目录，公开 HTML 表格本身不需要脚本、CDN 或网络。Langfuse 回执必须绑定相同来源 Hash；回执没有 URL 时保留 Trace ID，不猜测目标地址。导出接收、服务端读回和浏览器检查是不同验收阶段。Langfuse 已有[真实界面抽查截图](../../reports/file-tools-v2/langfuse-step-scores.png)，显示模型决策节点的 Schema、参数、工具选择与 GEval 分数及 Judge 子节点。截图属于界面抽查；六组导出的服务端完整回读均已单独通过。公开报告的本地文件浏览受安全限制，HTML / JSON / 链接静态检查不算报告浏览器验收。生成器会保留并链接输出目录内已有的截图和人工标注起点文件。

事后 Judge 放在原 Trace 下时，根 Span 的时间跨度包含原执行与后续评审之间的间隔。报告中的 Agent latency 保留原始执行时长，Judge 用量独立统计；不能以该根 Span 的墙钟跨度推算 Agent 响应速度。

## τ 官方领域试点

已完成 τ²-bench v1.0.1 的 retail 任务 0、1 次 trial：官方 reward 1.0，标准化结果为 PASS，证据完整。Agent 为真实 nanobot AgentLoop + `deepseek-flash`，官方动态用户模拟器使用 `openai/deepseek-flash`。该试点另计，不加入文件与决策套件的 444 个实例 / 612 次执行，也不代表全量官方成绩。

```bash
# 环境准备和无模型验证见 tau.md；此命令会调用真实 Agent / 用户模型。
.venvs/evaluator/bin/python -m eval_framework.benchmark.tau_harness \
  --config configs/benchmark/tau.local.json --env-file /path/to/local.env \
  --output artifacts/my-tau-retail-pilot
```

Inspect 编排外层批次，官方 orchestrator 负责内部对话、工具、用户模拟和 `EvaluationType.ALL` 奖励。DeepEval `OfficialTauRewardMetric` 原样暴露已保存的官方 reward，不用 GEval 替换。官方证据保存在运行目录的 `official/`，共享结果为根目录 `results.json`。来源固定、奖励语义、自然语言断言限制和更多命令见 [τ 说明](tau.md)。

## 当前架构与七项问题

| 部分 | 当前职责 |
| --- | --- |
| 专用生成器 + 冻结资产 | 确定性构建任务 JSONL / Manifest，区分公开输入与私有预期 |
| Inspect | 调度执行和原生日志；Scorer 桥接调用 DeepEval，不维护新主线的第二套判分 |
| 自研执行与证据层 | 模块 / 决策 / Agent 适配、工作区初始化、独立状态采集、Oracle、检查点、版本与恢复 |
| DeepEval | 以确定性证据执行正式指标，保留诊断指标的角色 |
| GEval | 调用评审模型评价公开动作、错误恢复片段和回复依据；未经人工校准 |
| Langfuse 与报告 | 展示既有证据与相应节点评分，量化覆盖、缺失、重复波动和用量 |
| τ 独立适配 | 已跑通 v1.0.1 retail 单任务试点；保留官方任务、动态用户与奖励，Inspect 编排外层批次、DeepEval 原样呈现 reward |

模块 / 链路 / E2E、GEval 的角色、逐步评分、τ、架构、Trace 和 Judge 量化七项问题的完成证据与剩余工作，逐项见 [status-v2.md](status-v2.md)。历史协议、通用 builder、mini_agent 与旧 Inspect 评分代码尚未全部删除，不能把新主线的职责划分误写成整个仓库已无兼容代码。

## 仍需区分的范围

- 当前文件任务没有覆盖完整nanobot产品的MCP、长期记忆、会话持久化故障、渠道和浏览器。
- 文件链路采用固定追问。τ领域套件的动态用户是独立适配，不会自动让文件套件具备动态用户。
- 调用先后与参数检查不等于完整语义数据血缘证明；没有声明预期的每个动作不承诺有独立语义真值。
- 合成任务未经过用户逐条人工审核；继承v1的holdout已经运行过，不冒充新的未见验收集。
- GEval人工校准仍需真实独立标注。相同模型家族作为Agent与Judge的偏差尚未通过跨模型对照排除。
- τ试点固定来源、领域、任务子集及官方reward，不能冒充全量官方排行榜成绩。
