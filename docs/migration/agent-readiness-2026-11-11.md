# MiniAgent 剩余 97 条执行接入

## 结果与范围

本轮接通原先未绑定的 97 条：28 条意图模块、21 条提前停止、21 条模块事件、27 条链路。使用既有 MiniAgentProvider、RuntimeFactory 与 MinimalAgent，Inspect 执行和留存日志。输入由独立确定性脚本提供，不调用付费模型、不访问生产后端、不上传托管服务。

目标是让所有已定义行为真正执行并接受验证，不能通过复制 Oracle 回答或调整冻结期望来取得全绿。本轮不修改 mini_agent 业务实现。

新交付目录为 `output/mini_agent_full_eval_20261111_v4/`。365 条行为定义包括233 Schema、35工具、97 Agent相关案例；202 静态契约检查与287 blocked义务仍另外保留。Agent运行中的LLM边界被确定性脚本替代，因此结果不能作为模型理解能力或生产Agent成功率。

## 具体执行

- **28 意图模块**：Provider `run_module`，向真实 IntentRouter 输入原始候选。候选统一为 READY/CALL_TOOL，保留0、空串、bad-phone等无效参数，让运行时完成归一化、参数校验、确认和拒绝；没有将期望状态喂给模型。
- **21 提前停止**：Provider `run_full`，验证 NEED_CLARIFICATION、NEED_CONFIRMATION、REJECTED，工具和 handler 均未执行；end_to_end 按原 `turns_match` 及终态目标检查。
- **21 模块事件**：明确刺激实际组件，包括归一化、参数/语义失败、工具guard、handler失败/超时、模型工具步骤失败、步数耗尽。`model_failed` 对应工具循环中的模型调用失败，不宣称覆盖意图分类调用异常的全部路径。
- **27 链路**：12正常、15受控工具故障，通过Provider完整执行。记录真实handler调用、工具结果、模型交互、状态和SDK事件；按来源链图验证 intent_validation → tool_execution → bounded_execution → result_emission。提前停止按声明分支验证意图节点和终止，不伪称经过未执行工具节点。

新 `AgentReferenceContext` 只含来源能力文档、Schema与参考身份，没有cases或Oracle。输入解码仅支持此次作者维护的合成模板，不是通用中文解析器。未匹配输入保持未绑定。

## 暴露出的三条差异

| Case | 观察结果 | 判定 |
|---|---|---|
| `I-intent.add_backpack_gift.9101ca688a883c` | num=0时返回NEED_CLARIFICATION，但parameters仍含num=0 | 参数与期望不符，且不符合绑定参数Schema |
| `I-intent.query_gift.296ed04ad02b7a` | gift_id=0时缺参为gift_id、single_gift_query_mode | 原定义只期望gift_id，严格缺参项检查失败 |
| `I-intent.query_pool.a9686242d0217c` | pool_id=0时缺参为pool_id、single_pool_query_mode | 原定义只期望pool_id，严格缺参项检查失败 |

第一项需要修正运行时无效字段处理；后两项需要明确缺参列表规范，再对齐实现或创建有明确依据的新数据集版本。当前保留失败，不修改冻结定义。它们是已经执行并得到FAIL的案例，不是UNBOUND，也不是执行器崩溃。

## 证据与版本兼容

- v3 readiness 请求携带manifest绑定的能力文档；v1/v2请求仍按原版本字段集合计算Hash。三份既有交付的请求Hash已与旧evidence逐一核对。
- 参考与当前运行能力bundle身份分开保存。执行前校验当前Schema、决策规则和新快照中的execution_semantics，不能只用参考bundle冒充当前能力。
- SDK InspectEvidenceSink独立写入并读取逐例事件，检查事件VALID、连续sequence、计数、trace/run身份及完成标志。
- 工具请求、实际handler调用、ToolCallRecord和工具终结事件相互核对；最终状态、响应、intent结果也必须与trace一致。
- 分类和每次next_tool_step的输入输出全部记录；工具结果必须实际进入下一模型步骤，最终文本由实际工具输出构造。删除整个工具循环记录不能通过。
- 运行日志在 `readiness/logs/`，逐例SDK日志在 `readiness/logs/business/<case-id摘要>/trace.inspect.json`；完整可重验观测也保存在 `readiness/evidence.json`。
- CLI的`readiness run/check`仍按整份交付的发布门槛返回1：失败案例或blocked义务未清零，不会自动冻结。

## 重跑

从仓库根目录执行，workspace须不存在：

```bash
.venvs/evaluator/bin/python -m agent_eval_suite.cli readiness run \
  --delivery output/mini_agent_full_eval_20261111_v4/dataset \
  --workspace output/mini_agent_full_eval_20261111_v4/readiness-rerun
```

查看 `report.json` 的category_counts、agent_category_counts、逐项checks；不要将返回码1解读为所有案例运行失败。定义中的NOT_RUN维持原静态语义，实际运行以独立readiness证据为准。

## 新交付实测

| 分类 | 执行 | 通过 | 失败 |
|---|---:|---:|---:|
| Schema |233|233|0|
| 六工具 |35|35|0|
| 意图模块 |28|25|3|
| 提前停止 |21|21|0|
| 模块事件 |21|21|0|
| 链路 |27|27|0|
| 合计 |365|362|3|

UNBOUND清零，运行绑定率100%，reference验证率99.2%；287 blocked不计入这365分母，整份交付不满足发布门槛。输出目录包含failure_details.json（逐项实际/期望）与case_evidence_index.json（97份SDK日志及Hash）。四份新旧交付各56个capability文件、254个dataset文件均通过manifest Hash核对。

## 工程验收

- Contracts：37 passed；Builder：378 passed、5 skipped；Evaluator：1576 passed、9 skipped；根 CLI：61 passed。跳过项为可选依赖、Docker或真实付费模型测试；本次未启用它们。
- 独立 fresh clone 叠加当前工作树后，分别安装 Builder/Evaluator 并完成依赖检查；新增 Agent 测试20 passed，再次导出、生成、校验和执行，复现362通过、3失败、0未绑定。
- 验证 Builder 环境未安装 mini_agent 仍可导入共享校验；历史冻结交付校验通过。386个相关源码文件与验收 checkout 逐字节一致。
- 当前产物 `readiness check` 无身份过期或证据完整性错误；唯一整体阻塞仍为实际失败和blocked义务。新旧交付字节和历史请求Hash保持不变。
- 验收日志与独立产物保留在 `tmp/agent97/acceptance-logs/`、`tmp/agent97/artifacts/`；临时克隆和虚拟环境已清理。
