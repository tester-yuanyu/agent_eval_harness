# Agent Eval Suite

面向工具型 Agent 的契约驱动评测工作台：从能力快照校验、评测集构建和人工审核，到 Inspect 执行、证据判定与报告输出。

本仓库整合原 `mini_agent`、`agent_dataset_builder` 和 `agent_evaluator` 的当前实现。生成与评测共享数据契约，保留独立的 Python 包和运行环境；参考 Agent 位于 `examples/`，外部 Agent 通过 Provider / RuntimeBinding 接入。

## 快速开始

需要 Python 3.11+、Git 和 Make。首次安装需要访问 Python 包源；离线 demo 不需要模型密钥或 Langfuse 服务。当前验证环境为 macOS / Python 3.11。

```bash
git clone <你的仓库地址> agent-eval-suite
cd agent-eval-suite
make setup PYTHON=python3.11
make demo
```

尚未发布到远端时，直接进入本地仓库执行后两条命令。

`make demo` 使用外部静态适配器，通过真实的 Inspect 编译、执行和评分流程，验证三个预设场景：`PASS`、`FAIL`、`INCONCLUSIVE`。输出路径打印在终端，包括 Markdown 报告、结构化结果和原生 `.eval` 日志，保存在 `artifacts/demo-*/`。

这是框架自检，结果不能作为 Agent 的业务成功率。正式评测需要冻结数据集和实际 Agent 配置；LLM 生成、Judge 与在线 Agent 调用均需显式配置。

## 仓库结构

```text
packages/
  contracts/          capability_snapshot_kit + eval_contracts
  dataset-builder/    生成、编译、校验、审核与冻结
  evaluator/          Inspect 执行、评分、比较与报告
  agent-trace-sdk/    Agent 轨迹接入 SDK
examples/mini_agent/  可选参考 Agent
src/agent_eval_suite/ 统一 CLI 与资产登记
data/bundles/        按 Agent / 发布版本保存的快照
data/bundle-index.json
configs/            外部 Agent 配置示例
scripts/            安装、离线 demo、测试与资产完整性校验
environments/       分环境依赖约束
docs/               架构、使用说明与迁移证据
```

Builder 的能力 IR 保持内部所有权。共享包只承载能力协议、评测数据模型和公共校验，不引入执行引擎。Evaluator 继续使用 `eval_framework` 命名空间，并将 Inspect 0.3.280 作为执行引擎。

Builder 与 Evaluator 当前的 OpenAI 版本约束不同，因此分别安装到 `.venvs/builder` 和 `.venvs/evaluator`。根 CLI 通过子进程转发命令，不把两套运行时装进同一环境。

## 常用命令

```bash
# 查看已登记的快照版本
make cli ARGS='bundle list'

# 解析并重新校验固定版本；返回相对路径和协议 Hash
make cli ARGS='bundle resolve --agent mini_agent --version 0.1.0'

# 准备内置 Suite 的生成请求（此步不调用模型）
make cli ARGS='dataset prepare --suite mini_agent_query_user_intent_v2 --workspace artifacts/query-user'

# 查看各阶段真实参数
make cli ARGS='dataset ingest --help'
make cli ARGS='eval run --help'

# 全量离线回归与历史资产校验
make test
python3 scripts/verify_assets.py
```

根 CLI 安装后也可使用 `.venvs/evaluator/bin/eval-suite`。支持 `dataset prepare/generate/ingest/validate/review/freeze`、`eval run/compare/gate/analyze`、`bundle publish/resolve/validate/diff/list` 和 `agent sync/resolve`；原模块的其他支持命令见 `--help`。

## 能力更新与评测比较

1. Agent 导出新的完整 v3 能力包，以 `agent.json` 为根入口。
2. 使用 `bundle publish --input DIR --agent NAME --version VERSION` 登记不可覆盖的新版本。版本索引位于能力包外，不向 v3 包内添加新的 JSON Manifest。
3. 新建或更新 Suite 时显式绑定 Bundle 路径及 Hash；旧 Suite 和冻结数据集保留原绑定。版本登记本身不会自动改写已有 Suite。
4. Builder 生成或导入候选，校验后产出审核材料；人工完成审核后才可冻结，不自动代填审核人。
5. 评测新旧 Agent 时，保持参考数据集和判分依据固定。新数据集需要让两个适用版本重新运行，不能直接把新旧数据集的分数相减。

`eval compare --baseline-run BASELINE_RUN_DIR --candidate CANDIDATE_RUN_DIR --output-dir DIR` 接收评测运行目录。`baseline` 不代表 Agent 版本。旧入口的 `--capability-bundle` 是参考包覆盖参数，仍要求匹配数据集 Hash；实际运行版本由 Provider 或可信 RuntimeBinding 配置选择。

外部源码更新只在显式 `agent sync` 时发生，返回完整 commit 和固定 checkout。执行评测不会自动拉取最新代码。

## 独立使用与验证

```bash
# 仅安装不含 mini_agent 的评测核心
make setup-core PYTHON=python3.11
.venvs/core/bin/python scripts/demo.py --output-dir artifacts/core-demo
```

`make setup` 默认不安装 DeepEval 等可选指标依赖。相关测试在缺少依赖时明确跳过，在线 smoke 测试默认关闭。可按需使用 `python3 scripts/setup.py --only builder --optional-metrics` 或 `python3 scripts/setup.py --only evaluator --optional-metrics`，它们使用各自独立解析的 `*-optional.txt` 约束。依赖约束升级应显式审查。

历史冻结数据和文档保留在各包内。当前入口以本 README 和以下文档为准：

- [架构与边界](docs/architecture.md)
- [生成、审核与冻结流程](docs/dataset-workflow.md)
- [外部 Agent 与版本配置](configs/README.md)
- [迁移来源](docs/migration/provenance.md)
- [验证记录](docs/migration/verification.md)

项目展示时，建议同时提供架构图、一条完整失败 Case 的证据链、固定数据集上的真实基线对比，以及对应 commit / 数据集 Hash。报告截图应标注样本量、运行模式和运行版本。
