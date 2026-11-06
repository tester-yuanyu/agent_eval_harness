# Environment 改造实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 在当前任务逐项实施；最终独立审查。

**Goal:** 解耦 Environment 与 Agent/Harness 实现，统一新接口并保留旧行为。
**Architecture:** 中立 Protocol、单一文件工具源码、领域包、延迟兼容入口；Inspect 继续管理沙箱。
**Tech Stack:** Python 3.11+、Inspect 0.3.280、pytest。
**Spec:** [设计](../specs/2026-11-06-environment-design.md)

## Global Constraints

不改冻结数据/Oracle/评分；不调用真实模型或托管服务；不修改或暂存并行 Benchmark 任务文件。实现位于独立 worktree，集成前核对交界文件。

## Review Focus

绝对路径和符号链接策略差异；2 MB 与 CRLF 快照；无 Evaluator 的独立 worker；错误发生阶段与取消；兼容导入循环和同步调用。

## Task 1: 契约与领域包

文件：environments/base、file_tools 包、旧模块转发；harness/core/tool_router.py 契约重导出；专用 tests/benchmark/test_environment_contract.py。
接口：reset(initial_state)、tool_schemas()、step(name, arguments)->str、snapshot()、teardown()；保留旧同步类。
- [x] 写公共导入、旧同步生命周期、异步离线适配、无 Agent 导入测试并验证 RED。
- [x] 迁移契约与领域实现、schema，增加适配器；验证 GREEN。

## Task 2: 公共文件源码与进程交付

文件：environments/_fs_utils.py、local_files.py、file_tools/worker_script.py、sandbox_env.py、integrations/nanobot/{sources.py,environments/}。
接口：safe_path(..., relative_only=False)、snapshot_files(..., relative_only=False, max_file_bytes=2000000)；build_worker_script() 自包含源码。
- [x] 写边界、沙箱独立执行、错误分类、worker bundle、身份漂移测试并验证 RED。
- [x] 收敛实现、装配 worker、迁移 nanobot bridge、保留兼容入口；验证 GREEN。

## Task 3: 扩展、文档与集成验收

文件：examples/simple_retail_environment.py、专用测试、docs/migration/environment-refactor-2026-11-06.md。
- [x] 增加不改核心的领域注入演示与实际 Harness 测试。
- [x] 全包 pytest、Ruff、冻结资产核验、独立审查与修复。
- [x] 仅提交本任务文件，集成并进行新克隆安装和离线 demo；记录真实结果与限制。

实际结果见 [迁移验收](../../migration/environment-refactor-2026-11-06.md)。实现 `4b96e6e`，整合 `91ebb96`；全部实施项完成，真实 Docker/模型运行不属于此次离线验收。
