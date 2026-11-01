# Agent Evaluator

本包提供工具型 Agent 的 **任务数据集 + Harness** 主入口：Inspect 执行与记录，DeepEval 计算新基准正式分数，Langfuse 接收保存的结果。首个真实 Agent 接入为独立进程中的 nanobot，任务覆盖文件读取、修改、多文件流程、多轮变更和异常处理。

仓库总入口见 [Agent Eval Suite](../../README.md)，真实实验与作品集见 [portfolio](../../docs/benchmark/portfolio.md)。以下命令均在仓库根目录运行。

## 快速使用

```bash
python3.11 scripts/setup.py --only evaluator
make demo

# 检查 300 条冻结任务、Hash 和参考执行，不调用模型
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli validate

# 真实评测：先按示例创建本地配置并设置模型密钥环境变量
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli run \
  --config configs/benchmark/nanobot.local.json \
  --limit 20 --split dev --output artifacts/nanobot-pilot

# 只读取保存的结果生成 HTML / Markdown 报告
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli report \
  --run artifacts/nanobot-pilot
```

`make demo` 使用确定性参考执行器，明确标记为离线自检，不计入真实 Agent 成绩。DeepEval 4.2.9 是默认依赖；Inspect 0.3.280 保留执行、调度和原生 `.eval` 日志。没有 mini_agent 需求时，`scripts/setup.py --only core` 安装同一基准核心而不安装该示例 Agent。

需要从本地 dotenv 加载凭证时，明确提供路径，且将全局选项置于子命令前：

```bash
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli \
  --env-file .env.benchmark run \
  --config configs/benchmark/nanobot.local.json \
  --limit 20 --split dev --output artifacts/nanobot-pilot
```

## 评分与证据

- **任务成功**：从真实初始/最终文件和回复重新计算独立 Oracle，不信任 Agent 自报成功。
- **工作区约束**：检查未授权结果变动及允许的工具范围；任务失败与环境失效分别呈现。
- **工具正确性**：DeepEval 工具选择诊断，不因等价合法工具路径单独否决任务。
- **响应质量**：可选 G-Eval 为诊断；未校准的 Judge 不改变正式结论。
- **稳定性与效率**：报告实际 Trial、重复执行结果、时长和观测到的 token 用量；未知费用不写成零。

数据集目前为 300 个实例、80 个任务族，240 dev / 60 holdout 按族分离。数据来源、生成器和局限见[数据集卡](../../data/benchmarks/file-tools-v1/README.md)。多轮任务使用固定 follow-up，当前不声明具备任意用户模拟或全部中间状态断言。

每次运行保存 `run.json`、`trials/`、`results.json` 和 Inspect 日志；报告命令另生成 `report.html`、`report.md`。运行身份绑定固定任务、评分和源码；恢复执行必须保持身份一致。报告与 Langfuse 读取保存的正式分数，不能隐式重跑或重评。

```bash
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli export-langfuse \
  --run artifacts/nanobot-pilot
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli verify-langfuse \
  --run artifacts/nanobot-pilot
```

外部模型与 Langfuse 操作均需显式运行上述命令并提供配置。测试与默认 Demo 保持离线。

## 兼容入口

`eval_framework.cli`、历史 Suite / Provider、mini_agent 示例及旧 Inspect Scorer 仍用于兼容和回归；主基准入口为 `eval_framework.benchmark.cli`。旧结果不得改标为 DeepEval 结果，也不与新基准进行直接分数对比。

原有包内技术设计、指标字典、Inspect 迁移、状态型礼物示例和 SDK 文档保留为历史实现说明。它们描述的“Inspect 正式评分”“第二阶段默认入口”不适用于新基准。保留边界与原文索引见[兼容说明](../../docs/benchmark/legacy.md)。

## 验证

```bash
.venvs/evaluator/bin/python -m pytest -q -c packages/evaluator/pyproject.toml \
  packages/evaluator/tests/benchmark
```

完整历史回归使用仓库根目录的 `python3 scripts/test_all.py`。模型或 Judge 的付费 smoke 仅在显式启用后运行。
