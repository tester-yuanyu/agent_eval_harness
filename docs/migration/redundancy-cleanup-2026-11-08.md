# 冗余收敛与历史兼容验收（2026-11-08）

## 范围与实现

本轮按用户批准的保守收敛方案执行：减少重复维护，不改变已交付评测口径。未调用真实模型或托管服务，未重新评分历史运行。

- Judge 的失败请求审计集中到 `benchmark/scorers/judge_client.py::AuditedJudge`。保留 `_AuditedJudge` 导入和 `_AuditedNativeJudge` 名称、失败事件名称及未知用量；已收到响应但 JSON 校验失败时不重复记账。
- SDK 的 manifest 与 event envelope 校验集中到 `agent_trace_sdk/validation.py`。旧 JSONL 仍按记录容错；损坏原生日志仍整体拒绝，不能回退到旧文件或用内存补出成功。
- Evaluator 的 `canonical_value` 转发 contracts 现有实现，保持 Unicode、空白、类型、键排序、分隔符及非有限数拒绝行为。共享代码进入新的 Harness / Provider 评分身份，历史保存身份不改写。
- 历史结果回归发现既有报告诊断把 Judge 的纯文本输入当作 Agent 消息对象。补充类型边界，保留原始事件，只跳过不适用的 Agent 会话诊断；正式判定不变。

现有报告、Langfuse Explorer 与导航工作已有其他未提交改动，本轮仅修复上述独立兼容问题，不覆盖其他工作。重构不要求重跑历史评测；新源码产生新运行身份，不能混入旧运行恢复。

## 包、链路与入口的保留理由

| 范围 | 结论与边界 |
| --- | --- |
| 根 `agent_eval_suite` | 保留独立解释器调度、资产登记及源码管理；不将 Builder/Evaluator 运行时导入根包。 |
| `agent-trace-sdk` | Provider、mini benchmark 仍实际依赖；Inspect 承担存储，SDK 保留业务完整性和独立证据策略。不是可以直接删除的旧包。 |
| Builder | 保留候选生成、编译、审核与冻结流水线；专属固定任务脚本不是等价替代。维持独立环境，不合入 Evaluator。 |
| 旧 Suite / Inspect 评分 | 保留旧接口、数据和结果支持；DeepEval Provider 评分仍复用部分断言，不能整块删除。 |
| File Tools v1 | Demo 仍使用；冻结数据、历史结果与可执行兼容分别管理，不把版本号当作弃用依据。 |
| `quality-audit` | 离线同状态重复候选与错误重试取证；StepEfficiency 是模型语义诊断，不等价。 |
| τ / mini_agent | 保留可选领域与接入边界；是否停止支持属于后续产品范围决策，不是本轮死代码清理。 |
| 报告 | Inspect View 用于执行调试；离线报告用于领域分母、公开脱敏交付；Langfuse 展示保存结果。诊断、用量与费用已有公共实现，不再新增平行计算层。 |
| CLI / Make | `make` → 根 CLI → 包 CLI 为转发链。根脚本分别负责安装、跨环境回归与迁移基线字节校验，不合并成评测运行时。 |

## 静态审计

扫描根源码、脚本及四个包的 352 个 Python 文件，检查函数体重复和标识符引用，并人工核对动态调用候选。唯一仅出现一次的私有函数名 `_get_identity` 是 nanobot 的继承覆写，不删除。

保留的短重复：独立公开报告脚本的 Hash 编码（避免拉入 Evaluator 依赖）；Builder 配置与内部 IR 各自的类型前缀验证；contracts 列表/元组两类模型的局部 ID 验证。它们各约 8～10 行，当前引入公共抽象的收益有限。worker 事件创建也有相似结构，但文件工具限制、τ 脱敏和独立依赖边界不同，本轮保留。

静态检查不能证明动态 Python 代码绝无死路径。本轮结论是已确认的高收益重复得到合并，未发现可直接删除的大块无用途实现，不声称全仓零重复。

## 验收

执行记录保存在 Git 忽略的 `.migration/redundancy-20261108/`，包回归日志在 `artifacts/verification/`。测试环境清除凭据和付费 smoke 开关。

| 检查 | 结果 |
| --- | --- |
| Contracts / Builder / mini_agent / 根集成 | 分别 20 passed、353 passed / 5 skipped、323 passed / 1 skipped、58 passed。跳过项为可选依赖及付费 smoke。 |
| SDK | 无独立测试目录，纳入 Evaluator 的新旧证据消费者回归。 |
| 新克隆安装 | 本地 Git 新克隆叠加验收时的工作树源码；新建独立 `.venvs/core`，`setup.py --only core` 与 `pip check` 通过，没有复用原虚拟环境。 |
| 新克隆定向回归 | 51 passed，覆盖本轮公共实现、旧导入路径、来源身份与 Judge 报告边界。 |
| 新克隆 Demo / Report | 根 CLI 子进程调度完成 5 条离线参考任务，5 PASS，生成 Inspect View；不代表真实 Agent 成绩。 |
| 历史报告回读 | 9 组、2,623 条保存记录的临时副本生成 domain 报告；逐 trial verdict 汇总相符，副本及原始 `results.json` 字节不变。包括 v1 基线/候选、v2 模块/决策/链路/端到端、chain-judge、τ、mini_agent。复评/Judge 与执行有重叠，不能视为 2,623 次独立执行。 |
| 迁移基线 | `verify_assets.py`：1,172 个导入参考资产与 fixture 验证通过。 |
| 改前/改后字节比对 | 1,121 个跟踪数据、公开报告、fixture 和已有 `results.json` 的 Hash 未变。 |
| 本轮文件 lint / diff | Ruff 与 `git diff --check` 通过。全仓 F401/F811/F841 通过。 |

全目录完整 Ruff 首次报告 142 项 import 排序问题，其中本轮涉及的 4 项已修复；其余 138 项已通过 `git show HEAD` 核实原有代码同样存在。随后历史报告兼容修复涉及的文件又修复其中 1 项；没有全仓批量改格式。

Evaluator 全包运行结果：1,502 passed、9 skipped、2 failed，耗时 312.52 秒；失败项为 `test_repeated_diagnosis_has_one_summary_and_compact_trial_references` 和 `test_alias_counts_deduplicate_turns_and_split_pages_link_to_summary`。并行报告更新后，两个失败项复查为 2 passed，报告全组复查为 67 passed（含 Inspect 原生报告及本轮历史 Judge 输入回归）。没有把这组分阶段验证写成一次全包零失败。原有第三方弃用警告保留。

首次全包执行还遇到并行任务新增测试早于 `report_context.py` 落盘而收集失败；模块出现后重新执行得到上述完整结果。最终全目录 lint 仍含旧 import 排序问题，以及并行报告工作中的行长、测试局部变量问题，涉及 `report_context.py`、其测试与 `test_report_insights.py`；本轮不覆盖这些工作。

本轮业务源码新增 97 行、删除 155 行，净减少 58 行，测试与验收说明另计。结论为已确认的高收益重复收敛、必要兼容保留；全仓 lint 清零及所有可选能力退出不在本轮完成范围。

## 后续记录清理

用户随后授权删除无用记录与报告。清理 21 份已完成且无剩余引用的计划/设计文档（其中 20 份可查 Git 历史）；9 个旧验收 clone 仅保留日志、收据及 `artifacts/` 证据，删除重复源码和独立虚拟环境；本轮报告回读的 9 份临时结果副本经 Hash 比对后删除，保留 `history/verification.json`，中间失败日志与临时检查脚本一并收敛。删除文件的逻辑体积约 4.30 GiB。

真实评测结果、公开报告、冻结数据、迁移基线、未完成计划和当前开发环境保留。历史验收正文中的 clone 路径为当时的验证位置，已不代表可直接启动的现存环境。清理后重新校验引用、数据/公开报告字节及迁移基线；删除清单位于 `.migration/cleanup-20261108.json`。

## 推送前整体验证

报告相关改动整合后，重新运行 `python3 scripts/test_all.py`：Contracts 20 passed、Builder 353 passed / 5 skipped、mini_agent 323 passed / 1 skipped、Evaluator 1,505 passed / 9 skipped、根集成 58 passed，总计 2,259 passed / 15 skipped，无失败。跳过项为可选依赖及付费 smoke，测试未调用真实模型；第三方弃用警告保留。重新校验 1,172 个参考资产通过，改动 Python 文件的 Ruff F/E9 检查与 `git diff --check` 通过。提交前移除报告测试中的未使用局部变量，修复后的文件已包含在本次全量回归内。日志位于 `.migration/push-verification-20261108.log`。
