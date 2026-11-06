# Benchmark M2 验收（2026-11-06）

M2 的代码、独立审查修复、本地整合与离线验收已交付。HTML 浏览器视觉抽查因本地文件 URL 被安全策略拒绝，明确未验证；没有绕过该限制。本批没有运行真实模型、上传 Langfuse 或填写人工标签，M3/M4 不在完成范围内。

## 交付范围

基线 `936c645`；实现提交 `845ac02`、`6405e5b`、`95b8d45`、`1e9b239`、`bc4e702`；独立审查修复 `ed50db2`，整合环境的旧 mock 修复 `f880faf`。产品代码已快进合入本地 `codex/tool-benchmark-deepeval`，没有推送远端。Environment、Harness 执行循环与现有正式 scorer 没有修改。

- **保存证据分析**：新增 `benchmark analyze`，生成独立 analysis.json/md/html/provenance.json。显式校验原始执行、正式复评和附加 Judge 来源链，不跟随记录中的路径或 URL；缺失计划 trial 保留 MISSING。复评与 Judge repeat 不构成新 Agent 执行。
- **失败归因与报告**：按结构化检查/错误定位 agent、infrastructure、scoring、unknown，保留版本与 JSON Pointer。PASS 中恢复成功的工具错误只记诊断。四层分母、未知字段、未审标签、失败证据与复现占位命令都可查看。
- **可靠性与效率**：comb(c,k)/comb(n,k) 的任务 micro / 任务族 macro；缺失或 INVALID 不筛掉，k>n 不填零。Agent/Judge/用户模拟器分别计算 token、费用、调用、输出长度和延迟，逐字段给计划 trial 与完整任务覆盖率。成功样本均值与总尝试/成功数分开。
- **独立注释**：新增 file-tools-v2@1.0.0 的 420 条 proposed，旧 tasks/manifest 不变。未能证明的结构特征和难度保留 unknown，正式桶仅使用 reviewed，当前全部显示未审/未标注。不可变版本登记绑定 dataset/content Hash，外部登记只能扩充、不能改写内置版本。
- **比较**：无 ExperimentSpec 可作探索性并列，来源总体独立。受控资格检查数据、评分、执行层、选择、环境、工具、提示词、生成配置及完整重复协议；历史缺项保持 descriptive_only。同一执行的不同复评分支为 scoring_only。

使用方法和字段定义见 [本地分析指南](../benchmark/local-analysis.md)。本批主要新增分析功能及资产，不将旧 runner/report/compare 改成新口径。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 第一次完整 Evaluator 回归 | 1,380 passed / 14 skipped |
| 审查修复阶段完整回归 | 1,393 passed / 14 skipped；随后补外部登记重绑回归，相关 56 项通过 |
| 最终整合后完整 Evaluator 回归 | **1,401 passed / 9 skipped**，281.77 秒 |
| 最终整合后根 CLI / contracts | **78 passed**，24.37 秒 |
| Builder 相关合同生成回归 | 9 passed |
| Evaluator Ruff / 新 contracts 四文件 Ruff / Git diff 检查 | 通过 |
| contracts 全目录 Ruff | 13 项既有问题，与 `936c645` 基线数量、规则一致；未夹带清理 |
| 冻结导入资产 | 1,172 项通过；新注释另经绑定与版本登记校验 |
| 新克隆独立 core 安装 / pip check | 通过；minimal_agent、nanobot、Langfuse 均未安装，核心分析导入成功 |
| 新克隆 M2 与历史兼容定向测试 | 109 passed |
| 新克隆根 CLI / contracts | 75 passed / 3 skipped：未安装独立 Builder 环境，根 validator 三项按条件跳过 |
| 新克隆离线交付 | v1/v2 各五条 reference demo；Inspect 报告、analyze 四份产物、420 条注释校验、ExternalProvider PASS/FAIL/INCONCLUSIVE、冻结校验通过；v2 分桶为 5 planned / 0 reviewed / 5 unlabeled |
| 新克隆可选 SDK 边界复核 | τ harness 20 passed / 12 skipped（未安装 Langfuse），含新增数字形 ID 回归 |
| wheel 打包 | annotation_versions.json 已包含在 Evaluator wheel 中 |
| HTML | 生成、内容、转义与无外部资源检查通过；浏览器视觉抽查未验证 |

各轮可选跳过涉及 nanobot / τ / Langfuse 环境、本地历史试点证据，以及明确禁止自动执行的付费 API smoke，最终数量以上表实际环境为准。没有通过放宽测试或修改冻结数据消除失败。

整合后首次全套为 1 failed / 1,398 passed / 9 skipped。失败来自既有 SavedLangfuse 测试替身把十六进制 ID `5347207e68077799` 解析为 JSON 科学计数法，导致实验项计数 2 而不是 3；生产保存的观察与评分全部匹配。新增两个固定 ID 复现先失败，再只让 mock 解码结构化 IO/metadata/usage，ID 保持字符串；τ harness 整文件 32 项通过后重跑整套。没有修改生产 Langfuse 导出、放宽 VERIFIED 判据或减少测试范围。

## 独立审查与裁决

一次独立只读审查得到 0 Critical、3 Important、1 Minor；四项均接受并修复，各有先红后绿的回归记录，没有延期的代码发现：

1. 缺 provenance 的派生记录不能清除顶层标记后冒充 execution；identity 与 trial 中残留的来源标记同样触发拒绝。
2. 用量归属统一识别 is_judge、owner、usage.owner、participant 等明确角色；冲突或未知归属拒绝，非 Agent 聚合费用不能覆盖 Agent 字段。
3. 空或缺少环境重置/随机性声明的重复协议不能获得 controlled 资格；有效协议也只是声明，不证明随机独立性或预登记时间。
4. 注释同版本不同内容即使换目录并重算 manifest Hash，也不能通过已登记版本校验。新建议版本默认 unregistered，正式使用需显式受信登记；登记内容也进入分析身份。

其他实施裁决：

- 统一 loader 仅分发到现有严格合同校验，不提前补 M1 中延期的通用 descriptor 抽象。
- AnalysisPolicy 在第一个分析消费者落地时加入共享 contracts；新注释模型不依赖 Agent SDK。
- reference 操作不是实际工具调用数或最短依赖图；因此首版难度 unknown，不为了填满表格推断能力。
- 正式失败的广义 task_success 不能证明具体原因；错误选择已有工具与调用不存在工具分开归类。
- 基线数据集不同时要求 `--comparison-dataset`；结果分栏，不拼接多个 run。
- 不把包注册要求做成后台可变全局状态；内置版本为打包数据，新版本由显式登记输入扩充。

## 证据位置与未覆盖项

开发与审查日志归档到 `.migration/benchmark-m2-worktree-logs/`；根整合测试为 `.migration/benchmark-m2-final-{evaluator,contracts-root,assets}.log`。新克隆为 `.migration/benchmark-m2-clean-20261106/`，独立 `.venvs/core`；安装和验收日志为 `.migration/benchmark-m2-install.log`、`.migration/benchmark-m2-clean-acceptance.log`、`.migration/benchmark-m2-clean-v2-acceptance.log`。离线产物在该克隆的 `artifacts/benchmark-m2-final/`，均为框架演示，不能当真实 Agent 成绩。

未覆盖：HTML 浏览器视觉抽查、真实 Docker / 可选 τ 环境、真实重复评测、人工 reviewed 标签、人工独立校准、托管看板与导出。前一项受本地浏览器策略限制；其余依赖可选环境或属于 M3/M4。本批没有修改既有约束文档、历史结果和冻结任务内容。
