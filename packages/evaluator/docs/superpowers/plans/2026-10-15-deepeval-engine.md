# DeepEval 主评测引擎迁移

用户已确认的目标：整个评估体系使用 DeepEval 框架，领域约束作为扩展保留。

## 设计与边界

Provider 只负责隔离执行、真实交互、证据收集及清理。执行结束后转换为 DeepEval `EvaluationDataset`、`LLMTestCase` / `ConversationalTestCase`，由 `evaluate()` 调度业务 Metric。Metric 内计算确定性断言、加权与关键断言策略、可选 GEval Judge、有效性和结论；不能把旧引擎预计算的分数包装成 Metric。

业务规则使用一个组合 Metric，保留非关键断言加权通过、关键断言一票否决和证据不足语义。单项断言作为原生 Metric 的结构化详细日志保存。DeepEval 的布尔 success 表示是否可以通过，详细日志区分 FAIL、INCONCLUSIVE、INVALID，不把未知记作零分。

DeepEval 原生 TestRun JSON 是框架运行记录。现有 results.json 是领域审计、对比、门禁及历史兼容导出。保存相对路径引用并迁移原生文件；运行引擎版本和适配策略版本参与可比性检查。

## 全局约束

- 保留当前工作区未提交成果，不覆盖、不自动提交。
- Oracle 不进入 Agent；不使用随机多轮模拟替代冻结输入。
- trials 每次真实执行，关闭 DeepEval 缓存与自动重跑。
- 无 Confident 云上传、无隐式模型调用。DeepEval 全局状态在进程内加锁并复位；固定版本 4.2.9。
- 使用 DeepEval 原生本地序列化，显式写入运行目录；不依赖工作目录的隐藏缓存。
- 不改上游源码；通过依赖及自定义 Metric 扩展。

## 实施步骤

- [x] 1. 写集成失败测试：默认 evaluate 路径、未预评分、真实重复执行、原生结果。
- [x] 2. 拆分执行与领域评估，将领域评估移入 DeepEval 自定义 Metric。
- [x] 3. 接入标准单轮/多轮 Dataset、原生 TestRun 本地存储和引擎指纹。
- [x] 4. 验证未知、无效、关键断言、Judge、可移植报告及历史可比性。
- [x] 5. 更新架构及使用文档，运行完整测试、礼物示例、静态检查并独立审查。

## 验证命令

`.venv/bin/python -m pytest tests/test_deepeval_engine.py -q`；完整 `.venv/bin/python -m pytest -q`；`.venv/bin/ruff check .`；`examples/stateful_gift.py` 离线端到端。

## 进度与裁决

- 当前已有 DeepEval 4.2.9 GEval Judge；这次迁移默认 runner，而非新增可选实验后端。
- 保留 run_evaluation / run_provider_evaluation 为兼容门面，通用 Metric 调度移交 DeepEval；环境执行循环属于 Provider 编排。
- 原生存储直接使用固定版本的 TestRun 和本地 writer，避免 evaluate 自动终结时隐式云上传和全局滚动文件；此适配由集成测试约束。

- 任务 1–4 完成：15 项引擎专项测试通过。新增原生结果迁移、引擎可比性、真实重复执行、未知/无效/关键判定、无网络、观测快照和超时作用域测试。
- 独立审查发现 DeepEval 外层软超时可能留下后台 worker；已通过先失败后通过的回归测试修复，在作用域内关闭并恢复该超时。复审 15 项通过，无剩余重要问题。

- 最终验证：完整 pytest 341 passed / 2 skipped（付费 API 冒烟），51.86s；ruff check . 通过；pip check 通过；120 个本地文档链接全部有效。
- 礼物示例：8 个 Trial，原生 TestRun 含 2 个单轮和 6 个多轮对象；4 PASS / 4 FAIL，全部 VALID / CLEANED。示例报告：artifacts/deepeval_engine_demo/stateful-gift-p2s9fnx7/eval_run_bca50ccdebbd40b2b13b32441fc97a0a/report.md。
