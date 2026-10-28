# Nanobot v3 评测生成约束

## 来源与更新规则

只读取本交付 source_delivery/ 中由清单 Hash 绑定的快照、执行契约、规格和源码证据。Builder 支持本包的 delivery/bundle/ 布局及原 OpenAI function envelope，保留原件，将工具参数投影为统一 Schema。execution_contract.json 为静态声明，不是执行轨迹。31 条新增执行契约候选逐条绑定 JSON pointer 与源码锚点，生成器锁定已审核契约 Hash；契约变化必须重新核对断言，不能沿用或自行猜测缺失预期。

## 分层与场景

37 个快照、31 个主要目标（8 模块、21 工具、1 意图、1 端到端链）均有记录；模块、工具、关键链路、端到端和辅助契约分别存储。参数覆盖类型、必填与省略、nullable、const、枚举、上下界、额外属性、嵌套数组/对象、model/model_preset 互斥与保留 channel。hooks 是 Python 对象接口，JSON 样例使用 null，不制造 Python 对象。Schema 合法性不等于 SDK 或工具运行时接受/拒绝；默认值不会由 Schema 校验器自动填入。

行为候选覆盖正常、异常、边界和源码明确的调用序列。保留 70 条工具、19 条模块源码候选；以 31 条执行契约候选替换旧版 1 条粗粒度端到端候选，包含 13 条端到端分支候选、2 条输入拒绝、12 条共享工具调用与错误处理、4 条观测与恢复契约。覆盖声明中的 9 类终止分支，不枚举所有自然语言任务或运行环境。缺少独立关键链路定义，保留缺口义务；不做无业务依据的工具/模块笛卡尔积。

## 单次运行边界

端到端边界是已构造对象上的一次 await Nanobot.run(...)，覆盖前台实际 await 的工作，终点为返回、异常或取消。命令可提前返回，异常或取消可从任一阶段退出；不强制固定完整路径。排除构造、gateway、渠道送达、后台任务、未来 cron、其他会话和脱离前台的 shell 进程；不推断全局静止、无副作用或回滚。

旧版整体内部模块边界冲突已收窄：配置 MCP 时，契约纳入可选连接，而 boundary 仍禁止 module.mcp。保留该条件路径缺口；本批端到端 fixture 明确使用 mcp_provider=None。独立工具/模块候选不受对话链观察选区限制，也不冒充全部属于该链。

## 断言与缺失预期

schema_contract 只判断 Schema；contract_check 只核对声明；behavior_candidate 带明确 fixture、输入和断言；blocked_obligation 记录尚缺依据的义务。源码推导候选与显式执行契约候选通过 source_basis 区分。unknown 不转为 supported，静态 supported 不代表业务执行成功。

返回路径检查 RunResult；异常和取消不要求原生 RunResult 或 final_response。evidence.run_exception 是评测方待实现的观察格式，导出方尚未实现；其观察器仍阻塞。completed、error=null、非空回答都不能单独判定业务成功；恢复后可能保留旧 error/stop_reason。tools_used 来自成功工具事件，不等于全部尝试。普通 run() 不混用 SDK 流式事件生命周期。

直接 ToolRegistry.execute 与 runner prepare_call→tool.execute 分开断言。共享分类标签不是稳定业务错误码；普通 "Error:" 字符串不自动成为 ToolResult.is_error。注册器不自动重试不意味着 provider、模型再次调用或工具内部重试均不存在。21 个工具仍缺完整成功结果 Schema、稳定业务错误码、权限/确认、幂等、批量与副作用细化；仅收窄共享结果和重试缺口，不清除逐工具义务。

## 依赖、差异与交付状态

执行仍依赖完整 Nanobot 环境、隔离 fixture、受控模型/服务替身、runner 适配、观察器和业务验收基准。120 条行为候选中，117 条保持 blocked；原有 3 条已声明 supported 的返回对象观测候选保持 needs_runner，仍未执行。本次没有将 unknown 升级为 supported。全部记录 DRAFT / NOT_RUN / PENDING。采用 nanobot_candidate 1.0 独立协议，兼容现有 EvalCase 的数量为 0。生成与复验均不执行 Agent、工具或外部服务，也不自动批准或冻结。

--previous 仅只读旧交付；携带可移动的差异基线、候选/断言差异和阻塞差异。源缺口按 fact_id + capability_key 对齐，不能因列表序号移动而误判解除。区分保留、收窄、显式解除、新增、被细化分支替代和无证据消失；最后一类会阻止发布。旧 nanobot 与 mini_agent 目录保持独立且不修改。
