# 离线报告与 Langfuse 联动

HTML 负责当前运行的整体结论、模式摘要、条件建议及完整离线证据。Langfuse 提供逐次模型/工具调用浏览、已保存正式评分和展示面板。Inspect 负责执行与日志，DeepEval 负责正式评分；诊断不会改变历史判定，也不会修正被测 Agent 的参数。

## 共享诊断

`report_diagnostics.py` 从保存结果与 Hash 绑定的任务、参考契约生成 `diagnostics.json`，同时归档到 `report-diagnostics/{analysis_id}.json`。文件记录源结果 Hash、规则版本及代码 Hash、可选配置版本、证据、问题编号和分组。HTML 与 Langfuse 使用同一份产物；规则更新产生新的解释版本，不改写旧记录。

规则名称和中文文案属于可维护的诊断规则。受影响用例、计数、字段偏差和行动建议由证据驱动；并非依赖另一轮模型自由归因。没有匹配规则时保留差异和诊断限制，不能把“未检测到问题”当作通过。

领域别名在可选配置 `configs/benchmark/mini-agent-diagnostics-v1.json` 中按意图声明。配置有版本与 SHA256 校验；只有参考契约确实要求对应标准字段时，才提示候选映射。通用报告模块不内置 mini_agent 的 count/num 等字段。别名仅用于解释，不进入执行输入或正式评分。

建议按证据触发：实际请求缺少标准参数定义时提示补齐契约；存在重复字段偏差时提示被测 Agent 评估别名兼容、冲突和类型校验；确认轮请求缺少前轮信息时提示上下文续接。不能仅凭输出不匹配断言“模型忽略了已明确提供的 Schema”，也不能保证增加别名后所有链路都会通过。

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

三个面板分别展示：保存的正式 verdict 分布；按任务目标分组后的 verdict；可重叠的诊断类别影响数。按源结果 Hash 筛选，诊断另按 analysis_id 区分，不混入其他运行或新旧解释版本。面板中的分组注释复用原 verdict，不进行重新评分。

总通过率分母含该次全部 trial；INVALID 不算通过。写场景中的保护路径 PASS 不等于成功写入。诊断类别可能重叠，不能将影响数相加当作失败总数。不同数据集、控制项或运行身份的补跑单独展示；当前只有一组可比主集，不生成虚假的跨版本趋势。Dashboard 受页面日期筛选影响，查看历史运行需要覆盖其执行日期；生成的 Dashboard 链接已携带执行时间范围，避免沿用浏览器中旧的日期筛选。

核心报告模块不导入 mini_agent 或 Langfuse SDK；远端模块只在显式同步/导出时导入。Oracle 仅供离线诊断与评分使用，不进入模型请求。
