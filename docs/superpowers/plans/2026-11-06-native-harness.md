# Inspect 自研 Harness 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 在保留 nanobot 原路径的条件下提供可实际运行和离线验证的 Inspect 自研循环。
**Architecture:** 通用异步循环与路由，Inspect 模型/工具桥接，动态 Environment，原生 timeline 提取；raw_model 为显式新入口。
**Tech Stack:** Python 3.11、Inspect 0.3.280、Pydantic 2、jsonschema、现有 DeepEval。
**Spec:** docs/superpowers/specs/2026-11-06-native-harness.md

## Global Constraints

- 不改冻结数据、历史结果或评分规则；不调用真实模型/托管服务。
- 保留 nanobot 原生 worker 和默认 provider；仅新增 opt-in raw_model。
- Oracle 不进入执行输入和模型消息；共享 Trace 位于 contracts。
- 全部运行操作经 Inspect 公开 API，local 不宣称 OS 沙箱。

## Review Focus

- 多个工具调用中预算耗尽不能执行剩余副作用。
- 模型没有最终回答、截断、异常、取消不能报告完成。
- 并发样本和后续用户轮次不能共享可变状态。
- 校验拒绝与基础设施异常不能混淆；工具 JSON Schema 不得静默丢弃约束。
- 原生事件导出、独立快照和既有评分投影必须保持关联，缺证不能 PASS。

### Task 1: 原生执行完整路径

**Files:** 新增 harness/core、harness/adapters、harness/trace、harness/prompts、environments/sandbox_files.py；新增 contracts/trace.py；新增 tests/benchmark/test_native_harness.py。
**Interfaces:** `BaseAgent.step(SessionState) -> AgentAction` 为 async；Environment 提供 tool_schemas/reset/step/snapshot/teardown；`run_agent_loop` 接受 Agent、router、simulator 和停止策略；`execute_native_task` 返回兼容 observation。

- [x] 写离线测试：多步、多工具、后续轮次、schema 错误、工具预算、模型截断、取消和并发隔离；运行并确认缺失能力失败。
- [x] 实现异步核心、Inspect 工具执行和业务信息注入、共享 Trace 与投影。
- [x] 运行新测试和相关已有分层测试，预期全部通过。
- [x] 记录验证并提交完整执行路径。

### Task 2: CLI 接入、身份与验收

**Files:** composition.py、orchestration/specs.py、benchmark/layer_sources.py；新增 raw_model runtime adapter、示例和文档。
**Interfaces:** 现有 AgentAdapter 整任务接口接入 `provider=raw_model`；旧 provider 未改变；新 harness 配置包含 prompt_version 和 max_tool_calls。

- [x] 写 registry/RunRequest/runner 集成测试：显式新 provider 可运行、旧默认保留、拒绝 module/decision、模板版本 hash、状态改变不能恢复旧 run。
- [x] 新增 adapter、配置、身份闭包；为 Python 直接调用提供标准 Custom Solver。
- [x] 执行 CLI 离线演示、evaluator 全量回归、contracts/相关集成和全新克隆安装验收。
- [x] 更新中文文档和 docs/migration 验收记录，提交后进行一次独立审查，修复重要问题并验证。
