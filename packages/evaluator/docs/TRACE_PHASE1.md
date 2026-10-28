# 业务证据协议与 Inspect 原生 Trace

采集包位于 `packages/agent_trace_sdk`，由评测体系维护，独立发布为
`agent-trace-sdk`。当前包是业务适配层：通用采集与存储由 Inspect 原生实现；包依赖固定版本 `inspect_ai==0.3.280`，无 Agent、数据集、评分和报告依赖。先安装仓库固定的 Inspect，再安装适配包：

```sh
python -m pip install -e ../agent_evaluator/third_party/inspect_ai
python -m pip install -e ../agent_evaluator/packages/agent_trace_sdk
python -m pip install -e ../mini_agent
python -m pip install -e ../agent_evaluator
```

`MiniAgentProvider` 默认使用独立通道。其他 Provider 通过可选方法
`create_observed_runtime(execution, session_id, scope, sink)` 接入；没有此方法的
旧 Provider 继续使用内嵌证据。配置独立通道后禁止回退内嵌事件。

兼容门面 `TraceCollector` 保留 `record()/export()`，内部直接使用 Inspect `Transcript.info`，不维护自研事件列表。mini_agent 的同名类只提供现有
事件规则与兼容入口。直接使用 Agent 时，可注入 `evidence_sink`，并在每轮
传递 `TraceContext(trace_id, turn_index)`。同一 Trial 共用一个 Sink，由调用方
在所有轮次结束后调用 `finish(execution_completed=...)`，不由单轮 Agent 关闭。

Runner 在执行前创建目录、`execution.json` 和每个 Trial 的
`evidence/<trace_id>/association.json`。调用 `run_evaluation(..., output_dir=...)`
可指定目录；未指定时创建独立临时运行目录，通过结果对象的 `run_directory`
读取。该本机路径仅用于定位产物，比较两次运行时应忽略。CLI 自动将输出目录传给 Runner，报告
继续写入同一运行目录。每个 Trace 保存原生 JSON EvalLog `trace.inspect.json`：
Sample.events 是业务 InfoEvent，Sample.metadata.evidence 是计数与采集状态。
两者使用 Inspect `write_eval_log` 一起原子保存，Reader 使用 `read_eval_log` 独立读取。
新生产类为 `InspectEvidenceSink`；`LocalEvidenceSink` 仅保留导入别名。旧 JSONL 写入和独立
collection 检查点已删除，历史格式仅只读兼容。报告复制原始证据，不重新生成事件。

## 协议和判定

- Trial 级 sequence 在校验和写入前分配，跨轮递增。记录尝试数、写入数和
  最后序号；Reader 按 sequence 排序，核验缺口和计数。单 Trial 使用同步 Sink，
  不支持多个进程共享同一文件。不同 Trial 可以并发。
- 主状态优先级为 EXPORT_FAILED > PARTIAL > STILL_OPEN > COMPLETE，全部问题
  同时保留。UNAVAILABLE 表示没有证据来源；旧内嵌事件存在时标记 PARTIAL，并记录
  legacy_embedded_trace 来源及完整性无法确认的原因。正常业务 FAILED 可以对应
  COMPLETE；关闭文件不等于正常业务终态。中断执行保留 STILL_OPEN，除非更高
  优先级的问题存在。进程被终止时保留最近一次成功提交的原生快照；尚未提交的事件不能作为证据。Inspect 的本地 JSON 写入包含原子替换和 fsync。
- 状态有内存副本，磁盘写入失败不会改写 Agent 的业务返回或重试工具。内存只可降低证据有效性，不能将磁盘未完成快照升级为 COMPLETE；原生日志损坏不回退到旧格式或内嵌事件。
- 每种事件有 Agent 维护的字段白名单和必需字段规则。未知事件保留公共信封，
  未声明的 payload 字段被过滤；缺少字段、脱敏或截断的事件保留但标为 INVALID，
  不作为严格检查的有效证据。脱敏按字段规则及常见 token 模式处理，不能保证识别
  任意自由文本中的秘密；接入方必须只提供允许采集的业务数据。
- 旧 `AgentResult.events` 与 `intent_trace_snapshot()` 保留原始兼容内容，仅用于
  旧调用方；独立证据及其脱敏不改变业务结果。最终业务输出的隐私策略由调用方负责。
- 异常后逐项执行证据充分的检查。已观测的禁止调用可以判失败；缺少最终输出或
  完整覆盖时，passed=None、applicable=True。未知检查不得通过权重排除获得 PASS。
- 结果增加 evaluation_validity=VALID/INVALID 和 evaluation_issues；必需证据
  通道故障或关联故障使评测 INVALID，不覆盖 Agent 业务状态，且 score=None，
  不允许总体 PASS。独立的已证实失败可以保留。

## 能力声明与 Builder

保持 Snapshot v3 的结构，使用 JSON Schema 注解 `x-evidence-delivery` 声明本地
接口、协议版本、事件字段和不可用条件，不升级整个 Snapshot 协议。通道只包含声明
的过程事件，不保证复制 IntentResult/AgentResult 的全部字段。原返回接口继续可用。
当前不支持跨轮上下文继承、确认接受和自动重试的业务能力仍标记 unsupported。

Evaluator 的 `validate_dataset` 对带新声明的契约检查断言所需证据。Builder 现有
`evaluator_gate` 已调用该接口，因此复用此门禁，无需修改 Builder 的当前工作区。
没有新声明的冻结旧契约保留原校验行为；新导出的能力快照重新计算 hash，不修改
已冻结的数据集。证据声明和实际运行完整性由不同阶段分别检查。

mini_agent 的 `capabilities/` 被现有 Builder Suite 按哈希引用，因此保留原冻结
内容。新快照已导出到 `mini_agent/exports/trace_v1`，可通过能力 CLI 重新生成；
新建 Suite 时显式绑定该目录与新 hash，避免旧 Suite 因源快照被覆盖而失效。

第一阶段不包含 Span、OTLP、远程接收服务、自动插桩或新增业务恢复逻辑。

## Evaluator 收尾与读取约定

采集收尾、证据读取、Provider 证据校验、断言、诊断、Trace 分析与 Runtime
清理失败均记录到 `evaluation_issues`，并使该 Trial 的 `evaluation_validity`
为 `INVALID`。这些错误不覆盖已记录的 Agent 执行状态；清理失败另写
`cleanup_status=CLEANUP_FAILED`。后续 Trial 继续执行。原始 Agent 异常独立保留。

读取时核对 `association.json` 与 Runner 在内存中的案例关联，以及文件中事件的
`trace_id`。关联失败的事件保留在原文件中，但不作为当前 Trial 的判定依据。
独立通道的读取故障不使用内嵌事件补救。初始化期间已经产生的事件也会尝试收尾和读取。

只有明确定位到某条事件的内容损失，且采集正常结束、检查需要的事件类型未受影响，
才允许保留该检查的完整覆盖判断。序号缺口、损坏记录或未结束采集不能证明禁止行为
没有发生。无论采集状态如何，INVALID 事件均不参与严格业务检查；它们仍展示在原始
时间线中。未知断言保持 `applicable=True, passed=None`。

新声明的预检检查交付版本、协议版本、读取接口、关联字段、事件规则版本和所需
payload 字段。模块结果检查继续读取返回的 IntentResult，不要求过程事件复制所有
返回字段。断言语义版本为 `phase1-v3`，与旧规则运行比较时按已有版本规则处理。

新报告的 Trace 和采集状态链接指向 `evidence/<trace_id>/trace.inspect.json`，另附
`association.json`。历史结果仍链接原来的 JSONL 与 collection.json。独立事件不再另生成 `evidence/<case>/<trial>/trace.jsonl`；旧内嵌
模式继续保留该产物。复制报告逐字节保留原始证据文件，写入新报告的 `run_directory`
指向目标目录；移动后的报告由 `load_run_result` 按实际位置重新定位，不修改原文件。

报告摘要分别计数采集状态和评测有效性。含 INVALID Trial 的报告标记为
`INVALID_RUN`，Release Gate 不可通过，业务质量比较标记 `INVALID_COMPARISON`；
已证实的单项业务失败仍保留。本机路径与随机 Trace 标识不参与业务输出稳定性判断。

## 2026-10-21 原生替换边界

- Inspect 负责通用 Transcript 和 EvalLog 读写；Evaluator 保留事件字段白名单、脱敏政策、
  Trial 关联、序列与完整性检查。`legacy.py` 只读取历史文件，不创建旧格式。
- Agent 返回值中的兼容事件投影使用原生内存 Transcript，不能作为正式证据读取失败时的
  备用源；正式业务事件只保存于本 Trial 原生日志。主执行 `.eval` 记录来源引用，避免再
  逐条复制这批事件。结果文件内的 trace_events 是评分和 Langfuse 导出用的只读投影。
- Langfuse 继续通过显式导出读取正式结果，不另启动采集。冻结证据接口和事件协议版本不变，
  运行身份中的 SDK 源码 Hash 会变化；版本比较须在新后端重新跑基线。
- 每次事件保存一次当前 Trial 的原生 JSON 快照，轨迹增长时存在重写开销。当前适用于
  小规模业务评测；长轨迹吞吐未验收，不宣称已采用原生增量流。以后优化应使用 Inspect
  的原生增量机制，不恢复自研 JSONL 引擎。

验收：Evaluator 全量测试 378 passed、2 个付费测试跳过，Ruff 通过；独立 Agent 自有虚拟环境已补齐本地 Inspect 依赖，全量测试 321 passed、1 个付费测试跳过。未执行云端上传。
