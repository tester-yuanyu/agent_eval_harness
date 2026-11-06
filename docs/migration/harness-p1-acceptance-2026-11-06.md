# Harness P1 验收（2026-11-06）

本轮承接第一阶段 `c801d07`，落实用户本轮列出的 P1 三项。实现说明见 [Nanobot 双接入与停止策略](../benchmark/nanobot-components.md)。原默认 nanobot 原生 AgentLoop 子进程已经存在，因此只新增明确的 `NanobotRuntimeAdapter` 名称并保留 `NanobotAdapter` 同类 alias；新增组件 Provider 单独使用 `nanobot_component`，没有把 raw_model 改名冒充原生 Agent。

## 范围与决定

- NanobotComponentAdapter 使用可选 nanobot 源码中的 ContextBuilder、模板和工具参数规范化；模型走 Inspect，循环由 Harness 控制。组件是受限 profile：禁用个人 bootstrap、memory、skills、插件、原生工具和 tokenizer。此处没有搬入 worker 全局 setup。
- 每样本独立 ContextBuilder/临时目录；新进程导入、两样本并发、来源不符拒绝以及 config/logger/tokenizer/环境变量不变都有测试。纳入 native 源码 hash 与实际 prompt hash。
- TimeoutStop 对 loop 内异步调用显式取消；ErrorStop 可选限制连续可恢复工具错误，成功后清零。未配置错误预算时保留现有恢复行为。基础设施错误继续抛出，正式评分不改。
- 不修改冻结任务/Oracle/历史结果，不重新评测历史 nanobot 全量结果，不调用付费模型、不上传托管服务。测试中的 nanobot 是真实组件代码，模型为 Inspect mockllm。
- P2 动态用户模拟、全量 file-tools-v2 基线对比未做；旧路径保留。Docker 和真实模型新旧能力对照也未在本轮完成。

## 审查

执行了一次独立只读整体验收审查，零 Critical、零 Important、一项 Minor。Minor 指出 shielded cleanup 无法由 Inspect 同类 CancelScope 提供硬超时；已修正文档，明确清理依赖自身边界，不宣称外层硬中断。内置 snapshot 命令有 30 秒超时，组件 close 同步清理临时目录。

审查独立复验停止策略 11 项和 cancellation 1 项。审查范围之外的事项已确认保留边界：组件与完整 nanobot 能力等价性、P2、Docker 实测、既有 shielded cleanup 架构和同步 Python 阻塞抢占，均未冒充已验证。

## 已完成的验证

- P1 相关测试（独立可选组件环境，真实 nanobot 0.3.0 源码 + mockllm）：48 passed。
- Evaluator 全包：1,280 passed / 11 skipped，138 条上游/兼容弃用 warning。其中新增的 5 项可选 nanobot 测试已在独立组件环境全部通过；其余 6 项为 Docker 2 项、未携带的历史证据 2 项、付费 smoke 2 项。
- 根集成与 contracts：61 passed。
- 包级 Ruff、compileall、git diff --check 通过。
- 冻结参考资产：1,172 项通过；冻结任务、历史报告和 fixture 相对起点无 diff。
- 组件 CLI 示例：单任务正常结束，固定假回复的正式 verdict 为预期 FAIL；组件/原始模型脚本动作的 DeepEval 集成测试均为 PASS，Oracle 不进入执行消息。

全新克隆验收记录在交付前补齐。
