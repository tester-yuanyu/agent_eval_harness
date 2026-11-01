# 文档导航

从[根 README](../README.md)开始安装和运行。当前主线是固定任务数据集与 Harness：Inspect 负责执行与日志，DeepEval 负责正式评分，GEval 提供尚未完成人工校准的诊断，Langfuse 展示已保存证据。

| 要做的事 | 阅读入口 |
| --- | --- |
| 查看框架分工、原生能力与必要自研边界 | [框架复用说明](benchmark/framework-reuse.md) |
| 核对框架复用的回归、Docker 与全新安装验收 | [框架复用验收](migration/framework-reuse-acceptance-2026-11-02.md) |
| 运行模块、模型决策、关键链路或端到端评测 | [分层评测指南](benchmark/v2-usage.md) |
| 核对本轮结果与尚未完成的工作 | [七项问题清单](benchmark/status-v2.md) · [v2 作品集](../reports/file-tools-v2/index.html) |
| 查阅当前指标公式、分母与轨迹诊断 | [当前指标规格](benchmark/metric-specification.md) · [质量检查报告](../reports/evaluation-quality-v1/README.md) |
| 独立人工标注与 Judge 校准 | [标注指南](benchmark/judge-annotation-guide.md) · [36 条离线盲标页](../reports/evaluation-quality-v1/annotation.html) |
| 核对质量补齐的回归与安装验收 | [验收记录](migration/evaluation-quality-acceptance-2026-11-01.md) |
| 理解一次真实失败及正式判定 | [失败案例](benchmark/failure-case-v2.md) |
| 运行独立官方 τ 领域试点 | [τ 适配说明](benchmark/tau.md) |
| 了解包边界、参考身份与运行身份 | [仓库架构](architecture.md) · [显式配置](../configs/README.md) |
| 阅读中文任务、构建任务或使用通用 Builder | [逐条阅读页](dataset-reading.html) · [数据集工作流](dataset-workflow.md) · [语言与冻结边界](dataset-language.md) |
| 查阅历史实验 | [v1 作品集](benchmark/portfolio.md) · [失败分析](benchmark/failure-analysis.md) · [数据集勘误](benchmark/dataset-errata.md) · [Langfuse 证据](benchmark/langfuse.md) |
| 维护历史兼容入口与导入资产 | [兼容范围](benchmark/legacy.md) · [迁移来源与验收](migration/provenance.md) |

当前数据集为 [File Tools v2](../data/benchmarks/file-tools-v2/README.md) 和 [Model Decisions v1](../data/benchmarks/model-decisions-v1/README.md)。中文逐条阅读页跨三个版本收录 744 条记录，包含 v1/v2 继承任务，不代表 744 个唯一任务。历史 [File Tools v1](../data/benchmarks/file-tools-v1/README.md)、Suite / Provider、mini_agent 与 Inspect Scorer 保留各自原有语义；[v1 架构](benchmark/architecture.md)不能作为 v2 能力清单。不同任务、运行方式或评分版本的结果分开报告。

说明文档使用中文，保留专业术语、命令、字段名和代码标识符。冻结任务、能力协议资源、第三方官方任务、原始模型或工具输出、审核证据及历史结果按原文保存；英语原文不因文档整理而改写。若要翻译影响执行或评分的内容，必须创建新版本并重新验证，不能覆盖旧数据及 Hash。完成的实施方案和重复阶段报告已收敛，详细演变可查 Git 历史。
