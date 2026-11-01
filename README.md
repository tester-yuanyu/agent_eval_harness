# Agent Eval Suite

用于工具型 Agent 的 **固定任务数据集 + Harness**。当前主基准以 nanobot 为被测 Agent，在独立文件工作区完成读取、编辑、多步骤与多轮任务；**Inspect 负责执行调度和原生日志，DeepEval 是新基准唯一正式评分后端**，Langfuse 展示已保存的轨迹、评分与实验结果。

[作品集与真实实验结果](docs/benchmark/portfolio.md) · [数据集卡](data/benchmarks/file-tools-v1/README.md) · [旧项目兼容范围](docs/benchmark/legacy.md)

已完成 300 个任务 × 3 次重复 × 2 组配置，共 **1,800 次真实 nanobot 执行**。基线 91.11%，工具说明候选 88.78%；保留真实回退结果、失败归因及[数据集勘误](docs/benchmark/dataset-errata.md)，不将离线 Demo 当成模型成绩。

## 一条命令跑通离线 Demo

需要 Python 3.11+。首次安装需要访问 Python 包源；当前约束在 macOS / Python 3.11 解析。进入本地仓库后执行：

```bash
python3.11 scripts/setup.py --only evaluator
make demo
```

`make demo` 执行 5 条离线参考任务，并生成 `artifacts/benchmark-demo/report.html`、`report.md`、`results.json` 与 Inspect 日志。它不调用模型或 Langfuse，**只能验证评测闭环，不能作为真实 Agent 成绩**。同一目录与身份相同的重复运行复用已保存结果；需要新运行时指定 `BENCHMARK_OUTPUT=artifacts/my-demo`。

没有可用 Make 时，等价命令为：

```bash
.venvs/evaluator/bin/python -m agent_eval_suite.cli benchmark demo \
  --limit 5 --split dev --output artifacts/benchmark-demo
.venvs/evaluator/bin/python -m agent_eval_suite.cli benchmark report \
  --run artifacts/benchmark-demo
```

只需要核心 Harness、不安装内置 mini_agent 时，使用 `python3.11 scripts/setup.py --only core`，并在根 CLI 前加 `--evaluator-python .venvs/core/bin/python`。DeepEval 在两种环境中都是必需依赖。

## 数据集与评测边界

File Tools v1 包含 **300 个可执行实例、80 个任务族**，分为 **240 dev / 60 holdout**；同一任务族不会跨切分。参数变体不是 300 种独立能力，完整来源与限制见[数据集卡](data/benchmarks/file-tools-v1/README.md)。

| 类别 | 实例数 | 验证内容 |
| --- | ---: | --- |
| 读取与搜索 | 60 | 文件查找、字段提取、结构化数据统计 |
| 创建与编辑 | 100 | 文本、JSON、CSV 的确定性转换 |
| 多文件、多步骤 | 80 | 备份、合并、拆分、汇总与交叉更新 |
| 多轮任务 | 40 | 同一会话中的需求变更与结果修订 |
| 缺失资源与异常输入 | 20 | 缺失文件、无效数据、冲突与重复标识 |

每次 Trial 使用固定初始文件和独立工作区。Agent 仅接收任务输入，不接收 Oracle、预期文件或参考操作。终态证据来自工作区采集，不以工具自报“成功”代替文件验证。

DeepEval 自定义指标检查任务终态和工作区约束；工具正确性作为诊断，避免把合法的替代调用方式判错。缺失证据与环境异常分别保留 `INCONCLUSIVE`、`INVALID`。正式结果记录任务 Hash、评分版本、Harness 与运行时身份；同一固定任务集上重复执行后才能报告稳定性。实时实验是否完成、样本量、失败和限制以[作品集记录](docs/benchmark/portfolio.md)中的证据为准。

本集针对 UTF-8 文件工具，不覆盖 shell、浏览器、数据库或生产系统写入。当前多轮任务验证最终状态与轮次，不代表动态用户模拟或每一轮中间状态均已验收。

## 运行真实 nanobot

先准备兼容的 nanobot 源码与其独立 Python 环境，复制 [nanobot.example.json](configs/benchmark/nanobot.example.json) 为本地配置，填写源码路径、解释器、模型和服务地址。密钥通过配置中的 `api_key_env` 指定环境变量读取，不写进配置、报告或版本库。执行不会自动拉取最新 Agent 代码。

```bash
# 无模型调用：校验冻结 Hash、契约与全部参考任务
.venvs/evaluator/bin/python -m agent_eval_suite.cli benchmark validate

# 小批量真实模型调用；先检查配置、费用和真实轨迹
make benchmark-live BENCHMARK_CONFIG=configs/benchmark/nanobot.local.json \
  ARGS="--limit 20 --split dev --output artifacts/nanobot-pilot"

# 查看保存的结果，不重新调用 Agent 或计算分数
.venvs/evaluator/bin/python -m agent_eval_suite.cli benchmark report \
  --run artifacts/nanobot-pilot
```

`benchmark-live` 会真实调用配置中的模型。建议先跑 20 条，再扩大到 60 条与全量；`--repeats 3` 表示每条任务执行 3 次，因此 300 条任务对应 900 个 Trials。失败和未完成 Trials 不得从计划分母中悄悄移除。

比较两个完整运行时，固定数据集、评分规则、Harness、任务选择与重复次数，仅改变事先声明的实验变量：

```bash
.venvs/evaluator/bin/python -m agent_eval_suite.cli benchmark compare \
  --baseline artifacts/baseline --candidate artifacts/candidate \
  --output artifacts/comparison.json
```

当 Agent 工作区含未提交修改时，仅记录 Git commit 不足以复现。本地可使用 `scripts/package_nanobot_snapshot.py` 保存与运行中 `working_tree_sha256` 一致的运行源码、逐文件 Hash 清单和归档校验值：

```bash
.venvs/evaluator/bin/python scripts/package_nanobot_snapshot.py \
  --source /path/to/nanobot --output artifacts/benchmark/nanobot-source.tar.gz \
  --expected-hash <运行记录中的working_tree_sha256> --scan-only
# 检查仅输出文件名的扫描结果；移除 --scan-only 才会写入本地归档。
```

归档仅保存在被 Git 忽略的 `artifacts/`，不包含 Git 历史、dotenv、符号链接或非运行资产，不自动上传。它用于恢复本次实际源码；固定模型别名仍不能冻结服务商远端权重，因此源码可复现不等于模型输出逐字可复现。

## Langfuse 与作品集证据

配置自己的 Langfuse 环境变量后，显式导出并回读验证：

```bash
.venvs/evaluator/bin/python -m agent_eval_suite.cli benchmark export-langfuse \
  --run artifacts/nanobot-pilot
.venvs/evaluator/bin/python -m agent_eval_suite.cli benchmark verify-langfuse \
  --run artifacts/nanobot-pilot
```

导出使用保存的结果，不重跑 Agent、不在 Langfuse 重新判分。展示内容包括任务与 Trial 关联、模型请求/响应、工具参数/结果、可用的时长和用量、文件状态与 DeepEval 分数。未知费用保持未知；API 接收成功与回读验证是不同阶段。截图、链接和验收范围见[作品集记录](docs/benchmark/portfolio.md)。

## 仓库结构

```text
data/benchmarks/file-tools-v1/   固定任务、Manifest、生成器与数据集卡
packages/evaluator/src/eval_framework/benchmark/
                               Harness、nanobot 适配、DeepEval 指标、报告与导出
configs/benchmark/             显式运行配置示例
packages/contracts/            共用契约与能力快照校验
packages/dataset-builder/      候选生成、编译、审核与冻结工具
packages/agent-trace-sdk/       历史独立取证 SDK
examples/mini_agent/            可选参考 Agent 与历史回归
src/agent_eval_suite/           统一 CLI 与资产登记
scripts/                       安装与离线验证
environments/                  分环境第三方版本约束
docs/benchmark/                作品集及兼容边界说明
```

当前展示主线使用 `benchmark` 命令。原 `dataset`、`bundle`、`agent` 资产工具和 `eval` 兼容命令仍保留；**历史 `eval` 路径包含 Inspect 评分，不能与新基准 DeepEval 成绩混合**。已从主 Demo 与快速开始移除旧评分入口，保留原因和命令见[兼容说明](docs/benchmark/legacy.md)。

## 本地验证

```bash
.venvs/evaluator/bin/python -m pytest -q -c packages/evaluator/pyproject.toml \
  packages/evaluator/tests/benchmark
python3 scripts/test_all.py
python3 scripts/verify_assets.py
```

默认测试不调用真实模型或托管服务。Builder 的 OpenAI 约束与 Evaluator 不同，仍使用独立环境；`make setup` 安装两者。Evaluator 的旧 `--optional-metrics` 安装选项仅保留兼容，已与默认 DeepEval 约束合并，无须为了主基准再创建一套 optional 环境。
