# Benchmark M1 最小闭环验收（2026-11-06）

状态：本轮最小闭环已完成实现、独立审查、联合回归、新克隆验收和本地整合；没有推送远端。本记录只对应本轮三个职责边界调整，不代表完整 Benchmark 路线图已交付。

## 范围与实现

基线 `c057ed2`；实现 `e973e3e`、`4b03032`、`c8b456a`，兼容修复 `2d61b24`。Environment 的 `a8cd2c3` 已合入本分支进行联合验证，未覆盖其文件所有权。

- runner 先由 domain 投影公开任务，再由包内 presentation 构造 Inspect Sample。FileToolsPresentation 保留原名称和文件装配；ProviderPresentation 被现有 mini-agent SQLite 领域使用。任务不再必须伪造顶层 prompt/fixtures，Sample target 为空、metadata 只含公开 case_id。presentation 配置、task name 和源码进入新运行身份，并在执行前后检查漂移。
- NanobotModuleAdapter、NanobotDecisionAdapter、NanobotAgentAdapter 分别注册为 nanobot_module、nanobot_decision、nanobot_agent；旧 nanobot provider 和 NanobotAdapter/NanobotRuntimeAdapter 兼容分派保留。执行语义、模型需求、worker 隔离和取消行为不变。
- 原生 worker Inspect bridge 的实现归 `integrations/nanobot/inspect_bridge.py`，`inspect_runtime._execute` 直接调用它；`harness.loop` 保留同模块兼容。没有把原生 Agent 改走组件 Harness。
- 正式确定性评分、回复诊断、轨迹 Judge、rubric、客户端和原生指标 worker 归 `benchmark/scorers/`。旧 metrics/judging/agentic_metrics 模块及 worker `-m` 入口保留，旧客户端替换仍有效；底层评分算法只保留一份。新文件纳入集中源码身份闭包。
- 既有独立参考执行仍位于 `scorers/reference_runner.py`；runner 的 offline 分支直接调用，oracle.py 保留兼容转发。离线演示不能计入 Agent 成绩。

本轮初始实现差异涉及 27 个文件（包括三个测试文件和计划），主要是搬迁与兼容门面；本记录及路线图修订另计。冻结任务、manifest、历史结果、评分版本、rubric 内容与四层分母口径不改写。

## 验证记录

| 项目 | 结果 |
| --- | --- |
| 公开 Sample / SQLite 领域定向回归 | 35 passed / 1 optional skip |
| 模式、身份、取消与 bridge 定向回归 | 40 passed |
| scorer 定向回归 | 57 passed；审查兼容修复后相关 35 passed |
| 迁移前后固定证据比较 | 四组正式评分对象逐字段一致，rubric SHA-256 不变 |
| 最终完整 Evaluator 回归 | **1,316 passed / 14 skipped**，263.09 秒 |
| Evaluator Ruff / Git diff 空白检查 | 通过 |
| 冻结资产校验 | 1,172 项通过 |
| worktree 根 CLI / contracts | 58 passed / 3 skipped；缺少 worktree 的 Builder 独立环境 |
| 集成后根 CLI / contracts | **61 passed**，25.60 秒 |
| 新克隆独立 core 安装 | 安装及 pip check 通过；minimal_agent、nanobot、Langfuse 均未安装，核心导入成功 |
| 新克隆最终定向回归与演示 | 163 passed / 1 skipped（未安装 minimal_agent）；根 CLI/contracts 58 passed / 3 skipped；五条 reference demo、Inspect 报告、原生 Harness demo、ExternalProvider PASS/FAIL/INCONCLUSIVE 及冻结资产校验通过 |
| 独立只读代码审查 | 0 Critical、1 Important 已修复、0 Minor；scorer/bridge 函数体 AST 对照保持原语义 |

完整回归首轮为 1,314 passed / 14 skipped / 1 failed，失败原因是既有取消测试的嵌套进程没有在两秒预算内启动。其整个文件定向重跑 12 项通过；未修改超时阈值或放宽测试，最终整套结果另记。评分拆文件时漏带诊断辅助函数的问题由现有错误路径测试发现并修复；审查发现的旧 `metrics.OpenAICompatibleJudge` 替换失效问题由新增回归先红后绿验证。

本批工作区日志和实施 ledger 已归档至 `.migration/benchmark-m1-worktree-logs/`，临时计划工作区已清理；根集成测试日志为 `.migration/benchmark-m1-root-tests.log`。独立克隆为 `.migration/benchmark-m1-clean-20261106/`，使用自己的 `.venvs/core`；安装日志 `.migration/benchmark-m1-install.log`，验收日志 `.migration/benchmark-m1-clean-acceptance.log`，演示产物位于克隆内 `artifacts/benchmark-m1-final/`。

## 实施裁决和边界

1. presentation/SampleSpec 保持 Evaluator 包内，基于 file-tools 与既有 SQLite 两个真实接入点提炼；暂不发布共享 contracts，未来跨包使用时需另行稳定协议。
2. 原生 Inspect bridge 移位但保留兼容模块和取消逻辑；不统一替换 Agent 循环，因此原生与组件 Harness 两条路径继续分别验证。
3. 全量 tau/mini/core 搬迁及统一 loader/descriptor 留在后续批次，不把这个最小闭环称为整个 M1 完成。
4. scorer 共用诊断结构抽成小函数，避免循环导入；该结构仍保持原错误记录字段。
5. 不承诺保留 metrics.GEval 等第三方偶然导入名；旧正式评分、公开客户端和回复诊断入口兼容，依赖偶然导入名的调用方应直接从 DeepEval 导入。
6. Environment 基线由其独立任务负责，本轮验证整合边界；审查者不重复协调者的完整测试与安装验收，真实模型/人工/托管交付仍 pending。

没有 deferred minor。真实 Docker、可选 τ 运行和付费模型不以离线测试冒充；缺失 SDK 的跳过项按实际结果披露。没有调用真实模型、上传托管服务、填写人工标签或改变冻结资产。

后续 M2 按用户评审排序：最小来源链/计划总体校验 → 失败归因与本地报告 → pass^k/成本及注释分桶。探索性比较允许无 ExperimentSpec，受控实验仍要求预先声明；费用/token 覆盖率分别显示完整字段的计划 trial 和全部 trial 已覆盖任务数。M3 按所需接口分批，M4 无人力/预算/独立授权时明确 pending。
