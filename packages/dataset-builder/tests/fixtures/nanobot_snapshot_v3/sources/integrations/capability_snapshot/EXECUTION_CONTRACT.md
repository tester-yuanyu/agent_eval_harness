# Nanobot 端到端执行与错误契约（声明版 v2）

本次补充只修改能力导出声明和 Nanobot 专用评测边界，保持 Snapshot 3.0。
不改变 Agent 行为，不增加评分器，不把源码声明当成已执行通过。
机器可读契约在 `contracts.json`，相同内容也写入快照意图、输出和工具契约。

## 端到端到底覆盖什么

边界是一次 **`await Nanobot.run(...)`**，调用对象已经构造完成。
起点在本次调用的模型选择之前，终点是返回 `RunResult`、抛出异常或传播取消。

普通模型路径包含：本次模型选择 → 可选 MCP 连接 → 会话锁与恢复/预压缩 →
命令路由 → 上下文构造 → 模型与工具迭代 → 前台持久化/响应准备 → SDK 结果转换。
这不是每次都走完的固定序列：命令处理可提前返回；异常或取消可从任一阶段退出；
模型调用未必产生工具调用。模型选择和 MCP 连接发生在会话锁之前。

不包含对象构造、gateway 启动、外部渠道送达确认，以及后台记忆整理、
`spawn(wait=false)` 子任务、未来 cron 触发、脱离前台的 shell 进程和其他会话。
这些工作可能在返回后继续。`spawn(wait=true)` 等本次实际 await 的工作属于前台边界。
返回、异常或取消都不保证全局静止、业务成功、无副作用或自动回滚。

## 输出与终止分支

| 分支 | 原生观察 | 下游不能推断的结论 |
| --- | --- | --- |
| 普通返回 | RunResult；常见 stop_reason=completed | completed 不等于业务成功，拒绝或内容过滤文本也可能是 completed |
| 模型错误响应 | 终止时可返回 stop_reason=error 和 error 文本 | 不保证抛 Python 异常 |
| 致命工具错误 | 未被后续继续/恢复时可返回 stop_reason=tool_error | 不能将每个工具错误都视为整轮失败 |
| 迭代上限 | max_iterations，可有无工具收尾调用或降级文本 | error=null 不表示完成业务任务 |
| 最终空响应 | 恢复后仍为空时为 empty_final_response 和诊断文本 | 不是用户要求的业务答案 |
| 命令快捷路径 | 跳过模型 runner，返回命令响应 | stop_reason、usage、messages 等可保持默认值 |
| 响应被抑制 | process_direct 返回 None 时 content="" | 不表示没有执行或没有副作用 |
| 未捕获异常 | Python 异常直接离开调用，没有 RunResult 保证 | 不得要求每次都有 final_response |
| 取消 | asyncio.CancelledError 传播 | 不保证返回 stop_reason=cancelled，不保证回滚 |

RunResult 的字段与类型从真实 dataclass 导出：content、tools_used、messages、usage、
stop_reason、error、metadata。所有返回分支都使用这个结构；异常包不伪装成 RunResult。
`tools_used` 在最终 runner 捕获中来自成功工具事件，并非全部调用/失败尝试。
`error`、`stop_reason` 需要合看；业务正确性还需要任务断言、真实输出和环境观测。
注入后续消息导致继续执行时，runner 可能保留先前的 error/stop_reason，
同时 final_content 已经是后续恢复回答。因此状态字段不一定精确描述最后一条回答；
不能仅凭非空 error 断定恢复回答无效，也不能忽略此前失败与已发生的副作用。

`evidence.final_response` 只适用于返回分支。
`evidence.run_exception` 描述供评测方实现的异常采集格式，**不是 Nanobot 原生 JSON 输出**，
因为本导出方尚未实现这个观察器，其可用性保留 unknown。
`evidence.execution_contract` 是可检查的静态契约文件，只支撑契约已声明的能力，
不能用来证明模型、工具或业务效果。普通 run() 没有 SDK StreamEvent 事件生命周期；
流式入口属于另一边界，不能混用断言。

## 输入与共享工具错误契约

完整输入参数已列入 input_schema，model 与 model_preset 不能同时为非空选择值；
channel="system" 是保留值。hooks 为 Python 对象接口，不可当作普通 JSON 参数传入。
ephemeral 控制会话策略，不是工具副作用隔离或事务回滚开关。

直接调用 ToolRegistry.execute 与模型正常走 AgentRunner._run_tool 是两条路径：
runner 通常先 prepare_call，再直接调用具体 tool.execute。
工具不存在、参数被拒绝、ToolResult.is_error、普通实现异常、策略拦截和控制流异常
已经在 result_protocols 中区分。分类名是适配器说明标签，不是稳定业务错误码。
普通字符串以 "Error:" 开头不自动构成内置工具错误标记。

工具事件的共享字段为 name、status（ok/error）、detail，可从 runner hooks 观察。
它们不是 RunResult 的独立字段。fail_on_tool_error=false 通常让模型尝试恢复，
true 可令整轮以 tool_error 返回；工作区/重复查询策略和继续执行机制仍可能影响结果。
注册器不承诺自动重试实现调用；模型再次调用、provider 重试、工具内部重试须分开看。

## 仍然缺失什么

21 个工具的完整成功结果 Schema、稳定业务错误码、逐工具权限/确认、幂等、批量规则
和副作用细化仍不完整，未知部分不会由共享契约推导出来。
没有真实模型/服务运行证据、业务验收基准或环境测试夹具。
不将源码里有流程等价为当前配置中该流程已执行成功。

现有 conversation 的评测意图沿用，但旧的通用边界无法表达上述错误退出，
因此改用包内 `specs/` 的 Nanobot SDK 细化版本（相同 scope/chain/boundary ID）。
`scope.result` 的响应要求只用于返回路径；异常分支需要单独的观察器。
静态契约能力可声明为 supported；对话、工具业务执行等仍为 unknown。
