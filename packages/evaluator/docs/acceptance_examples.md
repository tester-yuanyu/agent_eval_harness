# Evaluator 能力验收与示例手册

> 本文属于旧 Suite／Provider 兼容路径；其中 Inspect 评分、指标和产物约定不适用于当前任务基准。新基准由 Inspect 执行与记录、DeepEval 正式评分，入口见[包说明](../README.md)。以下包内命令在 `packages/evaluator` 目录执行。

2026-10-20 更新：Inspect 负责正式调度、判分和指标；Evaluator 保留业务扩展；Langfuse 接管展示和人工标注。旧 DeepEval Runner/G-Eval 路径已删除；2026-10-28 起可选接入 [Conversation Completeness](conversation_completeness.md)，仍由 Inspect 执行。最新单一职责、权威数据与验收限制见 [接入说明](langfuse.md)。

本文给出了解和验证当前框架的离线路径。核对日期：2026-10-13；范围是当前工作区实现，不是对某个发布版本的认证。先看[能力清单](capabilities.md)了解限制，再按本文执行；内部流程见[架构说明](architecture.md)。

## 1. 验收目标与准备

验收关注：输入是否被正确加载与隔离、实际行为是否被记录、正确与错误是否被区分、证据故障是否显式暴露、结果能否追溯。脚本模型与测试夹具不证明真实模型的理解能力，也不证明 Judge 的语义准确性。

命令均在仓库根目录执行，使用已安装项目及依赖的 `.venv`。首次安装见 [README](../README.md#安装)，独立 SDK 安装见[证据通道说明](TRACE_PHASE1.md)。mini_agent 为相邻项目的可编辑依赖，依赖变化可能引发能力契约不兼容；这类失败应调查，不能通过覆盖冻结文件绕过。

本手册的示例和选定测试不需要模型凭据、不调用付费模型。真实 OpenAI/DeepSeek 冒烟测试另行显式启用，不属于这组验收。

## 2. 首先运行一个完整示例

```bash
../../.venvs/evaluator/bin/python examples/stateful_gift.py --output-dir artifacts
```

脚本在 artifacts 下创建新的 stateful-gift-* 目录，导出匹配当前环境的能力包，生成 Suite 和四个 Case，再经编译、真实 mini_agent 运行时、本地 SQLite 环境、取证、评分与报告走完流程。模型响应是脚本化的，运行模式为 framework_self_test，每个 Case 执行两次。

命令输出 JSON，包含 suite、run_directory、report 和 quality_counts。按实际输出路径打开报告，不要依赖固定的随机目录名。

| Case | 检查场景 | 当前预期 |
| --- | --- | --- |
| GIFT-GRANT | 澄清、确认后检查是否实际发放 | FAIL：Agent 当前不能完成确认接受并放行写操作 |
| GIFT-CANCEL | 确认后取消，检查拒绝且无写入 | PASS：脚本化拒绝响应与观察符合预期 |
| GIFT-CORRECTION | 修改数量后确认，检查逐轮参数和实际发放 | FAIL：Agent 仍停留在确认阶段，未完成预期写入 |
| GIFT-LINK | 单次 Agent 调用请求确认，检查状态不变 | PASS |

预期共有 8 个 Trial，4 个 PASS、4 个 FAIL；所有 Trial 的评测有效性为 VALID、清理状态为 CLEANED，初始账本 grant_count 为 0。FAIL 是示例要展示的有效业务结论，脚本成功结束不要求全部 Case PASS。

这些预期由[示例测试](../tests/test_stateful_example.py)直接核验：

```bash
../../.venvs/evaluator/bin/python -m pytest -q tests/test_stateful_example.py
```

示例的脚本模型工厂通过 Python 注入，单独对生成的 Suite 执行 CLI run 不会自动恢复这套脚本响应。离线复现应再次执行示例脚本或使用同一工厂的 Python 路径。

## 3. 读取哪些产物

| 产物 | 应观察的内容 |
| --- | --- |
| report.md | 运行是否有效、质量结论、失败检查项及证据入口 |
| results.json | 8 个 Trial 的执行状态、quality_conclusion、evaluation_validity、score、cleanup_status |
| run_manifest.json | 数据、Provider、能力包和编译 Suite 的身份与指纹 |
| cases/<case_id>/<trial_id>.json | 实际输出、逐轮参数和 before_snapshot / turn_snapshots / system_snapshot |
| evidence/<trace_id>/events.jsonl | 原始独立事件；同时检查同目录 collection.json 与 association.json |
| stability.json | 每 Case 重复 Trial 的汇总；不要把脚本化一致性解释为真实模型稳定性 |

检查 GIFT-GRANT 时，应能把“期望写入一次”和“实际账本未写入”联系到具体断言及状态证据。检查 GIFT-CANCEL 时，应同时核对拒绝状态和账本未变化，不能只看自然语言回复。

## 4. 分别验收四种结果

### 4.1 正确行为：PASS

运行模块、链路及端到端的离线隔离测试：

```bash
../../.venvs/evaluator/bin/python -m pytest -q \
  tests/test_execution_scoring.py::test_module_link_e2e_all_run_offline_and_are_isolated
```

它验证给定夹具的执行与隔离行为；结合状态型示例中的取消和链路 Case，检查通过结论是否有实际观察支撑。

### 4.2 已知错误：FAIL

```bash
../../.venvs/evaluator/bin/python -m pytest -q \
  tests/test_execution_scoring.py::test_wrong_module_answer_is_stable_fail \
  tests/test_multiturn_execution.py::test_turn_checks_reject_bad_intermediate_behavior_despite_correct_final_state
```

验收重点是错误答案必须失败，以及正确终态不能掩盖中间轮次违规。状态型示例中的发放失败则展示了真实运行时能力限制如何落入业务结论。

### 4.3 缺失或不可信证据：不能误判通过

```bash
../../.venvs/evaluator/bin/python -m pytest -q \
  tests/test_multiturn_execution.py::test_missing_turn_state_is_inconclusive_and_does_not_hide_known_failure \
  tests/test_evidence_boundaries.py::test_tampered_association_cannot_prove_a_violation
```

缺失状态的检查应保留无法判定，独立已知违规仍可失败。关联被篡改的事件既不能证明通过，也不能证明当前 Trial 违规；必需证据关联故障还会影响 evaluation_validity。不要把检查级 INCONCLUSIVE 与 Trial 级 INVALID 混为同一个字段。

### 4.4 评测器异常：保留业务观察并记录 INVALID

```bash
../../.venvs/evaluator/bin/python -m pytest -q \
  tests/test_execution_scoring.py::test_assertion_failure_invalidates_evaluation_not_agent \
  tests/test_evidence_boundaries.py::test_cleanup_failure_preserves_execution_and_observed_violation \
  tests/test_evidence_boundaries.py::test_later_trial_runs_after_reader_failure
```

验收断言异常、清理异常及读取异常是否记录到评测问题中，是否保留 Agent 执行状态和已证实违规，以及后续 Trial 是否继续。不能把框架异常统计成普通 Agent 质量失败。

## 5. 综合离线验收

下面覆盖 Suite、编译执行、多轮、状态、证据和运行后决策。各文件中测试数量可能随项目变化，不将固定数量作为长期验收标准。

```bash
../../.venvs/evaluator/bin/python -m pytest -q \
  tests/test_suite_contracts.py \
  tests/test_compiled_execution.py \
  tests/test_multiturn_execution.py \
  tests/test_stateful_environment.py \
  tests/test_stateful_example.py \
  tests/test_execution_scoring.py \
  tests/test_evidence_boundaries.py \
  tests/test_phase2_end_to_end.py
```

针对扩展能力还可分别运行：

| 关注点 | 现有测试 |
| --- | --- |
| Hash、路径与预检 | [test_contract_store.py](../tests/test_contract_store.py)、[test_suite_compiler.py](../tests/test_suite_compiler.py) |
| Provider / Loader 可扩展性 | [test_provider_architecture.py](../tests/test_provider_architecture.py)、[test_dataset_loader_plugins.py](../tests/test_dataset_loader_plugins.py) |
| Judge 阈值与失败处理 | [test_judge.py](../tests/test_judge.py)、[test_inspect_judge.py](../tests/test_inspect_judge.py) |
| 基线可比性与门禁 | [test_comparison.py](../tests/test_comparison.py)、[test_gating.py](../tests/test_gating.py) |
| 人工复核审计 | [test_langfuse_reviews.py](../tests/test_langfuse_reviews.py) |

第二阶段端到端测试使用构造结果验证分析、比较和门禁产物，不代表它运行了一个完整的真实模型基准。真实模型与 Judge 需另用明确正确、明确错误和模糊样本进行校准，并记录人工分歧。

## 6. 运行后命令模板与退出码

以下是操作模板，需将路径替换为已有运行产物；比较双方应具有满足规则的相同评测条件。不要为了让门禁通过而把 framework_self_test 示例冒充正式 Benchmark。

```bash
../../.venvs/evaluator/bin/python -m eval_framework.cli analyze --run-dir artifacts/RUN
../../.venvs/evaluator/bin/python -m eval_framework.cli compare \
  --baseline artifacts/BASELINE --candidate artifacts/CANDIDATE \
  --output-dir artifacts/comparison
../../.venvs/evaluator/bin/python -m eval_framework.cli gate \
  --candidate artifacts/CANDIDATE --comparison artifacts/comparison \
  --policy policies/release_gate.example.json --output-dir artifacts/gate
```

示例 Gate Policy 是可修改的策略样本，不是所有项目默认接受的发布标准。

| 命令 | 退出码语义 |
| --- | --- |
| run | 普通 Agent 质量失败仍可返回 0；无效数据或结构化预检失败返回 2 |
| compare | 比较有效返回 0，即使发现回归；输入或比较无效返回 2 |
| gate | PASS 为 0，输入或比较无效为 2，FAIL 为 4，REVIEW_REQUIRED 为 5 |

自动化调用者应读取结构化产物，不能只凭 run 返回 0 认定质量通过。

## 7. 如何记录一次能力验收

记录当前提交及未提交改动状态、Python 和 mini_agent 版本、运行命令、测试结果、示例产物路径及契约指纹。区分“脚本响应验证框架”和“真实模型验证质量”。本手册描述预期与复现方法，不能替代每次实际执行的验收记录。

若结果偏离预期，先检查依赖与冻结契约是否匹配，再区分业务行为变化、证据故障或评分缺陷。能力改变后同步更新[能力清单](capabilities.md)、相关契约和本手册预期，不通过修改旧产物隐藏差异。
