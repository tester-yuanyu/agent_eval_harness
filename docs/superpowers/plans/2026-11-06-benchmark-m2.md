# Benchmark M2 实施计划

使用 executing-plans，基线 936c645，复用 benchmark-cleanup 隔离工作树。依据完整设计 §4–6 与完整计划 T5–T8，用户已要求执行 M2。无需重复设计审批；M3/M4 不在本批。

## Global Constraints

冻结任务/历史结果不改；无网络分析、不执行 Agent/Judge；四层分母隔离；复评不增加执行；未知用量不填零；proposed 不冒充人工 reviewed；输出不含 prompt/私有依据/密钥。旧 report/compare 默认行为不改。

## Review Focus

来源 Hash/identity/observation 全链路验证；显式来源无环且不自动跟随路径；缺失计划仍进分母；Judge 子集不裁剪执行总体；pass^k 无完整总体不出主值；逐字段成本覆盖；分桶多标签不可加总；报告转义和输出目录不可覆盖；无可选 Agent SDK 核心可用。

### Task 1: 来源链与计划总体

- [x] 先测原始执行、真实旧 regrade 格式、Judge 子集、篡改/缺链/重复/越界/层级错绑红灯。
- [x] 实现 analysis_sources、populations 与共享 AnalysisPolicy；只消费显式本地文件，保留完整计划。
- [x] 定向绿灯，记录身份及分母边界，提交。

### Task 2: 失败归因与基础本地报告

- [x] 先测 PASS 恢复、Agent/基础设施/评分/unknown、证据引用与不修改输入。
- [x] 实现失败统计、基础 analyze/report/CLI（JSON/Markdown/HTML/provenance），严格输出白名单；分析源码身份和内容稳定。
- [x] 旧输出不改、HTML 转义、无凭据运行测试通过；提交。

### Task 3: 可靠性与成本

- [x] 先测 comb 算例、缺失/INVALID/INCONCLUSIVE、k 边界、micro/family macro、重复协议状态。
- [x] 先测费用 10/20/30、已知小计/覆盖率、零成功、布尔/非有限/负值、Agent/Judge/模拟器隔离、事件别名。
- [x] 实现纯函数并接报告，不改原 summary；定向绿灯，提交。

### Task 4: 独立注释资产

- [x] 先测严格合同分发与 binding、注释三文件 hash、未知/重复/版本覆盖拒绝、proposed/reviewed、难度边界和私有依据投影。
- [x] 实现包内严格 loader/binding（不补 M1 descriptor 抽象）、共享注释模型、构建与校验 CLI；冻结 file-tools-v2 proposed 独立注释版本。
- [x] 能力/难度按层分桶，未审/未标注数量披露；源 run legacy identity 校验；测试及冻结校验通过，提交。

### Task 5: 对比、最终报告与验收

- [x] 先测受控 ExperimentSpec 与探索性对比，身份差异必须展示，regrade 标 scoring_only。
- [x] 完整本地报告、中文指标文档、CLI 根转发与 HTML 内容/转义验证。
- [ ] 浏览器视觉抽查：本地文件 URL 被安全策略拒绝，未绕过，见验收记录。
- [x] 完整 evaluator + contracts/root 及相关 Builder 回归、Ruff、冻结资产、独立审查和全新 core 克隆安装/demo/analyze/annotations 验收。
- [x] 记录验收/未覆盖项，按已有授权本地整合，不推远端。
