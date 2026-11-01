# file-tools-v1 数据集勘误

## FTV1-E001：Markdown 标题内部空格的处理有歧义

状态：在正式运行后的结果审查中发现；记录缺陷并建议下一版修正。冻结的 `file-tools-v1` 任务、Oracle、Hash 和本次成绩均未改动。

原题描述为：“读取 input.txt 的一级 Markdown 标题，去掉 # 和空格。最后一条回复包含 RESULT=<答案>，不写文件。”

“去掉 # 和空格”可以理解为去掉 Markdown 标记及分隔空格，也可以理解为同时删除标题正文中的全部空格。Oracle 只接受前一种解释。因此 Agent 选择后一种解释时，不能将冻结规则下的 FAIL 有把握地归因于能力不足。

影响范围是 **整个 `read_search/markdown_heading` 家族**，不是仅两条失败记录。三个任务均位于 holdout，且提示文案相同：

| 任务 ID | 原始一级标题 | 冻结 Oracle marker | baseline 3 次 | tool-aware 3 次 |
| --- | --- | --- | --- | --- |
| `file-tools-v1/read_search/markdown_heading/001` | `# Release 1` | `RESULT=Release 1` | PASS / PASS / PASS | PASS / PASS / FAIL |
| `file-tools-v1/read_search/markdown_heading/002` | `# Release 2` | `RESULT=Release 2` | PASS / PASS / PASS | PASS / FAIL / PASS |
| `file-tools-v1/read_search/markdown_heading/003` | `# Release 3` | `RESULT=Release 3` | PASS / PASS / PASS | PASS / PASS / PASS |

候选 `/001` 第 3 次的原始回答摘录是 `去掉 # 和空格后为“Release1”。`，输出 `RESULT=Release1`；`/002` 第 2 次对应输出 `RESULT=Release2`。文件未被改动，失败来自回答与 marker 不一致。样本来源和精确原文见 [analysis.json](../../reports/file-tools-v1/analysis.json) 的 `representative_cases` 与 `dataset_errata`。

建议下一版文案：

> 读取 input.txt 的一级 Markdown 标题。只移除行首 Markdown 标记 # 及其后用于分隔标题的空格，完整保留标题正文内部的空格。最后一条回复包含 RESULT=<标题正文>，不写文件。

该修正应覆盖家族全部任务，经人工检查后发布新的数据集版本与 Hash，并重新执行未来实验；不能把本次输出套入新规则，生成看似同一次实验的改写成绩。当前还应在作品集中明确：两个候选回答失败受题目歧义影响，不能直接计为已证实的能力退化。

## 对称排除的敏感性分析

只作事后诊断：从 **两组** 同时移除该家族全部 3 个任务及全部 3 次重复，各排除 9 条，包括通过和失败记录；其余任务、结果、评分不变。不是只排除候选失败项，也不把失败改判通过。

| 统计范围 | baseline | tool-aware | 候选减基线 |
| --- | ---: | ---: | ---: |
| 原始全部（正式结果） | 820/900，91.11% | 799/900，88.78% | -2.33 个百分点 |
| 排除家族后的全部（诊断） | 811/891，91.02% | 792/891，88.89% | -2.13 个百分点 |
| 原始 holdout（正式结果） | 171/180，95.00% | 175/180，97.22% | +2.22 个百分点 |
| 排除家族后的 holdout（诊断） | 162/171，94.74% | 168/171，98.25% | +3.51 个百分点 |

dev 不含该家族，保持 baseline 649/720、候选 624/720。排除后共 297 个任务，候选总体仍低于基线。因此题目歧义会影响部分失败解释和数值，但不能解释全部差距。本分析也不能证明候选对新任务的提升：这些 holdout 已经被审阅，后续据此调优需要新的未查看保留集。

## 冻结来源

任务文件 `data/benchmarks/file-tools-v1/tasks.jsonl` 的 SHA-256 为 `5b3a4feb3f82ba9a6b2c2eeebc9904f0fbb19069cdf46087bfbaa4fb35fe666f`。

两组原始 `results.json` 的 SHA-256 分别为 `edda7834859907a80339ebeef043c306601e1bf906c91b14253b52506af4f722`（baseline）和 `2b6f3d220e3565efff37c27122b80e6aefd4055e56ff8dc163cdf16d20bbe7ad`（tool-aware）。逐组分母、排除 ID、计算结果及来源路径收录于 [analysis.json](../../reports/file-tools-v1/analysis.json)。
