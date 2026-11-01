# 评测框架复用改造

用户已于 2026-11-01 采纳六项迁移建议，授权自主实施、跨项目检查、测试与回归修复。优先级为 P0 执行与证据、P1 评分、P2 实验与展示、P0 集成验收。

## 目标与选择

Inspect 负责样本环境、运行预算、执行日志、重复与恢复；DeepEval 负责标准指标与 GEval；Langfuse 负责在线实验与展示。自研仅保留冻结任务、业务 Oracle/检查点、独立文件取证、身份约束和最薄适配。

选择 Inspect 原生 Docker Sandbox + sandbox_agent_bridge 对接独立 nanobot，而非将其依赖并入 Evaluator 或继续维护子进程控制器。Inspect 0.3.280 的跨进程 bridge 需要 Linux；本机 macOS 的 local sandbox 仅用于无需模型桥接的模块和离线验证。Docker 环境由官方接口管理，构建输入不得携带凭据或嵌套 Git。

轨迹以 Inspect 原生 ModelEvent/SandboxEvent/InfoEvent 为来源；bridge 不自动产生外部 Agent 的 ToolEvent，业务工具执行与前后快照必须显式作为证据事件关联，不伪造原生工具事件。生成参数透传、四种执行边界、初始文件字节、模型与任务身份保持可核对。

评分优先使用 DeepEval 标准指标、GEval 与公开 tracing API。TaskCompletion/StepEfficiency 是语义诊断，不能替代文件精确终态、禁止修改项或必需 checkpoint。当前无独立人工标签，任何 GEval 正式通过线均不得冒充已校准。缺失/错误分数保持空。原始 Agent 轨迹的事后评测不得重跑 Agent；仅允许将保存证据映射为 DeepEval span。若锁定版本公开接口不能实现某项，记录实证并使用公开 GEval 扩展，不触碰私有接口。

通用展示优先 Inspect View bundle 和 Langfuse；旧报告保留显式兼容入口，独有的分层统计、来源 Hash 与严格可比性核对保留。Langfuse 官方 SDK/OTel 已负责运输，项目仅保留业务字段映射、历史回放、完整性回读。

## 约束与验收

- 不修改冻结数据及历史成绩；新执行/评分使用新身份，原 CLI/Python API 尽可能兼容。
- Oracle/参考答案不得进入 Agent 输入或 Judge 消息；Judge 的局部决策证据不得含未来轮次。
- 不混淆程序模块、一次模型决策、链路、端到端和重复评分次数。
- 测试不调用付费模型、不自动上传托管服务；使用真实框架、真实 nanobot 模块及受控模型/传输替身。
- 不改变原 nanobot 仓库现有修改；适配只能依赖其公开运行边界。所有团队改动在本工作区，子代理不暂存/提交。
- 通过定向测试、Evaluator 与其他包回归、冻结资产校验、Docker 离线 bridge 验收、全新克隆安装与 demo。真实人工校准保留待办，不伪造。

## 自主裁决

工作采用仓库内忽略的 worktree，完成后由协调者提交并快进整合回原功能分支。实现期间的兼容性判断记录在执行台账；无需逐步向离开的用户确认。
