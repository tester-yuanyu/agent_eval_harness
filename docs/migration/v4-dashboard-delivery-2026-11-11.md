# v4 统计看板补齐与正式交付接线

用户明确授权基于保存的 v4 结果补齐 Langfuse 云端看板并接入正式交付，不重跑 Agent、规则或有效 G-Eval。复用原 presentation / explorer 模板与确定性 ID，不另建绘图框架。当前工作树含历史改动，原地工作不混合提交。

## 执行顺序与验收

1. 共用 report_evaluation 统计：模型/确定性通过率，Agent/Judge 请求、已知 Token 与未知数，三个 G-Eval 维度及适用分母，预期失败说明；保存的延迟按执行组拆分。
2. 复用原 summary_payload / explorer_widgets / arrange_widgets，v4 新增统计区，不把单次基线画成趋势，不把正式规则与 G-Eval 混算。保留旧模板默认行为。
3. 新增展示交付编排，复用 sync_diagnostics / create_dashboard / sync_explorer；原始结果及回执只读，展示在独立目录，记录 data_status / dashboard_status / dashboard_url。正式 sync 自动接看板，另有只补看板入口，已验证数据无需再次上传。
4. 离线测试覆盖统计口径、幂等恢复、profile目的地及完整交付验收；部署前一次独立审查。云端创建/回读数据和布局，在线检查图表，返回 Dashboard 链接。

## 约束与决策

- 本次云端写入仅为展示注释、汇总 Score 与 Dashboard/Widget；不运行模型、不重评、不修改原始 Trace 或正式 Score。
- 已有主集30条与v4 365条不作为同口径趋势。
- 看板更新失败不能将整个交付标为完成；数据验证与看板验证分开。
- 允许新增派生展示目录；原冻结结果/评分/旧看板资产字节不改。

## 已落地的入口与统计口径

正式 `mini_agent_v4_benchmark.py sync --profile ...` 及通用 `langfuse_delivery` CLI 默认包含看板交付；Python `sync_run` 保留旧默认行为，显式传 `dashboard=True` 启用。通用 CLI 的 `--data-only` 仅同步数据，不代表完整展示交付。数据验证成功、看板布局成功、44 项展示汇总的云端 Metrics 聚合值与唯一数量均验证成功后，才标记 `delivery_status=COMPLETE`。只有验证完成的看板链接进入报告。

这次只补看板的命令如下，可用相同参数续传。展示记录保存在独立目录；已存在的注释、汇总 Score、Widget 和 Dashboard 根据确定性身份复用，不调用执行器或 Judge。

```bash
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py dashboard \
  --source artifacts/mini-agent/v4-deepseek-recovery-20261111/judged \
  --output artifacts/mini-agent/v4-deepseek-dashboard-20261111 \
  --profile configs/benchmark/mini-agent-langfuse-cloud.json
```

| 指标 | 保存结果与看板口径 |
| --- | --- |
| 全部案例 | 365 条；343 PASS、22 FAIL，仅作总量背景 |
| 真实模型案例 | 54/76，通过率 71.1% |
| 确定性检查 | 289/289，通过率 100%，不代表模型能力 |
| G-Eval | 196 项 SCORED，930 项 NOT_APPLICABLE，0 项 ERROR/MISSING；评分项不是独立案例 |
| 三个诊断维度 | 动作合理性 107 项、故障处理合理性 13 项、回复事实依据 76 项；分别展示均值和适用分母 |
| Agent 请求与用量 | 107 次，82,092 已知 Token，0 次用量未知 |
| Judge 请求与用量 | 201 次，318,651 已知 Token，5 次用量未知；包括保存的失败请求 |
| 耗时 | 模型与确定性组各自的执行均值/P95，不混入 Judge 或上传耗时 |

故障处理的 13 条案例注入了故障且规则期望 FAILED，因此 G-Eval 均值不是恢复成功率；三个维度仍是未经人工校准的诊断，不能覆盖正式规则 FAIL。单轮结果不显示趋势，旧 30 条代表集也不混入 v4 趋势。未知 Token 不补零，未提供可信定价时不生成实际费用。

## 本地验收

- 相关测试 46 项通过；独立审查后补齐显式目的地贯穿与聚合回读，相关 7 项通过。
- Evaluator 包回归：1,651 passed、9 skipped；付费/联网 smoke 保持关闭。
- 全新克隆叠加当前源码后完成 core + Langfuse 安装与依赖检查；无 mini_agent 安装时核心导入正常，离线演示分别输出 PASS、FAIL、INCONCLUSIVE。
- 本次改动的 Evaluator 文件 Ruff 通过；根脚本的 3 条既有 Ruff 提示（EXE001、两条 C408）与任务开始前基线一致。
- 原始 v4 执行/评分、旧代表集结果和冻结 v4 数据集共 4,293 个文件逐字节 Hash 核对无变化。
- 云端实际暴露旧模板的大分类查询问题：233 条 Schema 案例名称拼接使 GET URL 过长，返回 414。分类卡片改为既有 `metadata.category` + `results_sha256` + `AGENT` 筛选，仍分页核对完整根观察 ID 集合，不修改原始 Trace。新增长名称用例先复现失败再通过；22 项相关测试、全新克隆内 8 项看板测试通过，独立复核无 P0/P1。

## 云端最终交付

[本轮 v4 统计看板](https://cloud.langfuse.com/project/cmvgd40xe02ecad0en362z7wd/dashboards/cmwc855fs03haad0j04mzouem?dateRange=1794398296118-1794400912877) 固定了本轮时间范围，避免浏览器沿用上次日期而显示空图。

- 最终 `data_status=VERIFIED`、`dashboard_status=VERIFIED`、`delivery_status=COMPLETE`。
- 375 条非正式展示注释、44 项展示汇总均已回读；44 项 Metrics 实际聚合值及每项唯一数量核验通过。
- 29 个可见 Widget，布局回读一致；分类下钻完整根观察集合核验通过，包括 233 条 Schema。
- 网页实测显示 365 条总量、71.053/100 的分层通过率、196/930/0 的 G-Eval 状态、Agent/Judge 请求及用量、分组耗时和分类图表，无空白指标。
- 原始结果保留在 `artifacts/mini-agent/v4-deepseek-recovery-20261111/judged`；新报告和交付证据在 `artifacts/mini-agent/v4-deepseek-dashboard-20261111`，`report.html` 已包含验证后的看板链接。
- 续传过程中只读校验与补齐展示配置；新增 Agent 执行 0、新增 Judge 请求 0。未再次执行、评分或上传原始结果。
