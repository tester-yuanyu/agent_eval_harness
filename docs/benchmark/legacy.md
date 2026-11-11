# 新基准与历史兼容范围

自任务数据集 + Harness 改造起，仓库主入口是 `eval-suite benchmark` / `eval_framework.benchmark.cli`。它使用 DeepEval 作为正式评分后端，Inspect 负责执行与日志。**仓库仍存在用于历史兼容的 Inspect Scorer，不能表述为已从全仓删除 Inspect 评分代码。**

## 已整理的入口

| 原入口或组织方式 | 当前处理 | 原因 |
| --- | --- | --- |
| `make demo` → `scripts/demo.py` 的三个静态预设结果 | 主入口改为 5 条固定任务的离线 Harness Demo，并生成 HTML / Markdown 报告 | 克隆后首先看到任务、执行、评分和证据组成的闭环 |
| 老 Demo | 改为显式 `make legacy-demo`；原 Python 脚本保留 | 历史集成测试仍需要验证 PASS / FAIL / INCONCLUSIVE 语义 |
| `make eval-live` | 明确标记 legacy；新增 `make benchmark-live` | 避免将旧 Suite 评分与新基准混用 |
| DeepEval 仅在 evaluator-optional 安装 | 成为 Evaluator/Core 必需依赖；optional 约束文件引用同一份 evaluator 约束 | 消除评分后端的重复依赖约束与漂移 |
| README 中以 Inspect 迁移阶段为主的叙事 | 主 README 改为固定任务集、Harness、DeepEval 与证据交付 | 新访客可以直接进入当前项目主线 |

本轮没有删除历史不可变数据或改写历史报告，没有把新结果伪装成旧指标延续。Builder 的 optional 依赖与旧 Evaluator 安装选项仍可兼容已有脚本；主基准无需额外 optional 环境。

## 暂时保留的模块

| 模块 | 用途与边界 |
| --- | --- |
| `packages/dataset-builder` | 能力快照驱动的候选生成、编译、Gate、审核和冻结工具。固定 benchmark 运行不依赖每次重新生成候选。 |
| `packages/contracts` 与根 CLI 的 `bundle` / `agent` | 能力协议、固定版本登记、显式源码同步和历史契约校验。运行不会自动拉取“最新”代码。 |
| `eval_framework.cli`、Suite 编译器、旧 Provider / Scorer | 读取旧 Suite、验证旧指标、回归历史数据；保留 Inspect 评分语义，独立于新 benchmark。 |
| `examples/mini_agent` | 可选参考 Agent 和原项目回归。Core 安装不依赖它，当前主作品集使用 nanobot。 |
| `packages/agent-trace-sdk` | 基于 Inspect 的独立业务证据适配 SDK；当前 Provider 仍使用，历史格式仅只读兼容。 |
| 包内兼容使用文档 | 保留协议、接入方法、历史限制与旧结果口径；已完成方案和重复阶段报告由 Git 历史保留。旧阶段的“默认评分后端”不覆盖新主入口。 |

这些模块有现有使用者、测试或冻结资产依赖；删除会改变已交付行为。下一步若正式废弃，需先迁移调用者和测试、标明结果格式支持期限，再删除实现。当前的整理是收敛对外主入口及重复约束，不能宣称所有历史冗余都已物理移除。

## 历史命令

以下命令只用于兼容任务，不是当前 nanobot benchmark：

```bash
make legacy-demo

.venvs/evaluator/bin/python -m agent_eval_suite.cli eval run --help
.venvs/evaluator/bin/python -m agent_eval_suite.cli dataset prepare --help
.venvs/evaluator/bin/python -m agent_eval_suite.cli bundle list

python3 scripts/verify_assets.py
python3 scripts/test_all.py
```

旧 `eval compare` 使用运行目录而不是 Agent 版本；跨新旧数据集、评分后端或指标版本的分数不能直接相减。新基准只通过 `benchmark compare` 比较同任务、同评分与同 Harness 的完整运行。

## 兼容文档索引

- [旧评测架构](../../packages/evaluator/docs/architecture.md)：契约驱动的 Suite / Provider 与旧路径边界。
- [旧 Inspect 执行与评分迁移](../../packages/evaluator/docs/inspect_engine.md)：旧引擎决策与范围。
- [旧指标字典](../../packages/evaluator/docs/metric_dictionary.md)：历史指标语义，不能作为新 benchmark 的版本声明。
- [旧报告规范](../../packages/evaluator/docs/evaluation_report_spec.md)：旧领域报告结构与判定规则。
- [旧独立证据通道](../../packages/evaluator/docs/TRACE_PHASE1.md)：SDK 接入与证据状态。
- [旧 Langfuse 接入](../../packages/evaluator/docs/langfuse.md)：原结果导出和人工复核流程。
- [monorepo 迁移来源与验收](../migration/provenance.md)：原三个项目的合并来源；保留原项目为只读参考。

当前实现和真实运行证据以[根 README](../../README.md)、[v2 数据集卡](../../data/benchmarks/file-tools-v2/README.md)和[v2 作品集](../../reports/file-tools-v2/index.html)为准；[v1 作品集](portfolio.md)保留历史实验口径。
