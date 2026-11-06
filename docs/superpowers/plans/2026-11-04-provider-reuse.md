# Provider 复用与可选依赖实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 复用已有 Provider 注册和生命周期，解除 benchmark runner 对 nanobot 的直接依赖，并使 Langfuse 可选。

**Architecture:** 增加 AgentAdapter 可选扩展及 EvaluationProvider 桥接，使用现有 ProviderRegistry 解析。nanobot 实现留在领域适配层。展示依赖通过 extra 和延迟加载隔离。

**Tech Stack:** Python 3.11、Inspect 0.3.280、DeepEval 4.2.9、可选 Langfuse 5.0.2。

**Spec:** `docs/superpowers/specs/2026-11-04-provider-reuse-design.md`

## Global Constraints

- 只在当前仓库工作；使用现有 `codex/tool-benchmark-deepeval` 分支和独立包环境。
- 不改冻结数据集、历史结果或历史 Hash 算法；不调用模型或上传服务。
- Oracle 不进入执行输入；新运行使用新的 Harness 身份。
- 保留旧 Provider API、既有 nanobot 配置默认值和命令行为。

## Review Focus

- 未知工厂或不支持 benchmark 的旧 Provider 明确拒绝，不能回退到 nanobot。
- 执行或投影失败后仍清理 Provider runtime。
- 适配器实现/运行身份变化拒绝恢复。
- Langfuse 缺包不能阻止核心运行或本地报告。
- 离线适配器不使用 Oracle 生成观察，证据缺失不能伪装为成功。

## Task 1: Provider 桥接与 benchmark 注册

**Files:** `provider_registry.py`、新增 `agent_adapter.py`、`composition.py`、新增 `benchmark/adapters.py`、`benchmark/runner.py` 及相应测试。

**Interfaces:** `ProviderRegistry.create_adapter(provider_id, *, config)` 返回 `AgentAdapter`；`run_benchmark(..., provider_registry=None)` 支持可信代码显式注册。`EvaluationProviderAdapter` 接受可信 worker 命令与领域投影；worker 通过 `execute_provider_request` 复用现有 Provider，不接收完整任务/Oracle。

- [x] 添加替换适配器、Provider 生命周期、身份漂移和 Oracle 隔离测试并确认失败。
- [x] 实现注册扩展、nanobot 适配器和 Provider 桥接，runner 仅调用中立接口。
- [x] 运行新测试、既有 runner/runtime/provider 回归，修复兼容问题。

## Task 2: 可选 Langfuse 与依赖清理

**Files:** Evaluator `pyproject.toml`、`cli.py`、`benchmark/cli.py`、展示相关入口、`scripts/setup.py`、约束文件/文档和可选依赖测试。

**Interfaces:** 安装 `agent-evaluator[langfuse]`；`scripts/setup.py --with-langfuse`；旧 `--optional-metrics` 的环境选择保持可识别，但不再重复声明 DeepEval。

- [x] 添加缺包子进程测试及安装元数据测试，确认失败。
- [x] 延迟加载展示能力，提供明确缺包错误，更新安装参数和重复 extra。
- [x] 在有/无可选 SDK 的环境运行相应离线回归。

## Task 3: 验收与 mini_agent 可行性

**Files:** 中文架构/使用文档、`docs/migration/` 验收记录。

- [x] 检查 mini_agent Provider、冻结任务和工具环境，记录可直接使用及仍需补齐的边界。
- [x] 运行完整包回归、lint、冻结资产检查和干净副本安装/demo。
- [x] 独立代码审阅，处理实质问题；保留测试证据和用户可检查的 diff。

## 执行记录

- 初始工作树干净；当前为已有 codex 功能分支。依用户已明确授权的两项调整在本地执行，避免另开工作区影响独立环境绑定。

- 独立审阅发现并修复沙箱降级、逐模式身份漂移、线程超时和后代进程清理问题；有失败复现、原生 Inspect 测试及复核通过记录。最终证据见 `docs/migration/provider-reuse-acceptance-2026-11-04.md`。
