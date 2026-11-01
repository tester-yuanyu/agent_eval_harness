# 评测框架复用实施计划

> 执行：superpowers:subagent-driven-development；用户已授权持续执行。各任务有明确文件所有权，协调者集成与提交。

**Goal:** 用 Inspect/DeepEval/Langfuse 的公开能力替换重复基础设施，保留业务真值与历史证据。

**Architecture:** Inspect sample sandbox + bridge + epochs/eval_set 为执行核心；DeepEval 标准指标/GEval 为评分核心；Inspect View/Langfuse 为展示核心。独立 nanobot 不导入 Evaluator 进程。

**Tech Stack:** Python 3.11、inspect_ai 0.3.280、deepeval 4.2.9、langfuse 5.0.2、Docker。

**Spec:** ../specs/2026-11-01-framework-reuse-design.md

## Global Constraints

仅公开 API；冻结数据/历史结果不变；Oracle 不进 Agent/Judge；无付费模型/托管写入测试；新身份防止静默混用。保留四层执行与缺失值语义。子代理只改所属文件，不暂存、不提交。

## Review Focus

- 外部 Agent 实际受到预算和工具限制，而非只限制外层 solver。
- 恢复/epochs 不重复已完成样本，配置或源码改变拒绝恢复。
- 初始文件为精确字节，不因 Sample.files 路径探测改变内容。
- 原生 trace 指标只回放保存证据，局部评审不见未来或私有真值。
- 离线路径不受本机隐式凭据影响，不自动上传或触发真实模型。

## Task 1: Inspect 执行与轨迹（P0）

**Files:** benchmark/runner.py、nanobot_runtime.py、nanobot_worker.py、module_runtime.py、module_worker.py、decision_runtime.py、decision_worker.py；新增 inspect_runtime/沙箱构建/证据映射模块；对应 runtime/runner/integration 测试。

**Interfaces:** 保留 run_benchmark(tasks, dataset=..., config=..., output=..., repeats=..., concurrency=..., offline=...) -> dict 与 execute_task(task, config=..., workspace=...) 外部兼容；输出保留 results.json/trials，新增原生 Inspect 身份与事件来源。config 中新沙箱选项由实现者明确后通知协调者。

- [x] 先写行为测试：fixture 同字节、epoch隔离、模块不调用模型、decision不执行工具、拒绝身份变更恢复、原生模型事件与预算、文件快照缺失。
- [x] 用 Sample.files、sandbox().exec/read/write、sandbox_agent_bridge 取代通用工作区/进程控制/模型日志。删除对应旧实现；保留原生Agent接入和独立取证。
- [x] 用 Task.epochs / eval_set 接管重复与恢复，业务身份先于框架恢复校验；指标显示写入 Inspect Score，原始证据可回溯。
- [x] Docker 构建只包含受身份约束的运行代码与依赖声明；支持受控离线模型的真实 bridge 验收。
- [x] 运行定向测试；报告兼容性变化与证据。协调者审查后提交。

## Task 2: DeepEval 评分与重复诊断（P1）

**Files:** judging.py、新 agentic_metrics.py（若需要）、metrics.py 的重复诊断默认角色、对应 judging/agentic_metrics/metrics 测试。judge_run.py 的接口变更先通知协调者。

**Interfaces:** 保留 score_trajectory_judge 类现有调用；新增 dimension/implementation 列表与版本记录，输出遵守 status/score/formal/event_id/evidence_ids。使用公开 DeepEval API，不能直接设置 _trace_dict。

- [x] 测试真实 DeepEval 指标 + 本地 fake Judge：普通工具动作、正常重试、状态变化、缺失证据、非法返回、请求预算、Oracle/未来信息隔离。
- [x] 用标准参数/完成度/效率指标与 GEval 覆盖 task、动作、turn、chain；对已有保存证据进行公开 tracing 回放，不执行 Agent。
- [x] 精确重复分类降为可选文件证据审计，默认效率评分归 DeepEval；硬 Oracle/checkpoint 保留。
- [x] 所有未校准语义分数为诊断；按真实 Judge 请求计预算，错误为空；升级评分身份。
- [x] 定向测试通过并报告。

## Task 3: 原生报告与实验接入（P2，协调者）

**Files:** cli.py、report.py 或新增 native_reporting.py、judge_run.py 必要集成、配置示例、对应 CLI/report 测试。

**Interfaces:** report 默认为原生 Inspect bundle（有原生日志），历史纯结果路径保留 domain 报告兼容。compare 保留严格身份核对并提供 Inspect 原生对照视图；Langfuse使用原有官方SDK/OTel映射，不另造运输。

- [x] 测试生成可独立部署的原生 viewer、来源日志不变、历史结果兼容、对比身份不匹配拒绝。
- [x] 接入 bundle_log_dir/原生log API；提供清晰 CLI view/report/compare 入口与本地输出。
- [x] 更新配置、说明与所有权表，区分原生能力、业务扩展及历史兼容。

## Task 4: 集成、审查与回归（P0）

- [x] 合并文件变更、审查原生API使用与用户要求覆盖；对发现问题先复现再修复。
- [x] 执行 Evaluator 全套、根 scripts/test_all.py、ruff、scripts/verify_assets.py。
- [x] 真实 nanobot 模块 + 受控 mock 模型的 Docker bridge 集成（无付费模型）；验证 epochs、恢复、轨迹和预算。
- [x] 提交后全新 clone（不共享环境），安装并执行 demo/原生报告；记录命令与数量到 docs/migration/。
- [x] 独立最终代码审查，修复后复跑必要检查；快进整合工作分支，报告完成内容与实际限制。

最终代码 `0416ec8`；验收与剩余边界见 [框架复用验收记录](../../migration/framework-reuse-acceptance-2026-11-02.md)。
