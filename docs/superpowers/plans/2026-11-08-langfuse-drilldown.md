# Langfuse 调试入口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans，当前会话连续执行。

**Goal:** 交付可验证的分类下钻、健康度卡片及同口径性能/用量趋势。
**Architecture:** 纯离线 explorer 产物保存汇总和精确 Trace 集合；可选 Langfuse 层生成筛选入口、汇总 Score、Widget 及回读收据。
**Tech Stack:** Python、现有 Langfuse SDK、静态 HTML。
**Spec:** docs/superpowers/specs/2026-11-08-langfuse-drilldown-design.md

## Global Constraints
- 不调用模型、不重评分、不改冻结文件；未知成本不补零。
- 缓存不得重复计入 token；延迟按 trial 根节点，不混入事件。
- 旧历史注释/观察记录保持不变；网络同步显式启用。

## Review Focus
- 分类重叠：每类按 trial 去重，不能把类别计数求和当总失败。
- 来源变化：结果/收据 Hash 不一致拒绝链接和同步。
- 缺失用量/费用：标未知，估算与实付分开。
- URL 筛选丢失：浏览器结果数及 ID 集合必须匹配。
- 重复同步：稳定 ID，不重复创建观察记录或正式评分。

## Tasks
- [x] 1. 新增 benchmark/report_explorer.py 与 test_report_explorer.py：先失败测试，后实现健康度、任务族/诊断精确集合、独立 HTML 调试入口；复用 report_usage/estimate_cost。
- [x] 2. 新增 benchmark/langfuse_explorer.py 与对应测试：先覆盖 URL 及查询口径、汇总 formal=false/幂等，再实现远端能力适配。扩展展示 CLI 与 Dashboard 布局；维护已登记 ID。
- [x] 3. 核验 Langfuse API 和浏览器中的四类失败、任务族及一个 Trace 模型/工具输入输出；核验卡片与趋势数据。
- [x] 4. 相关离线回归、核心无可选依赖导入、冻结 Hash/凭据扫描，更新文档与 HTML/ZIP 交付。

Ruling: 用户已明确执行方案，不重复请求设计或执行方式批准；当前仓库干净且任务延续既有分支，直接在该分支实施。

验收：95 项相关离线回归通过，最终修改涉及模块复跑 12 项通过；23 个新增 Widget 逐项查询核对，Dashboard 共 27 项，浏览器确认数字、趋势、精确 Score 分布与工具链 Trace。73 个冻结证据文件 Hash 未变，模型调用仍为 53 次。全包回归本次未重跑，既有子进程启动时限失败记录保留。
