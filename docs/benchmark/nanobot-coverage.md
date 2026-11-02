# nanobot 核心组件与能力覆盖

本入口补充 Session、Memory、Context、Skills 的离线真实组件实验，保留已有 File Tools 和 Model Decisions 的独立口径。源码存在、当前 profile 启用、数据集定义、实际执行、评分通过、人工审核是六种不同状态；矩阵不计算“nanobot 整体覆盖率”。

固定配置只允许 `nanobot_root` 与 `python`，格式见 [示例配置](../../examples/nanobot-core.example.json)。配置中的路径只用于本机启动；不要在公开报告复制本机配置、凭据、原始上下文或用户数据。被测 nanobot 源码只读；worker 不构造模型 Provider、不上传，不使用用户全局 nanobot 配置。

## 数据和范围

[nanobot-core-v1](../../data/benchmarks/nanobot-core-v1/README.md) 包含 32 条冻结任务：8 个 dev 家族各 3 条，4 个 reserved holdout 家族各 2 条。`core-run` 只执行 dev；holdout 本轮只验证合同、家族隔离与 Hash，不宣称已完成独立未见验收。任务与 Oracle 的独立人工审核仍待完成，不生成或代填人工标签。

Memory 检查历史游标、损坏输入恢复和未处理历史保留；Session 检查持久化、键隔离与合法重放；Context 检查记忆可见性及消息拼装；Skills 检查来源优先级、禁用、显式调用与缺失依赖。Session 重载指新建 manager 对象后读取磁盘，不代表进程重启或断电恢复。网络/文件审计护栏适用于固定可信模块，不是 OS 级恶意代码沙箱。

## 校验与执行

以下命令在仓库根目录执行；`.venvs/evaluator` 应先按仓库锁安装。将示例配置复制为本机文件并填入现有源码与解释器路径。`--output` 必须使用新目录，失败/无效证据不能被覆盖。

```sh
DEEPEVAL_TELEMETRY_OPT_OUT=YES .venvs/evaluator/bin/python -m eval_framework.benchmark.cli core-validate \
  --dataset data/benchmarks/nanobot-core-v1

DEEPEVAL_TELEMETRY_OPT_OUT=YES .venvs/evaluator/bin/python -m eval_framework.benchmark.cli core-run \
  --dataset data/benchmarks/nanobot-core-v1 \
  --config artifacts/nanobot-coverage/local-config.json \
  --repeats 3 --concurrency 4 \
  --output artifacts/nanobot-coverage/dev72
```

`dev72` 是本次规划目录名，不是已完成数量。实际计划/观察/有效 trial、缺失与四种判定均由保存记录计算。Inspect 负责 Sample/Epochs、隔离目录、限时和原生日志；DeepEval 确定性 Metric 在执行边界外读取私有 Oracle。返回进程成功不等于任务通过，缺少快照、事件、绑定身份或完整执行不得记为 PASS。

每次运行保存 `run.json`、`snapshot.json`、`results.json`、`trials/*.json` 与 Inspect 原生日志。源码实际字节、commit/dirty、解释器与依赖、适配器/评分代码、数据集和控制项共同构成身份。中途漂移应拒绝继续使用旧身份。

本次被测 nanobot 是 **dirty 工作树**，commit 不能单独重建这次实际源码。复核必须同时比对 snapshot 的逐文件 Hash 与 `working_tree_sha256`，不能只检出该 commit 就称为同一实现。公开产物保留 Hash 而不复制外部 nanobot 源码；没有对应源码字节时，不能宣称已完成跨机器源码重现。本轮组件证据也不构成完整产品验收。

## 构建覆盖矩阵

历史目录必须提供原始已评分结果，不能拿公开精简摘要替代 `results.json`。下例使用本项目已有四个历史运行；如果这些资产保存在其他位置，只替换相应路径。多个 `--file-dataset` / `--legacy-run` 的顺序应在矩阵与摘要命令中一致。

```sh
DEEPEVAL_TELEMETRY_OPT_OUT=YES .venvs/evaluator/bin/python -m eval_framework.benchmark.cli coverage \
  --config artifacts/nanobot-coverage/local-config.json \
  --core-dataset data/benchmarks/nanobot-core-v1 \
  --file-dataset data/benchmarks/file-tools-v2 \
  --file-dataset data/benchmarks/model-decisions-v1 \
  --run artifacts/nanobot-coverage/dev72 \
  --legacy-run artifacts/benchmark-v2/modules60-scored \
  --legacy-run artifacts/benchmark-v2/decisions24x3-scored \
  --legacy-run artifacts/benchmark-v2/chains60x3-scored \
  --legacy-run artifacts/benchmark-v2/e2e300-scored \
  --output artifacts/nanobot-coverage/matrix
```

历史运行的任务定义可关联到矩阵，但旧运行保留自己的运行时与评分身份，不能升级为当前 File Tools profile 的执行/通过证据。组件、模型决策、链路与端到端的分母不同；本轮组件 trials 和既有历史 trials 分开展示，不相加称为新的 Agent 成绩。

## 生成可复查的公开摘要

脚本只读取已有结果和冻结任务，不触发新评测、模型调用或上传。它重新验证全部输入的 Hash/身份、逐 trial 完整评分和原始 trial 文件，使用同一 catalog、数据集和历史来源重建覆盖矩阵并全量比较；任何不一致都拒绝输出。

```sh
DEEPEVAL_TELEMETRY_OPT_OUT=YES .venvs/evaluator/bin/python scripts/build_nanobot_coverage_report.py \
  --run artifacts/nanobot-coverage/dev72 \
  --coverage artifacts/nanobot-coverage/matrix \
  --dataset data/benchmarks/nanobot-core-v1 \
  --file-dataset data/benchmarks/file-tools-v2 \
  --file-dataset data/benchmarks/model-decisions-v1 \
  --legacy-run artifacts/benchmark-v2/modules60-scored \
  --legacy-run artifacts/benchmark-v2/decisions24x3-scored \
  --legacy-run artifacts/benchmark-v2/chains60x3-scored \
  --legacy-run artifacts/benchmark-v2/e2e300-scored \
  --output reports/nanobot-coverage-v1
```

`--run` 接受运行目录或 `results.json`，`--coverage` 接受矩阵目录或 `coverage.json`；两者旁边必须保留原始 `snapshot.json`，运行还须有 `run.json` 和 `trials/`。默认 catalog 为 `data/coverage/nanobot-v1/catalog.json`；使用自定义 catalog 时，矩阵与摘要都传相同 `--catalog`。摘要不会重新执行历史 Judge，历史只保留已保存判定和原始来源绑定。

公开输出为以下四个文件，不包含 observation、完整上下文提示、文件正文、Oracle 或绝对路径；遇到路径泄漏即拒绝发布，而不是静默涂改身份。

| 文件 | 可验证内容 |
|---|---|
| `README.md` | 实际分母、各组件判定、重复一致性、边界与争议 |
| `summary.json` | 每个 case/trial 的 verdict、validity、耗时、原始 row Hash、原始 trial 文件字节 Hash，以及历史来源单列 |
| `snapshot.json` | 源码逐文件 Hash、解释器/依赖指纹、有效 profile 与 Harness 身份 |
| `coverage.json` | 完整来源绑定矩阵、未覆盖项、holdout/人工审核状态 |

`raw_row_sha256` 使用 UTF-8 canonical JSON（`ensure_ascii=False`、排序键、无额外分隔空格、拒绝 NaN）计算整条原始结果，而 `raw_trial_file_sha256` 对原始 trial JSON 文件字节计算。`sources.results_raw_sha256` 对原始 `results.json` 字节计算；保留本机原始证据即可逐项复核。相同输入生成相同输出；已有同名文件若字节不同，脚本拒绝覆盖。

## 读数时保留的边界

通过率同时给出 PASS/计划 trial 和 PASS/有效 trial；INVALID、INCONCLUSIVE 和缺失不会混进 PASS。重复一致性按“重复记录齐全”“判定一致”“全部重复有效”“全部重复通过”区分。一致失败不等于通过，确定性组件的重复通过也不证明 LLM 稳定性。

`core-session_legal_replay-orphan` 已暴露 Oracle/需求语义争议：冻结期望保留孤立 tool 之前的 user 消息，当前合法后缀策略丢弃此前缀。原任务、Oracle 和失败记录均保留，不能为变绿修改冻结答案，也不能未经裁定就称为 nanobot 产品缺陷。正式报告的最终计数以实际运行产物计算，本指南不预写通过数量。

本轮没有人工标签或独立人工审核，不验证 Dream 摘要质量、模型是否正确使用记忆、全 Agent 成功率、并发/断电一致性或全面安全隔离。公开摘要不会自动新增 Langfuse 线上证据。
