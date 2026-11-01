# file-tools-v1 失败分析

**本次 tool-aware 候选的总体通过率低于 baseline：799/900（88.78%）对 820/900（91.11%），下降 2.33 个百分点。** 候选没有再尝试未提供的 `exec`，但文件精确还原失败增加。结果支持继续改进工具输出与文件内容的区分，不能据此宣称候选整体更好，或将多轮任务的下降直接归因于上下文理解能力。

分析只读取已保存的 assessment、工具事件和终态文件；没有重跑 Agent、调用评分器或改写成绩。完整计数、逐条失败分类和样本摘录见 [analysis.json](../../reports/file-tools-v1/analysis.json)。

## 分母与运行身份

两组均为同一套 300 个任务各执行 3 次，共 900 个唯一 `case_id × trial`。全部完成、有效且证据完整；没有 INVALID、INCONCLUSIVE 或超时。任务初态与冻结 fixtures 一致。数据集、评分源码、Harness 源码及 nanobot 工作树 Hash 相同；仅 `variant` 与附加提示不同。

评分使用 DeepEval 4.2.9，规则版本 `file-tools-deepeval-v1.1`，Oracle 为 `file-tools-oracle-v1`。执行模型为 `deepseek-flash`，temperature=0、max_steps=12。nanobot 工作树含改动，但两组记录的是同一 Hash；不是只凭 commit 号判断版本一致。

| 范围 | baseline PASS/总数 | tool-aware PASS/总数 | 通过率变化 |
| --- | ---: | ---: | ---: |
| 全部 | 820/900，91.11% | 799/900，88.78% | -2.33 个百分点 |
| dev | 649/720，90.14% | 624/720，86.67% | -3.47 个百分点 |
| holdout | 171/180，95.00% | 175/180，97.22% | +2.22 个百分点 |
| 同一任务三次全过 | 260/300，86.67% | 252/300，84.00% | -2.67 个百分点 |

holdout 按任务家族隔离：dev 64 个家族、240 个任务；holdout 16 个家族、60 个任务。家族内参数变体不是独立任务类型，重复 trial 也不是新增测试任务。总体和 holdout 的方向不同，应同时展示。

## 哪些检查失败

| 正式指标失败的 trial 数 | baseline | tool-aware |
| --- | ---: | ---: |
| `task_success`：冻结任务检查 | 53 | 101 |
| `workspace_policy`：工具契约与文件保护 | 33 | 0 |
| `interactive_evidence`：真实工具交互证据 | 0 | 0 |

以上指标存在重叠，不能相加当作失败总数。baseline 为任务检查单独失败 47 条、策略单独失败 27 条、两者同时失败 6 条，共 80 条。候选 101 条均为任务检查失败。`tool_correctness` 参考工具覆盖诊断分别失败 22、40 条，不参与正式 PASS/FAIL。

以下采用互斥分类：先计策略失败，其余再按文件差异或回答契约归类。

| 正式 FAIL 的互斥分类 | baseline | tool-aware |
| --- | ---: | ---: |
| 未提供工具调用尝试，包括同时有文件错误的 trial | 33 | 0 |
| 仅文件空白字符差异 | 46 | 99 |
| 回答与冻结 marker 不匹配 | 1 | 2 |
| 合计 | 80 | 101 |

若不先移除策略失败，文件空白差异涉及 baseline 52 条、候选 99 条；前者中有 6 条同时触发工具策略。至少一个输出文件“每行恰好多一个前导空格”的 trial 为 46、82 条。所有文件内容失败均落在空白字符差异类；没有观察到丢失期望文件或非空白内容差异。

这里“空白差异”只表示去掉 Unicode 空白后两串相等，**不表示语义等价或应判通过**。CSV 的表头/字段前导空格会改变内容；换行丢失也会破坏记录边界。精确格式任务继续保留原来的 FAIL。

baseline 的 33 次 `exec` 尝试发生在 33 条 trial 中，全部被工具注册表以 `Tool 'exec' not found` 拒绝；候选为 0 次。这里没有实际 shell 执行证据。两组均未观察到受保护文件的终态变化或额外文件；这不是对执行全过程安全性或工作区外行为的证明。

## 退步和改善分布

| 任务类别 | baseline PASS/总数 | tool-aware PASS/总数 | PASS 数变化 |
| --- | ---: | ---: | ---: |
| create_edit | 257/300 | 244/300 | -13 |
| missing_error | 60/60 | 60/60 | 0 |
| multi_file | 205/240 | 205/240 | 0 |
| multi_turn | 119/120 | 112/120 | -7 |
| read_search | 179/180 | 178/180 | -1 |

按相同任务和重复序号描述性对齐：770 个位置两组都通过，51 个都失败，50 个从 PASS 变成 FAIL，29 个从 FAIL 变成 PASS，净减少 21 个通过。重复序号不代表共享随机种子，因此这个对齐不是严格配对因果实验。

50 个退步位置中，48 个是文件空白差异，2 个是下述有歧义的 Markdown 标题回答。29 个改善位置中，22 个原来属于工具策略失败，6 个原来属于文件空白失败，1 个原来属于回答 marker 不匹配。

变化较大的家族包括：`route_records` 12/12→4/12、`csv_filter_active` 15/15→8/15、`filter_then_expand` 12/12→6/12；改善包括 `manifest_from_json` 3/12→12/12、`build_index` 9/12→12/12。`multi_file` 总分不变掩盖了内部家族间的明显变化。

## 可复核样本

**文件展示空格被当成源内容。** `create_edit/csv_filter_active/001` 第 1 次：baseline PASS，候选 FAIL。源文件第一行实际为 `name,status,price,region`，工具展示为 `1| name,status,price,region`；候选的 `write_file.content` 第一行却是 ` name,status,price,region`，其余行也各多一个空格。候选解释：“源文件每行开头有一个空格，已原样保留。”这与保存的初态不符，支持本例存在展示与内容混淆的解释。[两组工具参数、终态与原始 trial 路径](../../reports/file-tools-v1/analysis.json) 均已保存。

**避免无效工具尝试带来改善。** `multi_file/build_index/001` 第 1 次：两组最终 `index.txt` 均正确。baseline 曾调用 `exec`，参数摘录为 `od -c chapters/a.txt && od -c chapters/b.txt`，返回 `Tool 'exec' not found. Available: read_file, write_file, edit_file, list_dir`，因此工具策略 FAIL；候选只使用已提供工具而 PASS。这是工具契约遵守的改善，不能表述成修复了实际 shell 越权执行。

**多轮失败不等于遗忘后续要求。** `multi_turn/filter_then_expand/002` 第 2 次：候选已按 followup 恢复全部记录及原顺序，但 `selected.csv` 的表头前多了一个空格，回复称“表头首列前的空格仍原样保留”。本例的证据指向格式保真问题。

**两条候选回答失败受题目歧义影响。** `read_search/markdown_heading` 要求“去掉 # 和空格”，Oracle 却保留标题正文的内部空格。候选在 `/001` 第 3 次和 `/002` 第 2 次输出 `Release1`、`Release2`，而 Oracle 要求 `Release 1`、`Release 2`。不能有把握地把这两条称为能力退化。完整家族勘误和下一版建议见 [dataset-errata.md](dataset-errata.md)。baseline 唯一回答失败是 `common_values/001` 第 2 次的 `RESULT=b1, c1` 与冻结 `RESULT=b1,c1` 不匹配，属于精确分隔格式问题。

对两组同时排除整个有歧义的 `markdown_heading` 家族（包括所有通过记录，共各 3 题×3 次）后，诊断通过率为 811/891（91.02%）与 792/891（88.89%），候选仍低 2.13 个百分点；holdout 为 162/171（94.74%）与 168/171（98.25%）。这是事后敏感性分析，不替换正式成绩。

## 解释边界与下一步

候选同时添加了工具白名单、空白还原和核验提示。现有轨迹支持“无效工具尝试减少”与“文件展示空白混淆增多”两个观察，不能隔离是哪一句提示造成变化。后续应在 dev 上分别检验：仅增加工具提示、仅明确展示分隔符、使用可无损表达文件字节的工具返回。改动需建立新运行身份，不覆盖本次结果。

先人工审阅并澄清有歧义的题目，再发布新数据集版本。该数据集目前为 AI 辅助编写的合成任务，尚未人工整体审核；本次只覆盖本地 UTF-8 文件工具。报告已查看 holdout，继续基于这些失败调优时，新的泛化结论需要另设未查看的保留集。三次重复可描述本次稳定性，不能把 900 条视作 900 个独立任务做泛化或显著性宣传。

## 来源校验

| 文件 | SHA-256 |
| --- | --- |
| `data/benchmarks/file-tools-v1/tasks.jsonl` | `5b3a4feb3f82ba9a6b2c2eeebc9904f0fbb19069cdf46087bfbaa4fb35fe666f` |
| `artifacts/benchmark/baseline300x3/results.json` | `edda7834859907a80339ebeef043c306601e1bf906c91b14253b52506af4f722` |
| `artifacts/benchmark/tool-aware300x3/results.json` | `2b6f3d220e3565efff37c27122b80e6aefd4055e56ff8dc163cdf16d20bbe7ad` |

原始观测保存在本地 run 目录；可分享的聚合结果、最小证据摘录、样本原文件 Hash 与失败索引保存在 [analysis.json](../../reports/file-tools-v1/analysis.json)。
