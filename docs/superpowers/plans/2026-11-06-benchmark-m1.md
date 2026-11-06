# Benchmark M1 最小闭环实施计划

> 使用 superpowers:executing-plans 逐项执行。本批由用户最新评审限定为领域装配、nanobot 模式、scorer 搬迁；不实施 M2/M3/M4。

**Goal:** 保持旧执行/评分语义，消除核心编排的文件任务假设并落实适配与评分实现归属。
**Spec:** ../specs/2026-11-06-benchmark-complete-design.md
**Baseline:** c057ed2。Environment 在独立任务重构；其所有文件不编辑。

## Global Constraints

冻结数据/历史结果不改；无真实模型或托管调用；Oracle 不进入公开 Sample；原生 worker 与 loop 语义保留；只提交本任务文件。

## Review Focus

- 非文件 Provider 不需要 fixtures，Inspect Sample 输入只来自公开投影。
- presentation 源码及 task name/config 进入新运行身份，恢复不可混用。
- 旧 nanobot 别名、模式选择和 worker bridge 取消/清理行为不变。
- 迁移后的 scorer 不遗漏相对导入、worker 模块入口和源码闭包；旧 API 仍可用。
- 兼容 monkeypatch/import 只在旧模块门面解决，不保留两套评分算法。

### Task 1: 两个实际领域的 Sample 装配

Files: benchmark/domains/presentation.py、runner.py、run_context.py、mini_scoring.py；tests/benchmark/test_domain_presentation.py。

- [x] 先写不带 fixtures 的公开 Provider/SQLite 执行测试，验证正式评分、Inspect Sample 无私有内容；运行红灯。
- [x] 提炼包内 SampleSpec/DomainPresentation；保留默认 file-tools；MiniAgentDomain 选 ProviderPresentation；旧 custom domain 有兼容默认。run_benchmark 新增可选 presentation 参数，身份绑定实现源码与配置。
- [x] 跑新增测试、runner/provider_domain/mini_domain/mini_worker/原生 Harness 回归；提交。

### Task 2: nanobot 模式与原生 Inspect bridge

Files: integrations/nanobot/adapters.py、inspect_bridge.py；benchmark/adapters.py、inspect_runtime.py、composition.py；harness/loop.py 薄兼容；tests/benchmark/test_nanobot_mode_adapters.py。

- [x] 先写新 provider 注册、错误模式拒绝、模式分母/模型需求与桥兼容测试；运行红灯。
- [x] 三模式适配共用 SDK 帮助能力；nanobot facade/历史别名保持；bridge 实现从 harness/loop.py 原样归 integrations/nanobot，旧函数同对象导出。
- [x] 不改 Environment/sources.py；新实现自动进入 layer_source_paths，adapter 显式声明其依赖闭包。
- [x] 跑 mode/identity/module/decision/bridge/取消测试；提交。

### Task 3: scorer 文件搬迁与联合验收

Files: benchmark/scorers/{deterministic,trajectory_judge,rubrics,judge_client,response,agentic_metrics,agentic_metrics_worker}.py；旧模块兼容门面、身份闭包和必要导入；tests/benchmark/test_scoring_compatibility.py。

- [x] 在迁移前保存固定输入的正式评分结果、rubric Hash 和请求预算测试；新 scorer 导入应先红灯。
- [x] 原样迁移后保持旧 API、monkeypatch 边界和独立 -m worker，确保无双份算法。
- [x] 运行定向及完整 Evaluator、root/contracts、Ruff、verify_assets；全新 clone 独立 core 安装及离线 demo。独立审查后按所有权整合 Environment 提交。
- [x] 验收文档明确仅 M1 最小闭环完成；完整集成目录迁移、通用 loader/descriptor、M2 以后仍待实施。

验收结果：完整回归 1,316 passed / 14 skipped，新克隆定向 163 passed / 1 skipped，根 CLI/contracts 61 passed；细节与后续边界见 [验收记录](../../migration/benchmark-m1-acceptance-2026-11-06.md)。
