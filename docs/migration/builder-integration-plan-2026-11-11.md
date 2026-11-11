# Builder P0 产物接入与 P1 小范围增强

用户明确顺序：先接现有 Builder 产物，再做 P1。复用已批准的 P0 门槛，不做 P2。

## P0 设计与验收

- 为 `readiness run/check/freeze` 增加 `--delivery`，与现有 `--dataset` 互斥。
- Builder 静态核验 generate-full 交付后，绑定 manifest、所有交付文件 Hash、完整行为案例集合及原始 case 位置。
- 执行适配限定 query_user_info/invoke_tool 的具体 fixture_setup；从 records 初始化现有 MiniAgent FixtureEnvironment，通过原生 Harness 调用真实 registry。读取现有 equals/schema_valid 断言，不猜预期。
- 没有执行适配或 fixture 的案例保持未绑定。报告分母为全部行为案例；contract_check 与 blocked_obligation 独立统计，局部通过不能发布整包。
- 运行器显式接入可信 MiniAgent 源码目录，按需加载可选依赖；运行身份另绑实际 MiniAgent 与 fixture 代码。reference 不接收 oracle/result_branch 预期标记。
- 检查交付变化、固定集合、执行输入和来源 Hash、跨环境断言、失败 oracle、review Hash、不可变输出。旧冻结字节不改。

## P1 设计与验收（P0 验证后）

- full_tool_fixture collector 从全文件广播来源改为按事实类别/模块的明确文件映射。
- 新增只读来源审计，区分输入未提供、仅 runtime 存在、仅 candidate 存在、内容冲突、缺来源；不将声明缺失直接断言为能力不存在。
- 保留 FactDocument 和 reconcile 的支持状态及硬错误行为；报告放在 bundle 外。

## 执行清单

- [x] P0 失败测试 → 协议、交付适配、实际 fixture Harness → 正反演示。
- [x] P1 失败测试 → 精细来源、审计报告 → bundle 不变验证。
- [x] 相关包回归、独立审查、全新克隆安装与离线验收。

## 记录

当前 checkout 有 P0 未提交改动，本次继续其上开发；不提交其他工作。

验收详情见 [P0/P1 交付说明](builder-integration-2026-11-11.md)。额外修复 python -m CLI 入口，并把 P1 记录接入原 full_tool_fixture export；保留原业务 gap 协议。
