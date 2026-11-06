# Inspect 自研 Harness 第一阶段验收（2026-11-06）

## 授权与范围

用户确认“Inspect 管评测运行，自研 Harness 管 Agent 执行”方向，并在成本讨论后授权第一阶段改造：先实现框架，保留原 nanobot 接入，不自动全量重评、不调用付费模型、不上传托管服务。起点为 `4e6d32755ccb54d64cd7de581252671bb0dfadbd`；执行层主提交为 `8d68e76`。

新增 `provider=raw_model`，经现有 benchmark CLI 和 Custom Solver 进入异步自研循环，提供 BaseAgent、状态、组合停止策略、动态 JSON Schema Router、Inspect 原生工具/模型调用、文件 Environment、版本化 Prompt、标准 Trace 与原 observation 投影。继续使用 DeepEval 正式评分。使用方法见[自研 Harness](../benchmark/native-harness.md)。

## 边界和实施决定

- 保留旧同步循环、router、nanobot worker、默认 provider 和整任务 AgentAdapter；新增异步 core，不搬迁历史文件。代价是两个入口暂时并存，文档明确其用途。
- 新路径仅支持 agent 模式；module/decision 仍走原生入口，明确拒绝静默转换。这样避免用框架工具替代被测 Agent 工具后仍声称是同一评测。
- 使用可选 `execute_in_inspect(..., state=TaskState)` 接入方法。锁定的 Inspect 版本没有公开的当前 TaskState getter，由外层 Solver 明确传递，避免依赖私有接口；旧 Adapter 无需改动。
- JSON Schema 与 Inspect ToolInfo 无法无损转换时明确拒绝，未支持的复杂 schema 需要后续适配。缺省 additionalProperties 按原 JSON Schema 语义显式规范化。
- local 模式是 Inspect 每样本目录隔离，不是 OS 沙箱；Docker 和真实模型行为未在本轮实测。不改变历史结果代表的运行身份。
- 在仓库内部隔离 worktree 实现，初期复用已安装的依赖环境并通过 PYTHONPATH 选定本轮代码；最后以独立全新克隆和自己的 core venv 验收，排除开发环境偶然依赖。

## 独立审查

一次独立只读审查发现两项 Important、零 Critical、零 Minor。以下两项均先以失败测试复现，再修复：

1. 嵌套 schema（如 `not`）可能在 ToolInfo 转换时丢失，且缺省 additionalProperties 从允许变成禁止。现在比较转换前后契约，无法保持的约束明确拒绝，规范化缺省值；补充嵌套 object 测试。
2. 缺失全部 ModelEvent 时，原完整性判断可能因空列表而通过。现在把 stop 的 steps/tool_calls 与原生模型事件、工具事件、路由前后记录、业务轮次关联数量交叉核对；删去单个/全部模型事件或整组工具证据都不能标记完整。

此前专项测试也覆盖多工具中途预算耗尽、重复 tool-call ID 跨轮关联、参数拒绝与恢复、截断、原生 token 限额、取消、环境初始化/执行/清理故障、并发隔离、Oracle 不进入输入、身份变更拒绝恢复。

## 验证记录

| 检查 | 最终结果 |
| --- | --- |
| Evaluator 全包回归（审查修复后） | **1,266 passed / 6 skipped**，137 条上游/兼容弃用 warning |
| 新增专项测试 | **29 passed** |
| Contracts | 3 passed |
| 根集成 | 58 passed |
| 全新 core 克隆定向回归 | **146 passed**，无 skip |
| Ruff / compileall / diff | 包级检查全部通过 |
| 全新 core 安装 | setup 与 pip check 通过 |
| 新循环合成演示 | PASS（固定假模型生成动作，真实本地工具执行，DeepEval 评分） |
| 配置驱动 CLI | 正常结束，固定假回复未完成冻结任务，正式 verdict 为 FAIL |
| 冻结参考资产 | 1,172 项校验通过，数据/历史结果无改动 |

六项 skip：两项显式 Docker 集成、两项工作树未携带的本地历史证据测试、两项付费模型 smoke。没有把这些未执行项表述为通过；历史证据原件保留在原工作区，未因新路径删除或改写。

全新克隆位于 `.migration/native-harness-clean-20261106/`，安装自身 `.venvs/core`，`setup.py --only core` 与 `pip check` 成功；未安装 minimal_agent 或 Langfuse。原生循环离线合成演示 PASS。现有 CLI 使用 mockllm 固定回复执行冻结任务，预期 FAIL，证明执行完成不等于任务通过。

冻结校验通过：1,172 个导入参考资产和 fixture；`data/`、`reports/`、冻结 datasets 与 Builder fixtures 相对起点无改动。未修改评分公式、冻结任务或历史结果；未重新执行历史 nanobot 全量评测。

本轮开发和回归日志已汇总到 `artifacts/verification/native-harness/`；独立安装与验收原始日志同时保留在 `.migration/native-harness-clean-*.log`。测试/演示的模型是 Inspect mockllm，真实模型调用和托管导出未启用。
