# Benchmark 职责边界实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 在本任务内逐项实施；完成后独立审阅。

**Goal:** 减少 Benchmark 编排对具体领域与 Agent 实现的依赖，保持历史入口和评测语义。

**Architecture:** 移动实现、保留兼容门面；数据格式与执行后端分别保持自己的契约。

**Tech Stack:** Python 3.11、Inspect、DeepEval、pytest、ruff。

**Spec:** docs/superpowers/specs/2026-11-06-benchmark-boundaries-design.md

## Global Constraints

- 只在本仓库工作；冻结数据、历史结果和 Oracle 隔离不变。
- 不调用真实模型、托管服务；不改 Harness 所有文件，不提交其他任务修改。
- 保留逐样本运行身份检查、独立 worker 和各模式语义。

## Review Focus

- 拷贝到 Docker 的 worker 依赖必须完整，且无需安装 Evaluator。
- 新实现文件必须进入来源 hash，已有字段/标签不能偷偷重解释。
- 兼容入口仍可导入，评分和比较不能漂移。
- 数据读取保留逐字节摘要和各版本的严格拒绝行为。
- 缺少可选 Agent 包时核心/外部 Provider 继续可用。

### Task 1：比较与编排上下文

**Files:** benchmark/runner.py、benchmark/run_context.py、benchmark/identity.py、aggregator/comparison.py；tests/benchmark/test_benchmark_boundaries.py。

**Interfaces:** compare_runs(baseline, candidate) -> dict 保持；RunContext 与 InspectRuntime 组织 _run 的参数，run_benchmark 公共签名不变。

- [x] 补比较独立导入、损坏记录拒绝的边界测试并验证红灯。
- [x] 提取比较和公共摘要，替换 _run 参数装配；保留旧 API。
- [x] 跑 test_runner、test_provider_domain、test_agent_adapters、test_native_runtime、test_harness_integration。

### Task 2：领域加载与 reference

**Files:** benchmark/datasets/io.py、benchmark/domains/file_tools.py、benchmark/tasks.py、core_tasks.py、provider_tasks.py、scorers/reference_runner.py、oracle.py、scorers/reference.py。

**Interfaces:** 旧 load_tasks/dataset_identity/validate_task/select_tasks/execution_task 不变；read_jsonl_bytes(raw: bytes) -> list[dict]、file_sha256(path: Path) -> str 只做基础读取；独立 reference_observation(task) 不读 oracle。

- [x] 测试无运行时依赖的领域加载、冻结 manifest 身份与 reference 等价。
- [x] 下沉 file-tools 实现、共享读取基础能力，保持合同校验与异常语义；迁移 reference 并留门面。
- [x] 跑 task/core/provider/oracle/scorer/metric 相关测试。

### Task 3：Environment 与 nanobot 集成边界

**Files:** environments/local_files.py、environments/file_tools.py、environments/inspect_file_tools.py、benchmark/nanobot_runtime.py、benchmark/inspect_runtime.py、benchmark/inspect_docker.py、benchmark/layer_sources.py、integrations/nanobot/ 的实现与 worker 支持。

**Interfaces:** safe_path、snapshot_files、prepare_tokenizer、runtime_identity、execute_task 原签名可用；独立 worker 保留原启动方式。

- [x] 测试通用 Environment 不导入 nanobot、符号链接/路径拒绝和 worker 独立导入。
- [x] 迁移 SDK 实现与通用文件操作，更新沙箱依赖和来源覆盖；保留模块入口。
- [x] 跑 Environment/runtime/module/decision/identity/Docker 输入相关测试。

### Task 4：集成验收与文档

**Files:** docs/migration/benchmark-boundaries-acceptance-2026-11-06.md；文档导航。

- [x] 运行完整 Evaluator 回归、相关 contracts/root 检查、ruff 与冻结资产检查。
- [x] 独立审阅，修复有证据的问题；只提交本任务文件。
- [x] 与 Harness 任务整合后运行联合回归；全新克隆独立安装与离线 demo。
- [x] 记录实际执行的验证、未覆盖项目和保留的兼容路径。
