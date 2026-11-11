# Builder P0 发布就绪验证实施计划

> 使用 executing-plans 在当前会话实施，按 test-driven-development 验证关键行为。

**Goal:** 为固定的 read_file 案例集合打通 Builder 静态校验、原生 Harness reference 执行、证据失效与显式冻结。

**Architecture:** contracts 定义版本化制作协议；Builder 负责准备、门槛与冻结；Evaluator 使用原生 Inspect Harness 和无模型调用的参考执行器；根 CLI 仅以独立解释器编排。首版为工具级验证，不宣称 MiniAgent 或链路通过。

**Tech Stack:** Python、Pydantic、现有 Inspect Harness、pytest，无新增依赖。

**Spec:** 本聊天已批准的 P0 最小切片：固定集合、真实 Harness 绑定、独立断言、绑定内容 Hash、人工审核后显式冻结。

## 全局约束

- 保留旧 valid 语义、v3 agent.json、历史 Hash 和冻结数据字节。
- 不调用付费模型，不上传；Oracle 不进入参考执行器消息。
- 当前 checkout 有用户未提交改动，复用该 checkout，不暂存或提交他人文件。
- 首版支持 read_file 单调用、独立 fixture、精确输出及文件不变断言；其他工具明确拒绝。
- P1/P2 不在本次范围；不建立新的通用语义编译器。

## Review Focus

- 空集合、重复 ID、未知工具和路径越界必须拒绝。
- 进程成功但断言失败不能通过。
- 案例删除、fixture/断言/runner 变化使证据失效。
- 缺失或重复证据不能抬高指标；人工审核必须绑定当前请求与证据。
- 原有接口、离线运行与 Builder 环境独立性保持。

## Task 1：共享协议与 Builder 门槛

Files: contracts/src/eval_contracts/readiness.py；dataset-builder/src/dataset_builder/readiness.py；对应 tests。
Interfaces: ReadinessDataset / RunnerIdentity / ReadinessEvidence；prepare、assess、freeze_release。
- [x] 写失败测试：固定集合、断言失败、证据失效、审核绑定、禁止覆盖。
- [x] 实现严格协议、文件 Hash 及门槛；测试转绿。

## Task 2：原生 Harness reference 执行

Files: evaluator/src/eval_framework/benchmark/readiness.py；tests/benchmark/test_readiness.py。
Interfaces: identity()；run(dataset, log_dir) 返回 ReadinessEvidence。
- [x] 写失败测试：真实 read_file、错误预期失败、无 oracle 泄漏。
- [x] 使用 execute_native_task 与自定义确定性 BaseAgent；保留 Inspect 日志，生成证据。
- [x] 验证空证据、运行故障及源码/版本身份变化。

## Task 3：CLI、文档与验收

Files: 根 CLI、Builder CLI、examples/readiness/read_file.json、中文说明。
- [x] 接入根 CLI 子进程编排和 Builder 显式审核冻结入口。
- [x] 执行相关测试、包回归及全新克隆安装/离线演示；记录结果。

## 执行记录

- 2026-11-11：用户已授权按方案实施；采用本会话直接开发以控制成本。先实现文件工具切片，MiniAgent 适配另行推进。

- 独立审查发现 Builder/Evaluator 双环境断言版本可能不一致；新增 assertions_sha256 双向校验及回归测试，已通过。
- Ruling：首版新制作协议只支持 read_file，不强行映射历史 capability_contract_case；避免将旧 847 项误报为已验证。
- Ruling：原生 timeline 要求 ModelEvent，reference 通过进程内 mockllm 记录确定性动作；最终回复来自 tool message，不读取 oracle。

### 已完成的验证

- Builder 包回归（包目录执行）：369 passed / 5 skipped；随后新增的审核 CLI 退出码用例随 P0 专项共 17 项通过。
- 根 CLI 与 contracts 回归：82 passed；根 CLI 专项在去除环境安装依赖后再次 2 passed。
- 初次从仓库根运行包回归暴露相对路径/同名 tests 包问题，改用各包文档指定工作目录复验；未改测试数据。
- P0 worker 专项：3 passed；检查了完整原生证据、工具失败与私有 Oracle 不进入日志。
- Ruff 与 git diff --check 通过。
- 全新 Git 克隆后叠加当前工作树源码快照（包含本任务前已有未提交改动），新建 builder/core 两个独立环境，安装及 pip check 通过。core 未安装 minimal_agent。
- 新环境正向演示：2/2 read_file 案例，binding=1.0、reference=1.0、approval=PENDING。
- 新环境反向演示：故意改错一个 expected_output，静态有效且 binding=1.0，reference=0.5，根 CLI 返回 1。
- 仅自动测试 fixture 的审核冻结成功；再次冻结到同目录被拒绝。没有批准或冻结用户正式数据集，也没有上传服务。

- Evaluator 包回归（包目录执行）：1527 passed / 9 skipped / 160 warnings，435.79 秒；跳过为显式付费模型、Docker 和未安装 Nanobot 的可选测试。
- 当前改动留在工作区，未暂存、提交或合并；用户已有未提交修改保持原样。
