# Inspect 内自研 Harness：第一阶段

用户已批准成本受控的第一阶段：只改造自己的编排，保留 nanobot 原生 worker 和整任务 Adapter，不调用付费模型、不上传服务、不全量重评 nanobot。

新增明确 opt-in 的 `provider=raw_model`，使用现有 benchmark CLI、Inspect 调度和 DeepEval 评分。仅支持 agent 执行模式；module/decision 仍走原入口，禁止静默改变它们的含义。自定义 Solver 内调用异步 agent_loop，通过 BaseAgent.step 产生动作；RawModelAgentAdapter 只调用 Inspect 单次 generate。一个业务 Turn 可以含多个模型步骤和工具调用。固定 UserSimulator 的后续消息仅在上一轮最终回复后加入。

通用 ToolRouter 从异步 Environment 获取工具 JSON Schema，校验后通过 Inspect execute_tools 调用工具。校验拒绝反馈模型；基础设施异常保持异常语义。模型步骤和工具调用分别限额，调用前检查，取消不吞掉。Environment 的实际文件操作经过 Inspect sandbox；local 是样本临时目录隔离，不宣称 OS 隔离。

Inspect transcript 是事件事实来源；业务 info 仅补充轮次、路由、环境快照和停止原因。共享 contracts 定义 Task/Turn/Step Trace，提取器生成 Trace 并投影到现有 observation，不改变 Scorer。Oracle 不进入执行输入、消息或公开元数据。模板以版本和内容 hash 记录。

冻结数据、历史结果、旧 API、默认 provider 保持不变。新旧身份区分。验证使用确定性 Agent、Inspect mockllm 和真实本地 sandbox，不调用真实模型或托管服务。完成后做 evaluator 回归、contracts 与相关集成检查，以及全新克隆安装和离线演示。
