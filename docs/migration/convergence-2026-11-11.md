# 渐进收敛与兼容记录（2026-11-11）

按用户四步方案实施，不新增评测能力。执行计划见[计划](convergence-plan-2026-11-11.md)。

## 第一步：模块职责与调用关系

路径相对于 `packages/evaluator/src/eval_framework/`，除显式包名外。静态遍历 378 个 Python 模块，对其中 50 个 Trace、Harness、Environment 与历史执行/评分模块整理直接及间接导入者，再核对 CLI、注册工厂与 worker 等动态入口。完整清单保存在 `.migration/convergence-20261111/import-audit.json`；静态导入图不是无死代码的证明。

| 分类 | 实现 | 直接调用者及间接入口 | 保留职责与本轮处理 |
| --- | --- | --- | --- |
| 主线 | Inspect 公共 API | `harness/adapters/inspect_solver.py`、`integrations/nanobot/inspect_bridge.py` ← adapters / benchmark runner ← benchmark CLI | 调度、预算、沙箱生命周期、原生事件与日志；不修改上游 |
| 主线 | `harness/core/agent_loop.py`、`core/tool_router.py` | `harness/adapters/inspect_solver.py` ← raw_model / nanobot_component | 自研异步编排主实现；Schema 验证公共化，保留原生错误恢复 |
| 兼容 | `harness/conversation.py`、`router.py` | 公开 `harness.run_conversation`、同步插件协议、离线测试及外部 callback | 保留同步调用、立即终止错误、bare file map、工具输出类型、清理和预算语义；Router 使用环境 Schema |
| 主线 | `environments/` | Harness、native worker bridge、文件环境适配 | 初态、工具执行、独立快照与清理；不评分 |
| 主线/可选接入 | 独立 `agent_trace_sdk` 包 | Provider 执行、mini benchmark、外部 Agent 接入 ← 旧 Suite / 新 Provider adapter | Inspect 业务证据适配；业务规则、脱敏、采集状态和读回，公共身份校验移入 contracts |
| 主线 | `harness/trace/timeline_extractor.py`、`tracer.py` | Inspect solver / nanobot bridge ← benchmark adapters | 转换原生事件与环境证据；保留路径专有要求，关联来源事件 |
| 主线 | `benchmark/scorers/`、`benchmark/domains/` | runner / 重评分入口 / 报告 ← benchmark CLI | DeepEval 正式评分、领域诊断和汇总；GEval 仍仅显式调用 |
| 主线/共享 | `eval_contracts`、`capability_snapshot_kit` | Builder、Evaluator、mini_agent、SDK | 运行时中立契约和校验；Builder IR 仍在内部，不引入 Inspect |
| 历史兼容且仍被复用 | `runner.py`、`inspect_engine.py`、`scoring.py`、`native_scoring.py`、`reporting.py`、Suite contracts | 历史 API/CLI；`agent_adapter.execute_provider_request()` 复用 Provider 生命周期；`mini_scoring.py` 的 DeepEval metric 复用 scoring/native_scoring 断言 | 顶层公开 API 按需加载；必要实现不整块迁走或删除 |
| 可选参考 | `examples/mini_agent`、`providers/mini_agent.py` | composition 可选工厂、显式 API、旧冻结资产 | 原实现与接入保留；缺失时 core 与 external Provider 可用 |
| 原生被测 Agent | `integrations/nanobot/`、独立 nanobot AgentLoop | nanobot adapters / worker | 被测原生运行条件，不属于自研循环去重对象 |
| 可选交付 | Langfuse | 显式导出命令 ← 保存结果 | 展示已有结果；不自动上传 |
| 根入口 | `src/agent_eval_suite` | CLI / scripts / Make | 独立解释器与子进程调度；不导入包运行时 |

### 转发文件并非重复实现

`schemas.py`、`phase2_schemas.py`、`schema_base.py`、`capabilities.py`、`capability_loader.py`、`dataset_loader.py`、`dataset_validator.py`、`evidence_requirements.py`、`errors.py`、`tool_catalog.py` 把旧模块名指向 contracts。`harness/loop.py` 指向 nanobot Inspect bridge；`benchmark/metrics.py`、`agentic_metrics.py`、`agentic_metrics_worker.py`、`judging.py` 指向当前 scorers。`sys.modules` 转发保持同一模块对象与旧 monkeypatch 行为，不能当作两份业务实现删除。

### 同步与异步的保留差异

| 行为 | 同步 callback | 异步 Inspect 主线 |
| --- | --- | --- |
| 输入/输出 | dict history、原始 Python 工具输出 | Inspect messages、ToolCall、文本工具输出 |
| 参数错误 | `InvalidToolCall`，结束本次运行 | 原生 ToolEvent 错误，可恢复；受连续错误策略约束 |
| 预算 | `max_steps` 计 callback，跨 followup | step/tool/time/error/native Inspect 多种预算 |
| 生命周期 | 环境 reset/snapshot/final_state/teardown | Solver 管理环境，loop 关闭 Agent，屏蔽取消确保清理 |
| 证据 | callback 无原生 ModelEvent，不伪造模型日志 | 必须有原生 ModelEvent 与关联 route/turn |

这些差异无法通过简单 `asyncio.run()` 等价适配，尤其已有事件循环中的同步调用和工具错误恢复。本轮收敛公共路由，保留同步循环并明确兼容用途；后续移除须另行定义迁移协议。

## 第二步：公共证据逻辑

- `eval_contracts.trace.duplicate_event_ids()` 和 `associations_match()` 承载运行时中立的身份与同属关联校验；SDK `validation.py`、历史 `trace_analysis.py` 和原生 timeline 转换复用。保留现有共享模型字段和 SDK issue/status 语义。
- SDK 保留 envelope 字段规则、采集计数、脱敏、完成/关闭状态、读回验证以及历史容错。SDK 新增对共享 contracts 的显式依赖，仍是独立分发包；Evaluator 的 SDK 必需依赖未移除。
- Harness 保留文件快照、原生模型/工具数量、轮次完整性等路径要求。新增拒绝重复原生 UUID、重复 turn/route 端点、孤立或重复使用 route、call/turn 错配及跨轮次时间错配。错误仍保留独立终态，只标记 `evidence_complete=False`，不会用 Agent 返回值补全。
- 转换 turn 显式携带 `native_event_id`，工具投影携带原生 ToolEvent 和 route 端点的 `source_event_ids`。这些是来源引用，不新增事件存储，不把投影计成另一份独立证据。
- 原生日志损坏整体拒绝、历史 JSONL 只读容错的区别不变；写入失败、缺失事件、未结束与内存降级规则继续由现有 SDK 回归覆盖。
- `layer_source_paths()` 已收录 contracts `trace.py` 与整个 Harness 目录，新代码自然进入运行身份；保留旧记录身份和 Hash 算法。

本轮发现并修复的证据漏洞是转换层的完整性误判，不改变 DeepEval 正式评分算法，也不重写历史结果。损坏日志不能因为事件数量相同就被当作完整证据。

## 第三步：循环与工具路由

新增 `harness/tool_validation.py::ToolSchemaValidator`，公共实现负责 JSON Schema 校验及错误分类。异步 Router 保留 Inspect Schema 可表达性检查和原生工具执行；同步 Router 保留 JSON 解析、`InvalidToolCall` 与原工具输出，改为消费环境 `tool_schemas()`。`FileToolsEnvironment` 暴露独立 Schema 副本；旧无环境/无 Schema 调用仍回退现有文件领域声明，不再维护 Router `_FIELDS`。

同步 callback 与异步主线的参数接受/拒绝、类型不强制转换、工具 allowlist、错误归类、预算、followups、独立快照及清理有兼容测试。异步 `run_agent_loop()` 的控制流未改动；同步循环保留上表列明的非等价用途；nanobot 原生 AgentLoop 未改动。

## 第四步：旧依赖与删除依据

本轮删除清单为空。旧 API、转发模块和 SDK 都有运行调用、兼容承诺或冻结依赖；按需导入缩小影响范围，不降低依赖声明。`eval_framework.__init__` 的公开名称全部按需加载，`__all__`、`dir()`、历史函数/类对象身份和显式 mini_agent 导入保持兼容。顶层导入、ProviderRegistry 与外部 Provider 不再隐式加载历史执行器、报告和 Suite 编译执行。

现有共享逻辑并不都需要搬走：`agent_adapter.execute_provider_request()` 本来已统一 Provider 生命周期；`mini_scoring.py` 在 `deterministic_values()` 范围内复用旧断言，正式执行仍由 DeepEval 驱动，不调用旧 Inspect Scorer。此次确认这些调用为共享兼容实现，保留原位置而非制造另一份实现。旧报告仅在明确请求时加载。

全新 Core 环境没有 minimal_agent，外部 Provider 和旧 Suite Demo 可运行；全新 Builder 环境没有 Evaluator/Inspect，共享校验和 Builder 测试可运行。

## 验收

日志、改前 Hash、评分基线和克隆安装记录位于 Git 忽略的 `.migration/convergence-20261111/`。凭据和 live smoke 开关从测试环境移除，禁用 DeepEval telemetry；测试与演示没有调用真实模型或上传 Langfuse。安装通过包索引解析依赖，与离线模型/服务验证分开。

| 项目 | 实际结果 |
| --- | --- |
| 相关定向回归 | Trace/SDK/历史分析/懒加载 79 passed；Schema 与同步生命周期 34 passed |
| 独立审查修复 | 1 项 Important：route 两端同时指向另一个存在的 turn 仍被接受。先复现失败，再加入时间归属校验；原生 Harness 33 passed。无遗留 Critical/Important/Minor |
| 包回归 | Contracts 22 passed；Builder 353 passed / 5 skipped；mini_agent 323 passed / 1 skipped；根集成 58 passed。SDK 由 Evaluator 消费者测试覆盖 |
| Evaluator 全包 | 首轮 1,523 passed / 9 skipped；审查修复后全包重新运行，1,524 passed / 9 skipped，291.64 秒 |
| 相同保存证据评分 | 4,181 条 file-tools v1/v2 保存 observation 的 verdict、validity、正式 metrics、错误与评分版本完全相同。含历史验收副本，不能视为 4,181 次独立 Agent 执行。6 条非正式 ToolCorrectness reason 仅有集合输出顺序差异，分数不变 |
| 历史 Suite 读回 | 6 组旧保存结果、18 条 case 经公开 `load_run_result()` 读取，原 quality_conclusion 与文件 Hash 均一致 |
| 新克隆安装 | 本地 Git `clone --no-hardlinks` 后叠加本轮源码；分别新建 Core、Builder 虚拟环境，没有复用开发 venv，两者 `pip check` 通过 |
| 新克隆回归 | 最终 Core 定向 99 passed；Contracts 22 passed；Builder 验证 16 passed |
| 新克隆演示 | 根 CLI 子进程调度 5 条离线参考任务，5 PASS，报告生成成功；旧 external Provider Demo 为 PASS / FAIL / INCONCLUSIVE。参考执行只是框架自检，不代表真实 Agent 成绩 |
| 安装隔离 | Core 查不到 `minimal_agent`；Builder 查不到 `eval_framework` 和 `inspect_ai`；显式外部 Provider 导入、历史 CLI help 通过 |
| 资产 | `verify_assets.py` 验证 1,172 个导入参考资产；改前记录的 1,452 个冻结数据、报告、fixture 与历史结果文件 Hash 全部一致 |
| 静态检查 | 本轮 Python 文件 Ruff 及 `git diff --check` 通过。Evaluator 全目录仍有 159 项既有 lint（140 项 I001、19 项 E501）；对 HEAD 基线 163 项比对，无新增问题，未批量改格式 |

一次完整包回归需要数分钟；审查后的代码变化只涉及 Harness 证据边界，因此重新完整运行 Evaluator，其他包已完成回归且源码未再变化。Docker opt-in、可选 nanobot、未安装 DeepEval 的 Builder extras 与付费 smoke 跳过，第三方弃用警告保留。

### 复现入口

```bash
python3 scripts/test_all.py
python3 scripts/verify_assets.py
# 全新克隆内，用 Python 3.11+ 分别创建新环境：
python3 scripts/setup.py --only core
python3 scripts/setup.py --only builder
make demo EVAL_PYTHON=.venvs/core/bin/python BENCHMARK_OUTPUT=artifacts/convergence-demo
.venvs/core/bin/python scripts/demo.py --output-dir artifacts/convergence-legacy
```

### 分步回退边界

1. 职责文档和 SDK README 可独立回退，不改变执行。
2. 公共证据函数、SDK dependency/调用者、历史分析与 timeline 修改作为一组回退；保留原始日志与结果，不重新保存旧身份。
3. 两个 Router、公共 Schema validator 和同步环境 Schema API 作为一组回退；循环控制流未改，不涉及 nanobot。
4. 顶层 API 懒加载可独立回退。删除清单为空，不需要恢复已删除实现。

回退运行代码后仍必须重新计算实际运行身份，不能复用另一源码版本的恢复目录。

### 最终补记

最终源码上的各包回归合计 **2,280 passed / 15 skipped**，没有失败。新克隆最终验证的 280 个 Evaluator/contracts/SDK 源码文件与当前工作树逐字节一致。实现验收时改动留在工作树；用户随后授权提交、推送并合入默认分支。已有 `output/`、`tmp/` 及并行 readiness 改动不纳入本轮提交。

所有四步均保留独立验收与回退边界。同步 callback、实际复用的历史断言和旧导入转发继续保留，不声称已经移除所有历史执行代码，也不把尚未验证的 Docker/可选 nanobot 路径描述为已验证。
