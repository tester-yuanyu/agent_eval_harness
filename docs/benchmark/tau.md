# 真实 nanobot 的官方 τ 领域试点

这是独立的**英语零售领域套件**，保留官方任务、领域策略、数据库、工具、动态用户模拟器、编排器及 `EvaluationType.ALL` 奖励计算。被测参与者是实际 nanobot `AgentLoop`，包括其会话与工具循环。

已完成固定 v1.0.1 版本的 **retail 任务 `0`、1 次执行，官方 reward 为 `1.0`（PASS）**。Agent 模型是 `deepseek-flash`，官方用户模拟器使用 `openai/deepseek-flash`。终止原因为 `user_stop`；证据校验完整，包含 13 个 generation、5 个 tool 和 4 个 turn 事件。这是有界集成试点，与文件及决策套件的 444 个实例、612 次执行分开统计，不代表全领域复现或官方排行榜成绩。[作品集报告](../../reports/file-tools-v2/index.html)保留了官方摘要和来源 Hash。

## 版本与来源

- 上游：[sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench)。
- 固定发行版：`v1.0.1`；解析后的 commit 为 `fc0055dc4e0a316c3f83133267fbd6faaa770992`。
- 许可证：上游 MIT，保存在下载源码的 `LICENSE` 中。
- 适配时核对的上游 2.0 已变更英语任务、提示词与评分；当时的上游 README 将 v1.0.1 保留为可复现的 1.x 比较版本。本适配明确固定该版本，结果不属于 2.0。
- 上游代码与数据下载到 Git 忽略的 `.sources/tau2-bench`；本仓库不复制或改写其大量任务原文。

## 执行边界

nanobot 只接收公开领域策略、工具 Schema 与对话消息，不接收私有 τ Task、预期动作、评测条件或模拟用户的私有场景。用户场景仅提供给官方用户模拟器。

每次 nanobot 工具代理调用都会交给官方编排器。官方环境执行工具并记录 `ToolMessage`，结果随后返回原来等待中的 nanobot 调用。运行同时保留官方对话 JSON 和 nanobot generation/tool JSONL 证据。此领域禁用 nanobot 默认的 shell、文件系统、MCP、插件发现与消息工具，只注册官方零售工具定义。

Inspect 编排外层任务批次，官方编排器负责内部模拟及奖励计算。DeepEval 的 `OfficialTauRewardMetric` 通过共享结果格式原样呈现保存的官方 reward，并与文件工具指标分开报告。GEval 不替代官方奖励，也不改写官方数据库成功条件。

## 准备与运行

复制 [`tau.example.json`](../../configs/benchmark/tau.example.json) 为 Git 忽略的本地配置，填写 `nanobot_root`。独立 τ 环境使用 Python 3.12 或 3.13。

```bash
.venvs/evaluator/bin/python -m eval_framework.benchmark.tau_adapter prepare \
  --config /path/to/local-tau.json --base-python /path/to/python3.12

.venvs/evaluator/bin/python -m eval_framework.benchmark.tau_adapter validate \
  --config /path/to/local-tau.json --output artifacts/tau-validation

.venvs/evaluator/bin/python -m eval_framework.benchmark.tau_harness \
  --config /path/to/local-tau.json --env-file /path/to/local.env \
  --output artifacts/my-tau-retail-pilot
```

`prepare` 在 `.venvs/tau` 下载并安装依赖，保留 Evaluator 的独立环境。`validate` 检查固定源码与所选官方任务，不调用模型。`tau_harness` 使用指定环境变量中的凭据，真实调用 Agent 与用户模拟器；`--env-file` 显式读取本地环境文件，不把值写入配置。已有非空结果目录会被拒绝，以保留运行证据。只需要官方适配器输出时，也可使用底层 `tau_adapter run`。

默认明确选择 retail 任务 `0`，该固定任务没有非空自然语言断言。其他任务若在官方 `reward_basis` 中包含 `NL_ASSERTION`，可能需要上游自然语言断言模型；未启用 `allow_official_judge` 时会校验失败，适配器不会静默跳过断言或换用其他 Judge。启用后，固定上游 Judge 使用 `gpt-4.1-2025-04-14`，凭据取自 `official_judge_api_key_env` 指定的变量（默认 `OPENAI_API_KEY`）。执行进程只继承明确选择的 Provider 凭据和基本平台变量。

## 输出与限制

Harness 输出下的 `official/summary.json` 记录源码与任务 Hash、公开策略 Hash、运行包版本、实际 τ 导入路径、nanobot 工作树身份、模型、各次奖励与实验限制。每个任务及执行序号保留 `official-result.json`、`nanobot-events.jsonl`、`user-simulator-events.jsonl`、标准化的 `benchmark-observation.json` 及独立会话目录。适配器校验源码 commit、已跟踪文件清洁状态和实际导入的源码位置。

已交付运行位于 `artifacts/benchmark-v2/tau-retail-pilot`，根 `results.json` 保存标准化的 Inspect/DeepEval 结果。公开报告生成器使用 `--tau-run artifacts/benchmark-v2/tau-retail-pilot/official/summary.json` 读取官方摘要。该运行已完成 Langfuse 上传与服务端完整回读：1 次执行、23 个观测、2 条评分的内容与节点关联均已核对；绑定结果来源的验收回执保留在本地运行目录。

`COMPLETED` 表示每次计划执行都有官方数值奖励，数值可以是零；它不表示 Agent 通过。`PARTIAL` 与 `FAILED` 将缺失奖励保留为 null。每条结果另行记录 `evidence_complete`；空日志、参与者缺失或未结束的调用不能通过证据校验。官方提前终止会被明确记录，官方奖励仍保持原值。恰好在步数上限收到的工具结果会在取消 nanobot 前保存。

当前范围是有界的英语零售文本集成。全领域重复执行、τ 2.0 多语言或语音领域、独立校准的 Judge 都尚未完成。`eval_framework.benchmark.tau_harness` 提供 Inspect 外层编排、原样包装官方 reward 的 DeepEval 指标和共享轨迹导出格式；本地执行成功与 Langfuse 交付验证分别验收。公布结果时必须同时披露用户模拟模型、nanobot 适配方式和运行依赖等实验控制项。
