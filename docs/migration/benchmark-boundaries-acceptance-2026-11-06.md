# Benchmark 职责边界整理验收（2026-11-06）

本轮执行用户已批准的 Benchmark 结构整理，与独立 Harness 任务按文件分工协作。基于 Harness P1 实现及验收提交 `188977f`、`6e99123`，只在 adapter 的 `fingerprint_sources` 增补迁移后来源；没有改动 Harness 循环实现。

## 实现范围

- `aggregator/comparison.py` 承载运行比较，`benchmark.runner.compare_runs` 保留薄兼容入口。`RunContext` 与 `InspectRuntime` 将内部 `_run` 改成显式上下文装配，公共 `run_benchmark` 签名保持。
- file-tools 的任务校验、加载与公开投影归入 `benchmark/domains/file_tools.py`，旧 `tasks.py` 保留公开入口。`benchmark/datasets/io.py` 只共享逐字节 JSONL 读取和文件摘要，各任务契约仍分别校验。
- 独立参考执行迁至 `scorers/reference_runner.py`；`oracle.py` 保留历史函数与评分转发。没有修改 DeepEval 正式判定、Oracle 隔离、参考结果或冻结任务。
- 通用路径约束及文件快照归入 `environments/local_files.py`；tokenizer、nanobot 源码探测与 SDK 身份归入 `integrations/nanobot/nanobot_sdk.py`。`nanobot_runtime.py` 保留旧 API 和不安装 Evaluator 的独立 worker 导入方式。
- Docker 构建复制使用集中来源清单，包含 shim、SDK、通用文件工具和既有 worker。源码身份闭包纳入新实现与共享摘要算法；覆盖快照将共享摘要模块正确映射到 contracts 包。历史已保存 Hash 不改写，新执行生成新的源码身份。

## 保留的边界

worker 隔离、nanobot 原生路径、module/decision/agent 的执行语义和运行中身份漂移检查均保留。不把原生 Agent 强制改走组件 Harness，不以只缓存一次身份替代运行校验。没有批量移动 tau/mini/core 协议，也没有删除兼容入口。

新增能力标签、难度、通用 pass^k 报告、人工校准和 Langfuse 看板属于后续方案评估，不在此次结构迁移中修改。冻结任务、历史报告和文档中的限制说明继续有效。

## 验证

实现提交为 `979d84a`。Harness 已作为父提交整合，以下验证针对整合后的源码：

| 项目 | 实际结果 |
| --- | --- |
| 完整 Evaluator 回归 | **1,285 passed / 14 skipped**，262.47 秒 |
| 根 CLI 与 contracts（根工作树集成后） | **61 passed** |
| Evaluator Ruff、Git diff 空白检查 | 通过 |
| 冻结资产校验 | **1,172 项通过**，工作树及新克隆均验证 |
| 独立只读代码审查 | 未发现重要/阻断问题；比较、参考执行与通用文件函数 AST 保持等价，身份检查顺序及 worker 依赖闭包保留 |
| 全新克隆独立 core 安装 | `scripts/setup.py --only core` 与 `pip check` 通过；未安装 minimal_agent、nanobot 或 Langfuse，核心导入成功 |
| 新克隆定向回归 | **99 passed**；涵盖新增边界、runner、Provider、任务、scorer、身份、Docker 输入、Harness 与原生报告 |
| 新克隆根 CLI / contracts | **58 passed / 3 skipped**；三项跳过为未安装 Builder 环境的 CLI 协议检查，已由根环境 61 项覆盖 |
| 新克隆离线演示 | 根 CLI 五条参考 demo、Inspect 原生报告、自研 Harness 合成 demo、ExternalProvider 的 PASS/FAIL/INCONCLUSIVE 三类结果全部通过 |

首轮完整回归暴露了新增共享摘要标签映射错误，已修复；另有一项取消测试未在两秒内启动嵌套子进程，最终整套重跑通过，未放宽测试或超时阈值。完整套件的 14 项跳过涉及可选组件/环境、Docker、保存的历史证据及明确禁用的真实模型 smoke；本轮没有以构建输入测试冒充 Docker 实际运行。

工作区回归日志保存在 `workspaces/benchmark-cleanup/.superpowers/benchmark-boundaries/`。新克隆位于 `.migration/benchmark-boundaries-clean-20261106/`，使用自己的 `.venvs/core`，在安装后快进到实现提交再执行验收；安装、验收与根环境日志分别是 `.migration/benchmark-boundaries-install.log`、`.migration/benchmark-boundaries-clean-acceptance.log`、`.migration/benchmark-boundaries-root-tests.log`。演示产物位于新克隆的 `artifacts/benchmark-boundaries/`。

以上演示仅用于框架离线验收，不计入真实 Agent 成绩。没有调用真实模型、上传托管服务、填写人工标签或改写冻结数据。
