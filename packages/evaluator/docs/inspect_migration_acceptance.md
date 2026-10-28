# Inspect AI 迁移验收记录

验收日期：2026-10-15。结论：本次约定的本地源码迁移与现有能力适配完成；默认执行已切换到 Inspect AI，完整业务回归和独立审查通过。

## 交付内容

- Inspect AI 0.3.280 官方源码已 clone 到 `third_party/inspect_ai`，固定提交 `dfcb169e1cb170a8fbe2c37a0e3befc45c2c2b85`。
- 业务源码、SDK、数据、测试与文档迁入 `extensions/agent_evaluator`，根目录保留兼容符号链接；三个 Python 包均 editable 安装。
- 默认运行使用原生 Task/Solver/Scorer/epochs，通用匹配使用原生 Scorer，生成 .eval；独立证据、业务状态、有效性、治理等作为扩展。
- DeepEval 主运行管理器删除；可选 GEval Judge 和指标桥接保留，默认运行不依赖 DeepEval 可导入。
- 源码内容身份、报告复制和旧结果读取保持可追溯。新旧引擎结果不直接比较，需重新建立基线。

实施计划与自审决定见 [计划](superpowers/plans/2026-10-15-inspect-migration.md)，能力映射、安装和运行见 [主框架说明](inspect_engine.md)。

## 验证证据

| 验证 | 结果 |
| --- | --- |
| 迁移前完整回归 | 341 passed，2 paid skipped |
| 迁移后从权威扩展目录执行完整 pytest | **355 passed，2 skipped**，79.79 秒 |
| Ruff：src、tests、scripts | All checks passed |
| pip check | No broken requirements found |
| 本地真实导入路径 | Inspect、Evaluator、SDK 均指向 clone 内对应源码 |
| Inspect CLI | 版本 0.3.280 |
| 42 Case Suite CLI 校验 | valid: true |
| SQLite 状态型示例 | 8 Trial、2 epochs；4 PASS / 4 FAIL；全部 VALID / CLEANED |
| 原生 EvalLog | success，8 samples，所有 target 为空 |
| 独立原生 Inspect Task | 业务评测后仍可执行，包含于集成测试 |
| 独立审查禁用 DeepEval 导入 | 默认业务引擎 2 epochs 均 PASS，报告生成成功 |

两个跳过项为显式开关控制的 OpenAI 和 DeepSeek Judge 付费冒烟测试；没有调用付费模型。40 条 warning 主要来自保留的弃用入口及上游参数弃用提示，不存在测试失败。

SQLite 的 FAIL 是预期观察结果：当前原生 Agent 无法完成示例要求的跨轮确认后写入。评测器没有代替 Agent 补上这项能力，也没有把此类质量失败变成框架错误。

验证日志保存在外层工作区 `artifacts/inspect_migration_acceptance/verification/`；示例路径记录见其中 `inspect-example-paths.json`。复现命令：

```bash
# 外层工作区，使用当前已安装环境
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/python -m pip check
.venv/bin/python examples/stateful_gift.py --output-dir artifacts/inspect_demo
```

## 自审与独立审查修复

1. 搬迁后两个历史基准回放测试错误地从扩展目录寻找外层 artifacts。已将所需的原始报告纳入测试夹具，保留原报告内容，两个回放通过。
2. 原生比较适配曾将 params_match / tool_args_match 的 expected_subset 放宽为递归子集。独立审查提供了嵌套额外参数导致 FAIL 变 PASS 的反例。现恢复为仅投影顶层字段、嵌套值严格比较；两个反例先观察到失败，修复后相关 28 项通过，最终全量通过。

最终独立复核确认上述问题已关闭，审查范围内无遗留重要或严重问题。只读审查同时覆盖了真实 Solver 执行、私有 Oracle、清理失败阻断、原生日志复制、额外原生 Task 和 DeepEval 可选性。

## 交付边界与仓库状态

本机没有 Docker，未验证 Docker/Kubernetes；同步 Provider 不支持强制中断。Suite Judge Profile 等原先未完成入口未在本次新增，详见主框架文档。没有把这些能力宣称为本次验收通过。

代码保留在本地开发分支，尚未提交或推送，避免把既有未提交工作混入自动提交。Inspect clone 是独立 Git 仓库，根仓库符号链接不包含其文件内容；交接应同时备份该 clone 与扩展目录。本次原始源码备份为 `/tmp/agent-evaluator-before-source-migration.tar.gz`。凭据与虚拟环境未搬迁，历史 artifacts 未删除。
