# nanobot Core v1：离线真实组件任务

本数据集独立于 File Tools 与 Model Decisions；32 个任务、12 个语义家族，覆盖 Memory、Session、Context、Skills。24 个 dev 任务来自 8 个家族；8 个 reserved holdout 任务来自另外 4 个家族。它验证固定源码与配置下的真实组件行为，不是模型或完整 Agent 成绩。

`tasks.jsonl` 与 `manifest.json` 由 `build_dataset.py` 确定性构建，构建器拒绝覆盖不同的已冻结字节。Manifest 绑定 SHA256、合同 `nanobot-core-task-v1`、任务/家族/分组数量。旧数据集与历史结果不变。

每条任务公开部分为 fixtures、必要 settings 和白名单 operations。执行器先准备 fixtures，worker 只收到 settings/operations；id、family、split、description、oracle 不进入执行投影。私有 Oracle 在评测进程通过 DeepEval BaseMetric 检查返回值及独立文件快照，不导入被测实现生成期望答案。

| 组件 | dev 家族（每家族 3 条） | reserved holdout（每家族 2 条） |
|---|---|---|
| Memory | history_integrity、pending_retention | legacy_migration |
| Session | persistence_isolation、legal_replay | delete_recreate |
| Context | memory_visibility、message_assembly | bootstrap_visibility |
| Skills | resolution、invocation_availability | malformed_metadata |

Session `reload` 表示构造新的 SessionManager 后读取实际磁盘，未宣称进程重启或崩溃恢复。Memory 恢复任务使用事先编写的损坏 JSONL/cursor fixtures。Context 使用固定哨兵检查可见性，不对动态系统路径、时间或完整系统提示做逐字比较。Skills 的 builtin 目录显式指向任务 fixture；环境依赖负例使用无凭据的专属缺失变量。

任务与期望由源码合同和明确场景编写，未运行目标来倒推期望值；尚未完成人工独立设计/审核，`human_reviewed=false`。holdout 本轮只做合同与 Hash 校验，不执行、不声称已通过独立未见验证。

首轮开发诊断出现 `core-session_legal_replay-orphan` 的 Oracle 语义争议：冻结期望要求保留孤立 tool 之前的 user 消息，当前 nanobot 的合法后缀策略丢弃该前缀。原任务、Oracle 和失败证据均保留，未改成迎合实际结果；该项不能直接被解释为 nanobot 产品缺陷，需要人工裁定要求。

网络/文件审计护栏只针对固定可信模块，不是 OS 级恶意代码沙箱；本地模块理论上可读同用户其他文件，因此仅保证本次显式配置路径和已测行为，不宣称全局安全隔离。运行器必须禁用真实模型/上传、清理凭据环境并固定源码及解释器身份。
