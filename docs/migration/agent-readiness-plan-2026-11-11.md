# 剩余 97 条 Agent / 模块 / 链路执行计划

用户已授权依次接通49意图/提前停止、21模块事件、27链路，并保留完整365分母与287 blocked。本轮复用 MiniAgentProvider、RuntimeFactory 与真实 MinimalAgent；独立 deterministic reference model 只根据公开输入返回原始候选参数和工具动作，所有状态由 Agent 本身判断，绝不将 Oracle 当模型回答。

## 设计

新增 v3 readiness 请求，携带 manifest Hash 绑定的 capability documents；保留 v1/v2。共享层新增 AgentPlan、输入脚本配方与结果断言，Builder 不导入 MiniAgent。Evaluator adapter 通过现有 Provider 的公开执行入口运行，工具仍为独立 fixture。受控错误只包装白名单工具 handler / model step，不改变通用 Provider 对任意 fault_injection 的拒绝，不执行数据里的代码。

28意图案例执行 run_module；21提前停止执行 run_full。模块事件用明确刺激触发真实组件，经实际 trace 验证，禁止制造事件冒充运行。27链路执行完整 run_full，记录工具输入输出、状态、模型交互、真实trace；按绑定链图检查 intent_validation → tool_execution → bounded_execution → result_emission 的实际证据顺序。错误与提前停止按声明分支验证可达前缀与终止事件，不能要求错误路径继续生成成功结果。

本轮不调用付费模型，不声称验证自然语言模型质量；不改 frozen case/Oracle，不自动冻结。若现有定义与运行真值不一致，保留失败证据并说明，不降低断言追求365全部绿。

## 实施顺序

1. 测试先行：49条输入配方、Provider执行、原始无效参数确实进入校验、Oracle哨兵不影响执行。
2. 21模块事件：明确刺激与作用位置、真实trace、错误/超时/guard/step limit；缺失或伪造事件验证失败。
3. 27链路：隔离fixture、显式handler故障、完整模型和工具证据、节点顺序校验；缺节点/乱序/错误调用不得通过。
4. 接入版本化request、Inspect日志、分组报告；新目录重建全部365并保存剩余真实失败。
5. 独立review、相关包回归、fresh clone 安装演示、旧交付Hash核对；保留工作树不自动提交。

## 进度与决策

- 沿用当前 codex 分支及未提交工作，用户已确认上一轮建议顺序，无需重复设计审批。
- 独立输入解码只支持此次合成模板及模块刺激，不能作为通用中文理解能力；不读生成器 EXAMPLES/Oracle，固定候选状态READY，实际规则负责补参、确认与拒绝。
- Task 1：49条真实Provider执行完成。28意图中25通过、3暴露原有运行/定义差异；21提前停止通过。差异为num=0仍残留、gift/pool无效ID多返回mode缺参项，不改Agent业务或冻结Oracle。
- Task 2：21模块刺激执行通过，SDK原生Inspect evidence验证事件，不凭AgentResult旧式event字典推断VALID。
- Task 3：27链路（12正常、15故障）真实执行通过，绑定handler调用、事件顺序、终止状态和实际返回；反向测试删除handler/state/manifest均先观察到漏洞，再补完整性校验。
- Task 4：v3请求、Oracle-free AgentReferenceContext、365统一Inspect执行与分类统计已接入；旧v1/v2路径保留。
- 独立review确认并修复三项：旧v1/v2请求Hash按历史字段集合计算；AgentResult与SDK trace的run_id、终结状态/输出/响应交叉校验；模型工具循环记录完整性及输入/输出逐步关联。8个新反向/兼容测试均先RED。
- 三个实际历史交付的request.sha256已逐一核对，与旧evidence中的dataset_sha256一致；旧证据仍按当前runner身份过期处理，保留历史身份不等于绕过freshness门槛。
- 最终新交付v4：365执行完成，362通过、3实际失败、0UNBOUND；新增Agent97中94通过3失败；287blocked保持，release_ready=false。四份新旧交付56+254文件分别Hash核对通过。

## 工程验收

- Contracts：37 passed；Builder：378 passed、5 skipped；Evaluator：1576 passed、9 skipped；根 CLI：61 passed。跳过项为可选依赖、Docker或真实付费模型测试；本次未启用它们。
- 独立 fresh clone 叠加当前工作树后，分别安装 Builder/Evaluator 并完成依赖检查；新增 Agent 测试20 passed，再次导出、生成、校验和执行，复现362通过、3失败、0未绑定。
- 验证 Builder 环境未安装 mini_agent 仍可导入共享校验；历史冻结交付校验通过。386个相关源码文件与验收 checkout 逐字节一致。
- 当前产物 `readiness check` 无身份过期或证据完整性错误；唯一整体阻塞仍为实际失败和blocked义务。新旧交付字节和历史请求Hash保持不变。
- 验收日志与独立产物保留在 `tmp/agent97/acceptance-logs/`、`tmp/agent97/artifacts/`；临时克隆和虚拟环境已清理。
