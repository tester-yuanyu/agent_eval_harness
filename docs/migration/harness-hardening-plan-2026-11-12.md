# Harness P0/P1 两批实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 提高崩溃证据可取回性、取消测试稳定性和身份计算效率，隔离 Langfuse 看板 API；不重跑有效评测。

**Architecture:** 保留 Inspect 执行、DeepEval 正式评分与现有证据 SDK；通过稳定 attempt 目录与原生恢复保存部分证据。身份复用只限同一个同步校验点，执行前后重新读取源文件；看板模板与回执语义不变。

**Tech Stack:** Python / pytest / anyio / Inspect 0.3.280 / 现有 agent_trace_sdk / Langfuse 5.0.2。

**Spec:** 本文记录用户于 2026-11-12 批准的 P0/P1 方案；当前聊天中的两批方案为范围依据。

## Global Constraints

- 保留 Python API、CLI、冻结数据与历史 Hash 算法；旧产物只读。
- 不调用真实模型、不上传云端、不升级依赖、不删除兼容入口，不实施 P2。
- 复用当前 checkout；不新增 worktree。产品修改不触及 mini_agent 的业务代码。
- 原始输入与 Oracle 分离；部分证据不能据此判 PASS；失败取证不能掩盖原错误。
- 新执行身份允许改变，历史执行与有效评分不重跑；本次不自动推送。

## Review Focus

- 进程在模型/工具执行前后被杀，证据目录仍可发现，取回不能依赖正常 finally。
- 并发 trial、同 case 多次 attempt、旧残留文件不得串用；不完整或损坏证据保留错误状态。
- 超时测试必须先证明子进程已启动，再验证取消；不能仅延长时间而失去清理断言。
- 相同大小/mtime 的源码修改、文件增删、异常退出及并发校验都不能复用过期身份。
- 看板 API 错误与格式变化不能写出 VERIFIED；无 Langfuse 安装时核心导入保持可用。

### Task 1: 测试就绪协议（第一批）

**Files:** `packages/evaluator/tests/benchmark/test_agent_adapters.py`。
**Interfaces:** 真实子进程写 started 标记；启动 budget 与取消观察 budget 分开，不新增产品测试专用开关。
- [x] 注入慢启动，复现原固定 2 秒用例未触达子进程即超时。
- [x] 使用就绪握手触发父取消；worker 超时场景用独立启动上限。保留 cleanup 与后代终止断言。
- [x] 运行该文件的取消测试并保存 RED/GREEN 输出。

### Task 2: 可发现、可取回的崩溃证据（第一批）

**Files:** `benchmark/agent_readiness.py`, `full_worker.py`, `full_adapter.py`，`harness/adapters/{runtime,inspect_solver}.py`，`benchmark/runner.py`，新 `harness/trace/evidence_checkpoint.py` 及相应测试。
**Interfaces:** 每次执行创建唯一 attempt 目录；现有 `InspectEvidenceSink` 直接写持久路径。宿主在成功/失败/取消路径均尝试保存取证文件，回执包含 attempt、Hash、完整性，部分证据只用于审计。路径 A 复用原生日志恢复及 SDK checkpoint，不新增独立日志框架。
- [x] 测试先复现成功前证据不可发现、失败宿主不取回，以及双 attempt 串用风险。
- [x] 最小实现稳定目录、分阶段持久化、失败取回与绑定校验，保持旧接口默认行为。
- [x] 对模型/工具边界强制中断；正常执行仍兼容，残缺/错误关联不得通过。
- [x] 运行 readiness、full benchmark、native harness、恢复和取消相关离线回归。

### Task 3: 同一校验点复用内容快照（第二批）

**Files:** `source_identity.py`、`benchmark/{runner,package_sandbox,full_adapter,identity}.py`、`harness/adapters/runtime.py`（以实际共享读取边界为准）；`tests/test_source_identity.py`。
**Interfaces:** `identity_checkpoint()` 仅包围同步身份校验，无跨 await 缓存；读取同一文件的 bytes/内容摘要在该点内复用。开始执行及结束执行各用新快照，公共 Hash 算法保持原字节语义。
- [x] 测试重复读取次数、独立校验点变更检测、等长且相同 mtime 修改、文件增删和异常清理。
- [x] 接入现有身份读取与 runner 校验点，保留外部 Provider 的原有调用行为。
- [x] 比较 identity 输出完全一致，记录 I/O 次数和本机耗时；不承诺真实模型端到端加速比例。

### Task 4: Langfuse 看板 API 边界（第二批）

**Files:** 新 `benchmark/langfuse_dashboard_api.py`；`langfuse_presentation.py`、`langfuse_explorer.py` 与现有看板测试。
**Interfaces:** 懒加载 SDK 的 Dashboard/Widget gateway，集中 list/get/create/update、定义验证；复用既有传入 client、节流器、确定性 ID、回执与 Metrics 回读。
- [x] 新离线边界测试覆盖分页、错误和不兼容响应不被视作成功。
- [x] 将 unstable 路径集中至 gateway；模板、统计口径与幂等恢复不改。
- [x] 运行 Langfuse presentation/explorer/delivery/v4 测试，不联系云端。

### Task 5: 集成与交付

- [x] 一次独立审查，只修 P0/P1 范围内的重要问题。
- [x] 运行包级回归、全新克隆安装与离线 demo；核对受保护结果 Hash。
- [x] 在 `docs/migration/` 记录结果与边界，交付两批改造说明；不运行历史评测。
