# Harness 分层改造设计

## 目标与边界

依据用户提供的四层架构图和改造建议，在当前 monorepo 内抽取 Harness、Environment、Benchmark 评分和指标聚合职责。用户明确暂不改被测 Agent；现有 Provider、nanobot/mini_agent/tau 接入协议保持兼容。此次实现基础分层与配置组合，不扩展新领域、新任务或新指标，不执行真实模型评测或上传服务。

## 采用方式

采用渐进抽取：旧 Python API、CLI 和冻结任务字节保持不变，旧模块转发到新的实现。相较一次性移动全部模块，这种方式允许逐层回归，避免破坏独立 worker 的导入；仅增加未接线的接口则无法完成职责分离。上述方案由本次实现根据代码现状选定。

Inspect 继续负责调度、执行与日志；DeepEval 继续负责正式评分。新的协议不替代二者。通用 TaskSpec 放入共享 `eval_contracts`，Builder 生成 IR 不变。评分私有字段只在可信评分端读取，执行投影只包含公共任务字段。

## 实现单元

1. 插件：扩展 Environment、ToolRouter、UserSimulator、Scorer Protocol 和精确版本类型；Suite 可选引用只有显式配置才参与编译快照，旧 Suite 默认 hash 语义不变。新引用必须解析、校验并留身份，不能静默忽略。
2. Environment：抽出 file-tools 的 workspace 初始化、安全路径、独立快照和生命周期；固定 followups 成为确定性 UserSimulator。以独立临时 workspace 保持 task 隔离。现有被测工具仍由原 worker 执行。
3. Harness：抽出我们拥有的执行边界、消息/工具路由及轨迹采集；保留 Inspect 沙箱、预算和子进程执行。`trajectory.py` 实际是 checkpoint 评分，不当作 tracer 迁移。不得重写被测 AgentLoop。
4. Benchmark：Executable/Reference/LLMJudge 评分接口包装或迁移现有实现，DeepEval 调用新的 scorer；保留诊断与正式结论的分离、INVALID/INCONCLUSIVE 与失败的区分。
5. Aggregator：将现有汇总迁出 runner/report，显式提供 Step、Turn、Task、Trial、Benchmark 聚合，旧 summarize 输出保持一致。不把未知成本当作零，不把缺失 trial 当通过。
6. 配置：Model、Harness、Environment、Benchmark、Execution 五份严格 Spec 和 RunRequest；保留旧配置读法，提供显式离线迁移命令，凭据只允许环境变量名。公开 JSON 示例不包含本机私密路径。

## 验收

- 新接口行为、生命周期清理、非法路径、配置无损往返、回答隔离有针对性离线测试。
- 原有 package 回归和 ruff 检查通过；保存可访问历史证据的离线评分逐项对比，按实际找到的数量记录，不把建议中的数字当验收事实。
- 冻结资产逐字节校验；不修改 `data/`、原有报告、历史结果、参考 fixture。
- 全新克隆安装与离线 demo 验收，记录来源和具体输出于 `docs/migration/`。
