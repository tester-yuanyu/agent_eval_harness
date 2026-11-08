# 离线报告与 Langfuse 联动

HTML 负责当前运行的整体结论、模式摘要、条件建议及完整离线证据。Langfuse 提供逐次模型/工具调用浏览、已保存正式评分和展示面板。Inspect 负责执行与日志，DeepEval 负责正式评分；诊断不会改变历史判定，也不会修正被测 Agent 的参数。

## 共享诊断

`report_diagnostics.py` 从保存结果与 Hash 绑定的任务、参考契约生成 `diagnostics.json`，同时归档到 `report-diagnostics/{analysis_id}.json`。文件记录源结果 Hash、规则版本及代码 Hash、可选配置版本、证据、问题编号和分组。HTML 与 Langfuse 使用同一份产物；规则更新产生新的解释版本，不改写旧记录。

规则名称和中文文案属于可维护的诊断规则。受影响用例、计数、字段偏差和行动建议由证据驱动；并非依赖另一轮模型自由归因。没有匹配规则时保留差异和诊断限制，不能把“未检测到问题”当作通过。

领域别名在可选配置 `configs/benchmark/mini-agent-diagnostics-v1.json` 中按意图声明。配置有版本与 SHA256 校验；只有参考契约确实要求对应标准字段时，才提示候选映射。通用报告模块不内置 mini_agent 的 count/num 等字段。别名仅用于解释，不进入执行输入或正式评分。

建议按证据触发：实际请求缺少标准参数定义时，第一步补齐意图请求的具体 Schema、与执行校验使用同源契约，并检查实际模型请求；第二步才按需评估别名兜底、冲突和类型校验。别名不能替代 Schema 注入；确认轮请求缺少前轮信息时提示上下文续接。不能仅凭输出不匹配断言“模型忽略了已明确提供的 Schema”，也不能保证增加别名后所有链路都会通过。

## 命令与产物

以下命令从仓库根目录执行；默认完全离线，不调用模型、不上传：

```bash
.venvs/evaluator/bin/python scripts/benchmark_presentation.py \
  --run artifacts/mini-agent/coverage-20261107/run \
  --profile configs/benchmark/mini-agent-diagnostics-v1.json
```

需要显式交付 Langfuse 时，先按原 benchmark 导出/回读流程获得 `langfuse_export.json` 和 VERIFIED 的 `langfuse_verification.json`，然后使用：

```bash
.venvs/evaluator/bin/python scripts/benchmark_presentation.py \
  --run artifacts/mini-agent/coverage-20261107/run \
  --sync-langfuse --dashboard
```

凭据只从本地 `.env` 读取。`report-links.json` 绑定源结果、目的地、原导出收据与 Trace ID。HTML 仅显示通过这些本地检查的链接，否则明确显示未导出/未核验，完整离线 Trace 仍可阅读。

## 历史 Trace 与新导出

[Langfuse v4 的已入库观测不可变](https://langfuse.com/faq/all/tracing-data-updates)。因此历史运行不重发 Span 来修改名称或标签：展示模块通过分类注释补充诊断，名称使用 `diagnostic.*.{analysis_id前缀}`，metadata 明确标记 `formal=false`。这些注释使用 Langfuse 的 Score 容器，但不属于新正式指标，也不产生第二套 PASS/FAIL。注释采用确定性 ID，先记录提交意图再写入；状态不确定时只回读，不盲目重发。

未来第一次导出时，保存诊断快照到导出收据，并在原 Span 首次入库前添加任务类别名称、operation/task_group/diagnosis 标签。续传及核验使用同一收据快照；历史收据不自动升级。正式分数、Span ID、输入输出和时序保持原语义。

## Dashboard 口径

前三个面板分别展示：保存的正式 verdict 分布；按任务目标分组后的 verdict；可重叠的诊断类别影响数。按源结果 Hash 筛选，诊断另按 analysis_id 区分，不混入其他运行或新旧解释版本。面板中的分组注释复用原 verdict，不进行重新评分。

总通过率分母含该次全部 trial；INVALID 不算通过。写场景中的保护路径 PASS 不等于成功写入。诊断类别可能重叠，不能将影响数相加当作失败总数。不同数据集或控制项的补跑单独展示。当前仅一组可比主集，趋势面板显示基线，不能声称改善。Dashboard 受页面日期筛选影响，查看历史运行需要覆盖其执行日期；生成的 Dashboard 链接已携带执行时间范围，避免沿用浏览器中旧的日期筛选。

核心报告模块不导入 mini_agent 或 Langfuse SDK；远端模块只在显式同步/导出时导入。Oracle 仅供离线诊断与评分使用，不进入模型请求。

## 跨运行趋势

追加 `--trend` 可离线生成 `trend.json`；重复 `--trend-run /path/to/saved/run` 加入后续运行。同步并更新已有 Dashboard 的示例：

```bash
.venvs/evaluator/bin/python scripts/benchmark_presentation.py \
  --run artifacts/mini-agent/coverage-20261107/run \
  --sync-langfuse --dashboard --trend --refresh-dashboard
```

趋势固定数据集与参考契约、选集、重复次数、正式评分身份、Harness、Inspect、执行模式、超时/预算与生成配置。模型及运行实现源码身份可以变化，并记录在逐 run 明细中；这是描述性对比，不证明某项改动导致改善。重复、不完整、分组不一致和控制项不一致的数据拒绝加入。目前要求每个 run 对应一个 Langfuse experiment，不支持把多 experiment 的重复试验误当成一组。

第四个面板按 `cohort_id` 筛选，不固定单 run。每次运行将原 verdict 聚合为读/写通过率，保存为 experiment 级 `summary.pass_rate.*`，metadata 为 `formal=false`；不新增 trial 正式判定。INVALID 保留在分母。后续同口径结果也需要显式同步；面板不会自行执行评测或上传。

Langfuse 的时间折线自动分桶，同桶内多个 run 的比率等权平均，不能保证每个图点恰好是一个 run；精确分子、分母、时间和运行身份保存在 `trend.json`。Langfuse 可能将空时间桶显示为 n/a/0，它表示无运行数据，不是通过率 0%。只有一轮时显示“仅基线”。当前读 90%、写 10%，写保护路径通过不等于成功写入。

`--refresh-dashboard` 只更新已登记的 Dashboard/Widget ID，并归档旧收据到 `langfuse-dashboard-history/`。诊断解释更新仍保留旧版注释；不会重复计算失败。`restricted_response` 已涵盖当前工具受限回复的解析错误，说明中标注 InvalidModelOutputError，不再另计一次 `invalid_model_output`。总览标题直接显示 PASS/FAIL/INVALID 数量。

## 调试入口与健康度扩展

在上面的同步命令追加 `--explore`，生成 `explorer.html` / `explorer.json`，并扩展同一个 Dashboard。仅离线生成入口可使用 `--run … --explore`，仍要求已有经过核验的 Trace 链接。入口按问题或任务族筛选用例，每条记录直达原始 Trace；分类链接使用精确根 observation ID 和执行时间范围。过长的 URL 不会悄悄截断筛选条件。

原生 Dashboard 增加健康度数字卡、问题/任务族下钻卡、延迟与 Token/费用趋势和正式 Score 分布图。下钻通过卡片菜单 **View as table** 进入根观测列表，再打开 Trace；不是点击任意柱子就自动联动嵌入表格。HTML 入口同时提供按精确 ID 的直接列表链接。原生下钻以源结果 Hash、原根节点名称和 AGENT 根类型共同约束，避免把 LLM/工具子事件算成多个 trial。

延迟使用保存的 trial 完整耗时，P95 沿用 HTML 报告口径；工具均值为实际 tool 事件数除以全部 trial。输入 Token 包含缓存，缓存曲线是其子集，不再次相加；无法确认缓存口径则保留未知。成本按实际金额和价格快照估算分开展示，订阅额度价值不代表实际扣费。Langfuse 不会自动补齐未导出的价格或工具统计。

健康度和趋势以非正式 experiment Score 保存，名称为 `display.v1.*`，`formal=false`。整组展示内容生成 `view_id`，Score ID 与 Widget 筛选均绑定该快照；价格、缓存证据、诊断或运行集合改变后保留历史快照，当前查询不混算新旧数据。写入不确定时只回读；已存在但内容冲突则报错，不永久等待。Dashboard 刷新保留用户另加的 Widget/文本，并归档原布局。同步复用配置相同的面板，并按托管 API 限额节流；限流中断后可再次执行以回读续传。正式分布图仅使用保存的正式且已评分指标；若同名指标包含其他状态/非正式记录，则不创建该面板，仍保留离线明细。同步前回读确认远端样本值、数量与正式性一致。

趋势只纳入显式提供且同口径的完整运行；目前只有一轮可比基线，不能推断改善或绘制真实多模型对比。每个 run 一组汇总值，平台按时间分桶，同桶多 run 为等权均值。扩展不调用模型、不重新评分、不修改原始 Trace，也不要求被测 Agent 依赖 Langfuse。

离散 Score（最多 20 种实际取值）按分值精确计数；更连续的指标采用平台近似直方图，并标明近似频数。避免原生近似分桶将 0/1 评分显示成小数样本数。

## 阅读顺序布局

Dashboard 按六组排列：全局数字（6 列）→ 读写拆分（整行）→ 四组趋势（4 列）→ 诊断宽图及四个下钻数字 → 任务族（6 列）→ 正式 Score（3 列）。新增独立通过率卡，移除可见的平均工具调用卡和重复任务族汇总柱图，保留原始 Widget 与 Score 供历史查询。主运行当前为 25 个可见 Widget；窄屏可能由 Langfuse 自适应换行。

可选 `report-dashboard.json` 的 `task_group_order` 指定展示顺序；示例见 `configs/benchmark/mini-agent-dashboard-layout.json`。不改变数据集、执行输入或正式评分。任务卡标题显示通过数/总数及通过率，原生 Number 仍显示该组用例总数，以保留 View as table 的精确根节点查询。

当前托管 Widget 配置不暴露环形图中心文案或隐藏空桶系列开关。通过率使用顶部卡片表达，重复环形图从布局移除但保留资产。原生大数字根据宽高自动缩减小数位，且没有公开的百分号格式配置；卡片缩短高度，并在标题显式显示精确通过率及美元估算下限，避免把估算读成零。趋势上的空名称行是查询后补桶；增加名称非空过滤不能消除这些行，不能将 avg 改成 sum 来消除噪音，否则同桶多 run 的口径会错误。空桶 n/a/0 不是一次真实测量。此限制来自平台组件，不通过篡改原始结果绕过。

后续运行仍需显式加入 `--trend-run` 集合并同步到同一可比组，页面时间范围也需覆盖新运行；同一时间桶内的平台聚合不保证每个 run 单独显示一个点。

### HTML 阅读重心

概览压缩为一行，问题摘要、归因因果链、下一步建议与逐条结果保持展开。任务类别、数据划分、评测层次、统计口径和用量与身份默认折叠；尾延迟解释也可按需展开。所有冻结证据、配置、价格来源与 Trace 链接仍保留，折叠仅改变呈现，不重新评分或调用模型。

### 范围、比较与检索

范围仅从身份绑定的冻结任务和已保存 assessment 推导。coverage_tags 按选定任务去重，分别显示选定与已执行数量；正式 metric 按执行去重，仅明确 formal=true 且 status=SCORED 的记录计入已评分数量，未标注的历史记录另行披露。标签不与评分项自动配对，SCORED 不等于 PASS，安全标签也不构成完整安全认证。未选入的任务不能扩大本轮覆盖范围。

报告明确是单轮快照，未在本页载入并验证对照运行时不宣称版本改善；也不根据先后顺序把运行命名为修复前后。性能说明仅描述本批尾延迟比例与可核对的 Token 结构，不做无阈值的达标判断。

目录可展开折叠证据；问题分类支持筛选全部受影响执行，也可逐条跳转。跳转到被筛选隐藏的证据时会清除筛选，保证证据可见。字段映射表和读侧失败摘要复用已有诊断，不增加新归因或业务风险等级。统计口径集中说明历史 P95 算法差异，不改变历史数值。
