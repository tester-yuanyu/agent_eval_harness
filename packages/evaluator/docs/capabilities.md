# Evaluator 能力清单与边界

2026-10-28 更新：Inspect 负责正式调度、判分和聚合；Evaluator 保留业务扩展；Langfuse 接管展示和人工标注。旧 DeepEval G-Eval 路径及依赖已删除；现已选定 5 个 DeepEval 专项指标待接入 Inspect Scorer，尚未成为运行能力。最新单一职责、权威数据与验收限制见 [接入说明](langfuse.md)。

本文帮助使用者判断当前 Evaluator 能否满足自己的评测需求。核对日期：2026-10-13；依据为当前工作区代码、接口及测试，包含尚未提交的实现，不等同于某个已发布版本的承诺。

总技术方案负责三个项目的职责划分；本文聚焦 Evaluator 当前可用能力。内部结构见[架构与运行流程](architecture.md)，接入要求见[契约与接入规范](integration_contracts.md)，验证方法见[能力验收与示例](acceptance_examples.md)。

各项断言、语义评分、运行指标及 Gate 的唯一选型、证据要求和实际口径见[评测指标字典](metric_dictionary.md)，其中区分“Inspect 原生／DeepEval 复用／业务自研／暂不适用”。RAG、记忆、规划等候选维度尚未实现，不计入当前可用能力；接入批次和验收条件见该字典第 8 节。

## 1. 项目定位

Evaluator 接收已有评测集及冻结能力契约，调用 Agent，采集实际行为与状态证据，执行确定性断言和可选语义评分，输出可追溯的结果，再支持基线比较和本地发布门禁。

Evaluator 不负责生成或改写正式 Benchmark，也不替 Agent 实现业务能力。用例中的预期答案由 Oracle 提供，只用于评分；运行时接收执行输入。遇到 Agent 不具备的确认接受、上下文记忆等能力，评测器记录和暴露结果，不补造成功行为。

## 2. 能力矩阵

“已实现”表示当前有实现和对应验证入口，不代表适用于任意 Agent 或环境；“有限支持”表示必须满足表中边界；“规划中”不应作为当前接入承诺。

| 能力 | 状态 | 当前行为与边界 | 实现或验证入口 |
| --- | --- | --- | --- |
| Inspect 默认引擎 | 已实现 | 实际 Solver 调度、原生 Scorer 与 epochs 重跑；本地 .eval 日志 | [引擎](../src/eval_framework/inspect_engine.py)、[测试](../tests/test_inspect_engine.py) |
| Suite 声明与编译 | 已实现 | 指定 Loader、Provider、数据源、契约和运行参数；执行前校验版本、配置、路径和 Hash，保存编译指纹 | [编译器](../src/eval_framework/contracts/compiler.py)、[测试](../tests/test_suite_compiler.py) |
| 数据格式接入 | 已实现 | 内置冻结 JSONL Loader 和用于自测的 JSON 文档 Loader，统一输出 DatasetBundle | [Loader](../src/eval_framework/plugins/builtin/dataset_loaders.py)、[测试](../tests/test_dataset_loader_plugins.py) |
| Agent 接入 | 有限支持 | 提供通用 Provider 协议；当前内置业务接入为 mini_agent，新 Agent 需要实现并显式注册 Provider | [协议](../src/eval_framework/provider.py)、[架构测试](../tests/test_provider_architecture.py) |
| 模块评测 | 已实现 | mini_agent 调用一次纯意图入口，检查输出结构、意图、参数、状态等 | [断言测试](../tests/test_intent_assertions.py) |
| 链路评测 | 已实现 | mini_agent 调用一次 Agent.run，可包含有步数上限的工具循环；不消费后续用户输入 | [执行测试](../tests/test_execution_scoring.py) |
| 多轮端到端评测 | 有限支持 | 在 NEED_CLARIFICATION 或 NEED_CONFIRMATION 后消费预先声明的 user_responses；终态或输入耗尽即停止 | [多轮测试](../tests/test_multiturn_execution.py) |
| 工具与逐轮行为核验 | 已实现 | 检查调用、禁用调用、次数、入参、顺序及逐轮状态；完整性不足时不把未知当通过 | [逐轮断言](../src/eval_framework/turn_assertions.py) |
| 系统状态核验 | 有限支持 | Provider 提供执行前、逐轮及结束状态；gift_sqlite_v1 使用真实本地 SQLite 查询，不从成功文案推断写入 | [状态环境](../src/eval_framework/providers/mini_agent/state_environment.py)、[测试](../tests/test_stateful_environment.py) |
| Trial 隔离与清理 | 有限支持 | 每个 Trial 创建运行时与会话；外部资源隔离、初始化失败回收和清理核验由 Provider 实现 | [Runner](../src/eval_framework/runner.py)、[证据边界测试](../tests/test_evidence_boundaries.py) |
| 独立证据采集 | 已实现 | 本地 SDK 持续写入事件，记录采集状态和 Trial 关联；独立通道启用后不回退旧内嵌事件 | [证据规范](TRACE_PHASE1.md)、[测试](../tests/test_independent_evidence.py) |
| 确定性评分 | 已实现 | 按适用断言权重评分，关键项失败不可被其他高分抵消；无适用项不产生虚假满分 | [评分](../src/eval_framework/scoring.py)、[测试](../tests/test_execution_scoring.py) |
| Inspect 原生语义 Judge | 有限支持 | Inspect Model Grading 加独立 Judge 模型，独立配置和凭据；不能覆盖确定性关键失败；当前保留兼容入口 | [适配器](../src/eval_framework/judges/inspect.py)、[测试](../tests/test_inspect_judge.py) |
| 重复试验与稳定性 | 已实现 | 支持每 Case 多 Trial，生成 pass@k、pass^k、波动及耗时统计；单 Trial 不足以证明稳定性 | [稳定性测试](../tests/test_multi_trial_stability.py) |
| Trace 分析 | 已实现 | 规范化时间线与规则观察；观察到的偏差不自动等同于根因 | [分析测试](../tests/test_trace_analysis.py) |
| 报告与重新分析 | 已实现 | Markdown 面向人，JSON/JSONL 面向程序；派生分析保留原始 results.json | [报告规范](evaluation_report_spec.md)、[测试](../tests/test_reporting_cli.py) |
| 基线比较 | 已实现 | 先校验数据、配置及相关指纹的可比性；不把不同评测条件下的分数直接当回归 | [比较测试](../tests/test_comparison.py) |
| 本地发布门禁 | 已实现 | 版本化策略检查通过率、回归、稳定性、证据等；可产生 PASS、FAIL、REVIEW_REQUIRED 或无效结果 | [策略示例](../policies/release_gate.example.json)、[测试](../tests/test_gating.py) |
| 人工复核 | 离线接入已验收，Cloud 待验收 | Langfuse 是唯一编辑入口；本地导入来源、修订、归因、结果 Hash，不覆盖自动结果或门禁 | [复核测试](../tests/test_langfuse_reviews.py) |
| 超时控制 | 有限支持 | 当前 mini_agent 同步调用返回后识别超时；不提供抢占式强制取消 | [运行说明](../README.md#当前超时机制的限制) |
| 全流程 Profile / Pipeline 插件化 | 规划中 | Loader/Provider 基础已落地；Judge、Trace、Assertion、Report 和 Gate 尚未完成统一声明式扩展 | [阶段报告](../PHASE_END_REPORT.md) |

## 3. 使用前必须理解的边界

### 框架支持不等于 Agent 支持

框架能够编排多轮输入并检查最终状态，不代表当前 Agent 已实现会话记忆或确认接受。状态型礼物示例中，发放和修改后发放预期为 FAIL，原因是原生 Agent 仍停留在确认阶段；取消和链路观察案例可以 PASS。这些失败是有效的观测结果，不是示例运行失败。

### 执行完成不等于质量通过

业务返回、评测有效性、断言结论和发布决策分别记录。Agent 可以完成调用但违反预期；也可以有可见输出但缺少可信证据，导致评测无效。必需证据缺失不能被忽略后算出 PASS，已经独立证实的违规仍保留 FAIL。

### 冻结提高可追溯性，不消除模型随机性

固定数据、能力契约、插件和评分配置可以明确比较条件，不能保证真实模型每次输出一致。评估波动需要重复 Trial；脚本化模型自测只能证明框架处理给定行为的能力。

### 声明能力不等于提供运行环境

Capability Bundle 描述能力，Provider 负责实际工具、状态和资源。当前默认 mini_agent 环境不会自动提供 Mock 工具、共享数据库隔离或故障注入。gift_sqlite_v1 是显式选择的有限环境，不是任意工具沙箱。

## 4. 当前不提供的能力

- 自动生成、改写或自动接受正式回归用例；失败案例经人工复核后交给 Builder 冻结。
- 从约束文档加载任意 Python、Shell 或自动发现插件；实现必须可信且显式注册。
- 在任意工具循环位置截断执行，或为同步 Agent 强制取消调用。
- 内置通用远程测试环境、分布式调度、托管服务、HTML Dashboard 或 CI 工作流。
- 自动确认根因，或用人工复核、Judge 高分覆盖原始确定性关键失败。

## 5. 维护方式

增加能力时同步更新状态、前置条件、实现入口和验收证据。仅有设计或配置字段不标记为“已实现”；只有通过对应执行路径并有可检查产物，才升级状态。发布版本需要额外记录提交号及依赖版本，本文日期不替代发布标识。
