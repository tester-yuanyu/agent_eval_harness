# Nanobot P1：组件接入与原生运行时对照

P1 在第一阶段自研循环上增加 `nanobot_component`，保留 `nanobot` 为默认完整运行时。两者是不同实验条件，历史 612 次结果仍属于其原始身份；本次不重跑历史评测、不调用付费模型、不上传 Langfuse。

## 两条路径

| 入口 | 实现 | 主循环与工具 | 依赖位置 |
| --- | --- | --- | --- |
| `nanobot` | `NanobotRuntimeAdapter`，旧名 `NanobotAdapter` 是同一类 alias | 原生 AgentLoop / 原生工具，通过旧 worker 子进程运行 | worker 独立 Python 环境 |
| `nanobot_component` | `NanobotComponentAdapter` 实现 BaseAgent；`NanobotComponentRuntimeAdapter` 桥接 Provider | 自研 loop / ToolRouter / Environment；Inspect model.generate | Evaluator 当前进程的可选 nanobot 环境 |
| `raw_model` | RawModelAgentAdapter | 同一个自研 loop，直接使用框架 prompt | core 环境即可 |

`RawModelRuntimeAdapter` 是整任务 Provider 到自研 loop 的桥接器，不是独立原生 loop。真正保留原生循环的对照是 `NanobotRuntimeAdapter`，其已有子进程路径一直保留。

组件 profile 为 `nanobot-context-v1`：复用 nanobot 的 ContextBuilder 系统提示组装、原生 identity/tool_contract 模板、用户消息构造和参数规范化。Inspect 已处理模型协议的 JSON 解析，组件保留其 parse_error，不声称重做一次原始响应解析。模型调用仍是 Inspect 原生接口，生成事件、工具事件、业务 Trace 和正式评分共用此前通路。

## 共享进程隔离

组件不执行原 worker 的 setup，也不调用 set_config_path、logger.remove、tokenizer monkeypatch 或写 TIKTOKEN_CACHE_DIR。每个样本创建独立临时目录和 ContextBuilder，任务结束/失败时清理。禁用个人 bootstrap 文件、Memory 检索、Skills、插件发现、压缩和原生工具执行；使用实例依赖替换禁用技能，不修改上游全局类。原生 identity 使用稳定的逻辑工作区路径，实际文件工具只接受 Inspect 环境内的相对路径。

公开任务 policy/instructions 追加到原生 prompt；Oracle/参考答案仍只进入可信 Scorer。输出保存 profile、实际 prompt hash、nanobot Python/Markdown 源码 hash 和框架运行身份。原生模板可能提及不可用工具，实际允许集合以环境 schema 和附加框架约束为准。

nanobot 必须在启动时已经可被当前解释器导入。适配器不为每个 sample 修改 sys.path，不支持同一进程同时载入多个 nanobot 版本；需要比较版本时启动不同评测进程。可选 nanobot_root 若填写，必须与已加载包的来源一致，否则预检失败。`python`、tokenizer 等旧 worker 配置不用于组件路径。只装 core 时 raw_model 和其他 Provider 仍可导入；选用组件时缺依赖会明确报错。

## 停止策略

- `TimeoutStop`：`harness.timeout_seconds` 在 loop 内显式建模为样本 wall deadline，包括模型和工具 await。到期取消正在等待的操作，记录 `time_limit`，保留部分轨迹并清理。它不能抢占阻塞 Python 同步代码，也不取代 Inspect 对整个 sample 的超时兜底；环境准备仍受外层限制。清理位于 shielded cancel scope，不受 loop deadline 或 Inspect 同类取消作用域强制中断；各清理实现需自带边界（内置文件快照命令有 30 秒超时，组件 close 同步清理临时目录）。
- `ErrorStop`：可选 `harness.max_consecutive_errors`（1–300）。被拒绝的工具、参数错误和可恢复执行错误计入连续错误，成功工具调用清零。达到阈值后，当前批次剩余调用不执行，记录 `error_limit`。缺省不新增错误阈值，保持原有恢复行为。
- 环境故障、模型连接错误继续抛出并记录来源，不被吞成普通工具失败。Inspect token/message 限额仍保留；本轮没有增加 tokenizer 或另一套 token 估算。

基础设施异常不能因停止策略变成 PASS；超时和错误预算耗尽均产生不完整证据及 Agent 停止原因。正式 verdict 仍由原有 DeepEval Scorer 决定。

## 离线验收与成本

先在独立 Evaluator 环境安装所选 nanobot 源码及其依赖（本轮测试的本地 checkout 为 0.3.0）。也可在启动时通过 PYTHONPATH 显式指向只读源码；这只影响整个启动进程，不在样本间切换。随后：

```bash
python -m eval_framework.benchmark.cli run \
  --config configs/benchmark-nanobot-component-offline.json \
  --output artifacts/nanobot-component-offline
```

示例固定为 Inspect mockllm、local 环境、单条冻结任务，运行时不收费。固定回复通常不能完成任务，正式 verdict 可以是 FAIL。这不是 nanobot 能力复评，也不是新旧分数一致性证明。组件专项测试使用真实 nanobot 代码和固定模型动作，覆盖并发双样本、真实工具执行、DeepEval PASS、私有答案隔离、来源不符拒绝及全局状态不变。

P2 尚未做：动态用户模拟、全量 file-tools-v2 新旧离线基线对比。旧 loop/conversation/worker 路径继续保留，无删除或正式下线。本轮也未完成 Docker 组件验证或真实模型评分对照。
