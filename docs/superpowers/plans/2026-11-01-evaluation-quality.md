# 评测质量补齐 Implementation Plan

> **For agentic workers:** 使用 superpowers:subagent-driven-development。用户已授权自行补齐，按文件所有权并行工作，由协调者统一集成、验证与提交。

**Goal:** 补齐重复调用诊断、校准交付与当前指标规格，并形成离线证据记录。

**Architecture:** 新诊断消费保存的 observation，加入 DeepEval 指标结果；现有正式 verdict 规则保持。校准输出和标注页消费已保存评分，人工字段保持独立。所有新报告与历史资产分离。

**Tech Stack:** Python 3.11、DeepEval BaseMetric、pytest、静态 HTML/JSON/Markdown。

**Spec:** `docs/superpowers/specs/2026-11-01-evaluation-quality-design.md`

## Global Constraints

- 只在本仓库工作；不修改冻结数据和历史结果。
- 不调用真实模型或托管服务，不写入凭据。
- Oracle 不进入执行输入；未知不记零，诊断不覆盖正式结论。
- 人工标签不得由模型代填；代理不暂存、不提交。
- 中文维护说明文档。

## Review Focus

- 错误重试与正常验证性读取不能冒充确定的冗余失败。
- 不完整轨迹、缺失/冲突错误状态或快照不能得到“没有重复”的结论。
- 标注页不泄露 Judge 预测，HTML 内容与导入字段必须安全转义。
- 校准分组分母与空标签、缺失 Judge 分数保持一致。
- 旧报告与新评分身份分开；复评分不增加执行数量。

## Task 1: 重复调用候选诊断

**Files:** 新增 `benchmark/repetition.py`、`tests/benchmark/test_repetition.py`。
**Interfaces:** `score_repetition(task: dict, observation: dict) -> list[dict]`；输出既有指标记录形状，`formal=False`，含 `classification`、`event_id`、`evidence_ids`、`reason`、版本。无工具时记录 NOT_APPLICABLE；证据不足 MISSING。正式集成由协调者完成。

- [x] 先写失败测试，覆盖同状态重复、错误重试、状态变化、跨轮、缺失证据、无调用和实际主流程 verdict 不变。
- [x] 实现严格范围的文件状态诊断与 DeepEval 指标封装，运行针对性测试。

## Task 2: 校准工具与离线标注

**Files:** 修改 `benchmark/judge_calibration.py` 及其测试；新增 `benchmark/calibration_reporting.py` 及测试。
**Interfaces:** 保留 `compare_human_labels` API，新增分维度统计、混淆矩阵与差异引用。新增 `render_annotation_html(worksheet: dict) -> str` 和 `render_calibration_report(result: dict) -> str`。CLI 接入由协调者负责。

- [x] 先写失败测试验证不均衡标签、空标签、缺 Judge 分数、HTML 转义、盲标与导出。
- [x] 实现按维度统计与可编辑离线标注页，导出原 record_id 与人工来源；空标签状态明确。
- [x] 针对性测试通过，报告具体接口。

## Task 3: 当前规格与校准操作指南

**Files:** 新增 `docs/benchmark/metric-specification.md`、`docs/benchmark/judge-annotation-guide.md`。

- [x] 依据当前代码整理所有主指标的公式、分母、粒度、范围、缺失处理和版本。
- [x] 每个 Judge 维度补四档具体示例，标注为机器编写的说明示例、未获人工审定。
- [x] 明确试标、分歧复核、阈值探索、独立留出验证和验收记录规则。

## Task 4: 集成与证据交付

**Files:** 协调者负责 `metrics.py`、`runner.py`、`cli.py`、导航、验收脚本和新报告目录。

- [x] 接入诊断并更新评分身份版本与源码 Hash 清单；补 CLI 标注页/报告输出与测试。
- [x] 用已有轨迹生成新的质量报告和空白标注页，保存来源 Hash；复用现有严格同口径 v1 对比，明确 v2 未新增 A/B。
- [x] 检查实现与规格一致，做独立审查、包回归、集成与冻结资产校验。
- [ ] 全新本地克隆安装与离线 Demo，记录通过项和未完成的人工验收。
