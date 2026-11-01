# 评测质量补齐验收记录

日期：2026-11-01。实现提交：`b4ca725e9a67963f908dbc9596bc57e24bb8b29d`。用户授权自行补齐，范围为当前 monorepo；没有真实模型请求、托管服务上传或人工标签代填。

## 交付与边界

- `tool_nonrepetition` 接入当前 DeepEval 评分，主评分身份更新为 `file-tools-deepeval-v2.2`，诊断源码参与身份 Hash。该指标只发现同轮、同参数、同文件状态的重复候选；不判断必要性，不改变正式 verdict。证据不足保留空值，诊断异常不清空正式分数。
- 校准工具增加逐维度统计、混淆矩阵、误放/误杀分母、差异证据和来源 Hash。离线盲标页提供 36 条空白记录；不显示 Judge 预测，导出要求标注者身份、理由与独立性声明。声明仍须人工审核。
- [指标规格](../benchmark/metric-specification.md)统一公式、粒度、分母、适用范围、缺失处理和身份规则；[人工指南](../benchmark/judge-annotation-guide.md)提供三维 rubric、12 个机器编写且未经人工审定的分档示例，以及试标、复核和独立留出验证步骤。
- [质量报告](../../reports/evaluation-quality-v1/README.md)读取已有 480 次 chain/E2E 执行，得到 2,166 条已评分记录、1 条重复候选、3 条缺证据；26 条不适用。保存的同口径 v1 配置对比保留 29 次改善、50 次退化和失败引用，不代表新增 v2 A/B。

## 回归、审查与冻结资产

`python3 scripts/test_all.py`：全部测试组退出码 0，共 **1,689 passed、8 skipped**。

| 组 | 通过 | 跳过 |
| --- | ---: | ---: |
| contracts | 1 | 0 |
| builder | 353 | 5 |
| agent | 323 | 1 |
| evaluator | 956 | 2 |
| integration | 56 | 0 |

SDK 无独立测试目录，由消费者测试覆盖。5 项跳过来自 Builder 未安装的可选 DeepEval 依赖，3 项为禁止默认运行的付费模型 smoke。执行器清理凭据与 smoke 开关，并关闭 DeepEval 遥测。

`python3 scripts/verify_assets.py` 校验 **1,172** 项冻结资产通过。7 份历史执行、Judge、样本和汇总来源 Hash 均未变化；对最终代码重跑离线审计，生成的 `summary.json` 和 `repetition-records.jsonl` 与交付内容逐字节一致。原始执行数量和正式评分没有被重写。

本次修改的 Python 文件全部通过 Ruff。全 evaluator Ruff 仍报告 **22 项既有 `I001`**；逐文件与修改前 HEAD 比对，数量和类型一致，没有扩改无关文件。因此不能宣称全仓 lint 已清零。

独立代码审查发现的两处问题已先用测试复现再修复：对比输入逐条绑定真实执行身份；诊断异常与正式评分隔离。复审通过。文档及报告另经一致性核对。浏览器检查确认页面可读，36 条分数和标注者为空、独立性复选框均未选中；导出脚本由 Node 执行测试覆盖。

## 全新克隆验收

验收提交为 `b4ca725`，在 `artifacts/evaluation-quality-v1/clean-clone` 的独立 `.venvs/core` 中执行，Python 3.11.4，未复用原工作树环境。`scripts/setup.py --only core` 使用原锁文件安装成功，`pip check` 通过；确认未安装 `mini_agent` 时核心及新诊断模块仍可导入。

v1 离线 reference Demo **5/5 PASS**，HTML 报告生成成功；新 `calibration-page` 生成 **36 条记录、144 个空白人工控件**。新 CLI、重复诊断与校准测试 **94 passed**。该 Demo 是安装演示，不是新增真实 Agent 评测；验收克隆的跟踪文件保持干净。

初次安装遇到系统代理 TLS 超时，随后缓存安装因缺少锁定版本失败；最终通过官方 PyPI 直连完成，未放宽任何约束。失败与成功日志均保留。完整命令及日志 Hash 位于 `artifacts/evaluation-quality-v1/clean-clone-verification.json`，主要结果、原记录 Hash、产物 Hash 已并入公开机器记录。

## 可复查记录与剩余验收

[机器验证记录](../../reports/evaluation-quality-v1/verification.json)保存命令、测试计数、日志 Hash、来源 Hash 和检查边界；[校准状态](../../reports/evaluation-quality-v1/calibration-status.md)仍为等待独立人工标签。

本次只完成可独立交付的代码、规格与离线证据。人工标签为 0，Judge 与人工一致性和误判率仍未知；候选阈值未经独立留出验证，不提升为正式门槛。当前 36 条样本属于开发集，既有 holdout 已被使用，不能冒充新的未见集。新增 v2 A/B、人工审定及可靠货币成本证据仍需另行完成。
