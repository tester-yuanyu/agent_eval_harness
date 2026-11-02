# nanobot 覆盖补齐 Implementation Plan

> **For agentic workers:** 使用 superpowers:subagent-driven-development；已获用户执行授权，按明确文件所有权实施，由协调者集成与提交。

**Goal:** 固定实际 nanobot 与评测 profile，交付可验证覆盖矩阵及第一批离线核心组件基准。

**Architecture:** 新任务合同与组件 worker 独立于冻结文件工具合同；Inspect 调度、DeepEval 确定性评分。覆盖报告分别陈述源码、启用、任务、执行与人工审核状态。

**Tech Stack:** Python 3.11、Inspect、DeepEval、JSONL/JSON/Markdown。

**Spec:** `docs/superpowers/specs/2026-11-02-nanobot-coverage-design.md`

## Global Constraints

- 只在本仓库及本次隔离工作树写入；外部 nanobot 只读。
- 不改变旧任务、Oracle、历史成绩及 Hash；新数据集使用新身份。
- 不调用真实模型、不上传、不发送消息；worker 不继承凭据或用户配置。
- Oracle、任务身份与私有预期不进入 worker；状态测量与被测模块返回分开。
- Session/Memory/Context/Skills 结果是组件证据，不是模型或完整 Agent 成绩。
- 人工标签、审核与独立阈值状态保持待完成；holdout 本轮禁止执行。
- 子代理不暂存、不提交他人修改，协调者统一整合。

## Review Focus

- 非法操作、路径/符号链接、嵌套私有字段不能越过执行投影。
- 当前源码、解释器环境或任务 Hash 漂移必须拒绝运行或错误归类，不能沿用旧身份。
- 异常、缺事件、worker 非零退出与快照失败不能被聚合为 PASS。
- 持久化/重载必须调用真实 API，不能由 worker 自己实现被测行为或写入预期答案。
- 覆盖必须绑定具体家族、执行记录及 profile；历史 v2.1 不冒充新 v2.3，dev 不冒充 holdout。

## Task 1：核心合同、worker 与冻结数据

**Files:** `benchmark/core_tasks.py`、`benchmark/core_worker.py`、`benchmark/core_scoring.py`、`tests/benchmark/test_core_tasks.py`、`test_core_worker.py`、`test_core_scoring.py`、`data/benchmarks/nanobot-core-v1/*`。

**Interfaces:** `load_core_tasks(path: Path) -> list[dict]`、`core_dataset_identity(path: Path) -> dict`、`core_execution_task(task: dict) -> dict`；worker stdin `{task: execution_projection, workspace: absolute_temp_dir, runtime_dir: absolute_sibling_dir}`，stdout observation JSON；`score_core_task(task: dict, observation: dict) -> dict` 返回 `validity/verdict/metrics`。执行器独立追加 `before_files/final_files/session_files/evidence_complete/runtime_identity`。

- [x] 先测试合同/投影/评分故障，观察失败，再实现严格操作集合与 scorer。
- [x] 编写有独立预期的新任务家族，划分 dev/holdout，保留人工审核空状态。
- [x] 真实模块 smoke 仅执行 dev，保留错误与成功证据，报告接口细节。

## Task 2：源码快照与覆盖矩阵

**Files:** `benchmark/capability_coverage.py`、`tests/benchmark/test_capability_coverage.py`、`data/coverage/nanobot-v1/catalog.json`。

**Interfaces:** `snapshot_nanobot(config: dict) -> dict` 固定源码/环境/已知profile；`build_coverage_report(snapshot: dict, catalog: dict, datasets: list[dict], runs: list[dict]) -> dict` 验证来源并生成矩阵；不读用户全局配置、不输出秘密。

- [x] 测试源码/profile差异、缺来源、错误关联和非执行状态。
- [x] 实现可复核身份与矩阵，不把源码存在记作覆盖，也不输出未经定义的整体覆盖率。

## Task 3：Inspect 执行与 CLI

**Files:** 协调者负责 `benchmark/core_runner.py`、`cli.py`、相关集成测试与示例配置。

- [x] 先测试独立重复、来源绑定和 Oracle 隔离，再用 Inspect Sample/Epochs/local sandbox 执行 core_worker。
- [x] 添加 `core-validate`、`core-run`、`coverage` 入口，配置只接受源码和解释器等必要非秘密字段。
- [x] 将实际 dev × 3 组件运行与覆盖清单关联，生成可公开摘要，保留 holdout 未执行状态。

## Task 4：交付与验收

- [x] 独立审查实现和矩阵，修复可复现问题。
- [ ] 相关测试、全仓分包回归、旧冻结资产校验、干净克隆安装和离线 Demo。
- [x] 中文文档、能力矩阵、优先补齐队列、运行报告和验收记录；保留未覆盖与人工待验收项。
- [ ] 整合回用户工作树并提交，不推送远端。
