# Inspect Custom Solver 内的自研 Harness

本阶段只改造框架自身。新增 `raw_model` 执行入口；默认仍是 `nanobot`，其原生 AgentLoop、worker 和独立依赖环境保持原状。新入口是“自研编排 + 原生模型接口”的基线，不代表原生 nanobot 的能力。此次验收不调用付费模型、不上传 Langfuse，也不全量重评 nanobot。

## 职责与调用链

```text
现有 benchmark CLI / runner（Inspect 加载、并发、限额、日志与恢复）
  → Custom Solver → RawModelRuntimeAdapter.execute_in_inspect
    → execute_native_task（公共 TaskInput 装配）
      → agent_loop（自研轮次流转、停止策略）
        → BaseAgent.step → Inspect model.generate
        → ToolRouter 校验 → Inspect execute_tools → Environment.step
  → Inspect timeline + 环境快照 → Task/Turn/Step Trace
  → 既有 observation → 原有 DeepEval Scorer / Aggregator / 显式导出
```

Inspect 仍管理模型调用、工具事件及 sandbox 生命周期。我们决定何时生成、调用哪些工具、何时加入后续用户消息和终止；没有使用 react/generate_loop 接管循环。`transcript().info(source="harness.v1")` 补充业务轮次、校验结果、快照和停止原因；没有增加事件文件写入器。

| 模块（相对 evaluator 的 `src/eval_framework/`） | 责任 |
| --- | --- |
| `harness/core/agent_loop.py` | 异步主循环、错误归属、Agent 清理 |
| `harness/core/session_state.py` | 每个样本独立的公共会话、计数、最后输出 |
| `harness/core/stop_conditions.py` | 可组合策略；在调用前检查预算 |
| `harness/core/tool_router.py` | 环境动态 schema、JSON Schema 校验、原生工具执行 |
| `harness/adapters/agent/` | 单步 BaseAgent 和 RawModelAgentAdapter |
| `harness/adapters/inspect_solver.py` | 可独立使用的标准 Inspect Solver 与装配 |
| `harness/adapters/runtime.py` | 复用旧整任务 Adapter 的显式新入口 |
| `environments/sandbox_files.py` | 框架自有的文件环境，通过 sandbox.exec 执行 |
| `harness/trace/timeline_extractor.py` | 原生事件转换；不采集另一份模型日志 |
| `harness/prompts/` | 版本化模板与内容 hash |
| `eval_contracts.trace`（contracts 包） | 不依赖 Inspect 的 TaskTrace、TurnTrace、StepTrace |

`AgentAdapter.execute()` 是完整 runtime 的接入；新增可选 `execute_in_inspect(..., state=TaskState)` 能力让受控 runtime 更新原生消息视图。旧 Adapter 无需实现此方法。`BaseAgent.step()` 是单步接入，不能据此声称已经接管任意外部 runtime。

## 运行与成本

无需安装 nanobot、mini_agent 或 Langfuse，即可在 core 环境验收新路径：

```bash
python3.11 scripts/setup.py --only core
.venvs/core/bin/python packages/evaluator/examples/native_harness_demo.py \
  --output artifacts/native-harness-demo
```

演示使用合成任务和 Inspect mockllm，真实执行本地文件工具，预期 DeepEval 返回 PASS。这个 PASS 只验证框架闭环，不是模型或 Agent 性能成绩。输出包括既有 run/results/trials 文件和 Inspect 原生日志。

现有 CLI 也支持显式配置：

```bash
.venvs/core/bin/agent-evaluator run \
  --config configs/benchmark-raw-model-offline.json \
  --output artifacts/native-harness-cli
```

此配置对冻结 e2e 数据抽取一条任务，使用 mockllm 的默认固定回复；不会调用真实模型。由于默认回复不执行任务，正式评分可为 FAIL，不能把“命令成功运行”当成评测通过。`demo` 子命令仍是原有 reference replay，不用于证明新循环执行过工具。

真实模型需另行明确配置和评测预算。本次没有运行。nanobot 进程内重写、多 runtime 单步接入、动态用户模型以及全量新旧真实分数对照均不属于本阶段。

## 配置与行为契约

- `environment.provider: "raw_model"` 显式启用；只接受 `execution_mode=agent`。module/decision 输入在预检时拒绝，继续使用它们的原生入口。
- `harness.max_steps` 是整个任务的模型生成次数上限，跨用户轮次累加；实际取任务和运行配置中的较小值。
- `harness.max_tool_calls` 是整个任务尝试工具调用的上限，默认 40，配置范围 1–300；被拒绝的尝试也计数。一条消息多个工具调用按顺序检查，耗尽后不执行剩余副作用。
- `harness.prompt_version` 当前为 `harness-v1`。结果保存模板 hash 与包含 instructions、TaskInput.policy 的实际系统提示 hash。
- Inspect 的 token/message/time 限额仍生效。停止原因与正式评分分离，预算用尽不会标记完成。
- 一个业务 Turn 从用户消息开始，到 Agent 最终回答结束，内部可以多次生成和调用工具。固定 followups 只在上一轮最终回答后加入。
- 截断、未知结束原因、非法 tool-call ID 不当作最终回答；基础设施失败记为 environment/provider/harness，保留部分证据与原异常。
- 工具从 Environment 动态提供。Router 没有四工具硬编码；本阶段的文件环境提供 read/write/edit/list。参数不做字符串到数字等隐式转换。顶层 schema 支持 object/properties/required/additionalProperties/description，不能传给 Inspect 的其他顶层约束明确拒绝，不静默丢弃。

## 隔离、证据和兼容

文件操作通过 Inspect sandbox.exec 执行，关闭有副作用操作的自动超时重试。命令仅接收固定环境程序，模型参数通过 JSON 输入传递。local 使用 Inspect 每样本临时目录，不是 OS 级安全沙箱；docker 复用 Inspect 的内置环境，要求镜像提供 python3。本阶段默认离线验收只验证 local，不声称完成 Docker 验收。

文件工具是框架自有语义，不伪装成 nanobot 原生工具；运行身份明确区分。冻结 task/manifest、参考答案和历史结果均不改写。新源码会形成新运行身份，不能用新版本继续写入旧身份的 run 目录。

Scorer 不改：提取器把标准 Trace 投影为既有 observation，包括工具前后文件、每轮快照、最终状态、错误和完整性标志。相同 tool_call_id 在不同调用中出现时使用独立路由关联，保留各自证据。Oracle 只在可信评分侧；TaskInput 和 Agent 消息不包含私有答案。缺失或中断证据不能因为执行返回而成为 PASS。

离线读取原生日志再提取时，先使用 `read_eval_log(path, resolve_attachments=True)` 解析 Inspect 的 attachment 引用。结果的 Trace 是业务投影，模型/工具原始事实仍以原生日志为准；已有 Langfuse 导出继续消费兼容 observation，只有显式调用才上传。
