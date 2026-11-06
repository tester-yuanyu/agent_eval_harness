# Benchmark 完整改造实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans 逐项实施；需要分派独立任务时再使用 superpowers:subagent-driven-development。步骤使用复选框记录，不能用工程验收代替人工或真实评测验收。

**Goal:** 完成领域/运行适配/评分/分析边界，补齐可追溯的能力标签、可靠性与效率报告、失败归因、校准和展示交付。

**Architecture:** 基于 `04a1cc3` 渐进迁移，旧入口保留门面。新分析和注释为独立版本资产，旧结果不重写；Harness 接口改动先协调所有权。所有计算先支持本地保存证据和无网络验收。

**Tech Stack:** Python 3.11+、Inspect、DeepEval、既有 contracts/Pydantic、pytest、Ruff；Langfuse 可选。

**Spec:** [完整设计](../specs/2026-11-06-benchmark-complete-design.md)。本文件是分批执行路线图；本轮具体完成与限制见 [M1 验收](../../migration/benchmark-m1-acceptance-2026-11-06.md)。

## Global Constraints

- Inspect 执行与日志、DeepEval 正式确定性评分、GEval/native LLM metrics 诊断、Langfuse 展示。
- 四层分母隔离；冻结数据、manifest、历史结果和 Hash 不覆盖。
- Oracle/reference/checkpoint/标签依据不进入模型消息或公开执行输入。
- 可选 Agent/展示 SDK 不阻塞核心导入；worker 和各包独立环境保持。
- 运行身份漂移继续拒绝；参考身份与当前运行身份分开。
- 测试/demo 禁止真实模型和托管上传；真实交付单独按当次授权执行。
- 新资产不可变；v3 agent.json 及 bundle 内清单结构不改。
- Benchmark 不自行修改 Harness loop。跨任务共享文件先约定单一所有者。Environment 任务目前拥有 environments/**、其 Harness 契约导入和 integrations/nanobot/sources.py；T1/T2/T3 不覆盖这些并行改动。
- 逐批实施范围以最小闭环计划和验收记录为准；本路线图不启动真实实验或人工标注。

## Review Focus

1. 文件型领域迁移后，非文件任务不得被迫伪造 fixtures；私有内容不得通过 SampleSpec 泄漏（T1）。
2. 脚本入口、平铺 Docker、缺少可选依赖时仍可用；源码闭包不能只覆盖门面（T2/T3/T4）。
3. 注释 hash 错绑、重复 ID、多标签重复计数、缺失任务造成分母漂移（T5/T6/T8）。
4. 复评伪装重复运行、INVALID 被筛掉、未知费用当零、零成功除零（T6）。
5. 开发试标冒充独立校准、失败工具误判为失败任务、汇总指标重复上传后重复平均（T7/T9/T11/T13）。

## 文件地图与执行顺序

下文路径均相对仓库根；`E=packages/evaluator/src/eval_framework`，`T=packages/evaluator/tests`，`C=packages/contracts/src/eval_contracts`，`CT=packages/contracts/tests`，`B=packages/dataset-builder/src/dataset_builder`。通用结构放 C，执行依赖放 E，Builder 只消费 C。

- 已完成 M0：旧职责整理，见 `docs/migration/benchmark-boundaries-acceptance-2026-11-06.md`，不重复执行。
- M1 首批：T1 的公开 Sample 装配 → T2 → T4，详见 [最小闭环计划](2026-11-06-benchmark-m1.md)。T1 的通用 loader/descriptor、T3a/3b/3c 另批实施；不将本批标成整个 M1 完成。
- M2 首批：T6 的最小来源链/计划总体校验 → T7 失败归因 → T8 基础本地报告；此批不依赖标签或 pass^k。后续完成 T6 可靠性/成本与 T5 注释，再接 T8 对应栏目，未实现栏目明确标 pending。
- M3：T9、T10、T11 在所需接口完成后逐项交付；T12 做整体验收。
- M4：T13 人工/真实评测/托管验收，前置条件未满足则记录 pending。

每项任务遵循：先写下列行为回归并确认新行为红灯，最小实现，运行指定检查，审查 diff，再只提交本项文件。纯搬迁保留已有测试，不为实现细节制造镜像测试。所有命令在对应包环境运行；不得复用其他包 site-packages 解决依赖问题。

### T1：领域装配与通用 Sample 边界（M1）

本轮完成包内 Sample 装配与 file-tools/SQLite 验证；通用 loader/descriptor 仍待实施，以下完整 T1 保留未完成状态。

**Files:** 新增 `E/benchmark/datasets/loader.py`、`E/benchmark/domains/presentation.py`、`T/benchmark/test_domain_presentation.py`；修改 `E/benchmark/{domain,runner,run_context,identity,layer_sources}.py`、`E/composition.py`、`T/benchmark/test_provider_domain.py`。

**Interfaces:**
- `DatasetDescriptor`：domain_id、contract_version、task_name、supported_modes、public_tool_names、categories；旧合同由可信代码生成，新外置 JSON 必须严格校验并纳入新资产 Hash。
- `load_dataset(path: Path, *, contract_version: str|None = None) -> dict` 返回 tasks、legacy_identity、descriptor；只分发现有 file-tools/model-decisions/core/provider 严格 loader，未知/矛盾版本拒绝；不改 tasks 内部结构。
- 包内 `SampleSpec`：input: str、files: dict[str,str]，不可包含私有 task；公开 case_id metadata 由 runner 设置。不提前发布共享 presentation 协议。
- `DomainPresentation.task_name: str`；`prepare_sample(public_task: dict) -> SampleSpec`。
- `run_benchmark` 新增可选 keyword-only `presentation: DomainPresentation | None = None`，旧签名调用保持有效。
- 旧 BenchmarkDomain 的三个方法不变；FileToolsPresentation/ProviderPresentation 只消费 execution_task 的结果。

- [ ] 新增 loader 分发测试：四类合同仍执行各自拒绝规则；未知/与 manifest 冲突版本拒绝，加载前后任务字节/identity 不变。
- [ ] 新增 `test_non_file_domain_runs_without_fixtures`：只有 prompt 和公开数据库输入的任务可执行；记录中 task_name 来自 presentation。
- [ ] 新增 `test_sample_contains_no_private_truth`：给 oracle/reference/checkpoint 放入哨兵字符串，Inspect input/files/metadata 及 adapter 请求均无哨兵；fixtures 内容即使像 URL 也只能是字面内容。
- [ ] 运行新测试确认红灯；实现可信 presentation 注册和兼容缺省，移除 runner 的 sample_files/fixtures/task_name 硬编码，sandbox 仍由 adapter 提供。FileTools 默认 task_name 保留。
- [ ] 运行 `cd packages/evaluator && ../../.venvs/evaluator/bin/python -m pytest tests/benchmark/test_domain_presentation.py tests/benchmark/test_provider_domain.py tests/benchmark/test_runner.py tests/benchmark/test_layered_identity.py`，全部通过。更新涉及源码闭包；新导入不能让 contracts 依赖 Inspect。
- [ ] 单项提交：`refactor(benchmark): separate domain sample presentation`。

### T2：nanobot 模式适配拆分（M1）

**Files:** 新增 `E/integrations/nanobot/adapters.py`、`T/benchmark/test_nanobot_mode_adapters.py`；修改 `E/benchmark/adapters.py`、`E/integrations/nanobot/sources.py`、`E/composition.py`；复用 `T/benchmark/test_{agent_adapters,module_runtime,decision_runtime,native_runtime}.py`。

**Interfaces:** `NanobotModuleAdapter`、`NanobotDecisionAdapter`、`NanobotAgentAdapter` 完整实现现有 AgentAdapter；provider IDs 为 nanobot_module/nanobot_decision/nanobot_agent。旧 provider nanobot 和 NanobotAdapter/NanobotRuntimeAdapter 继续作为同一兼容 facade，保存旧 provider_id。

- [x] 新增参数化测试：module 不调模型，decision 不执行工具，agent 保留完整 loop；错误模式在 preflight 拒绝；旧配置仍分派到相同执行语义。
- [x] 确认新注册测试红灯；提取共享配置/身份帮助函数，分别实现模式边界，不复制三份 SDK 逻辑。
- [x] 验证每个新实现变更均改变 adapter/source 身份；运行现有取消、进程树清理与 runtime drift 测试。
- [x] 跑上述 5 个测试文件及新文件，全通过后提交 `refactor(benchmark): split nanobot execution modes`。composition.py 的注册变更由双方约定的单一所有者执行。

### T3：集成归位，逐套迁移（M1）

**Files:** 目标 `E/integrations/nanobot/{core_worker,module_worker,decision_worker,nanobot_worker,module_runtime,decision_runtime}.py`、`E/integrations/mini_agent/{adapter,worker}.py`、`E/integrations/tau/{adapter,worker,harness}.py`；领域目标 `E/benchmark/domains/{nanobot_core,provider}/`；原 benchmark 对应文件保留 shim；修改 sources.py、inspect_docker.py、各 identity 与调用点；新增 `T/benchmark/test_integration_entrypoints.py`。

**Interfaces:** 现有 CLI/Python 函数签名、worker stdin→events/observation 协议、依赖 pin 不变。每集成提供 `worker_source_paths() -> dict[str,Path]` 的明确平铺清单；core 与 provider 原任务加载函数继续可调用。

- [ ] **T3a nanobot core**：先锁定 core loader/scorer、standalone worker、source-tree 和 `python -I -S` 平铺导入行为；迁移后跑 test_core_tasks/test_core_scoring/test_core_runner/test_core_worker及 test_integration_entrypoints，独立提交。
- [ ] **T3b mini**：保留 mini_dataset 的构造/冻结行为；数据与评分归 provider 域，SDK/worker 归 mini_agent 集成。无 minimal_agent 的核心/ExternalProvider 导入必须通过；有可选包的离线 SQLite 案例独立验证，单独提交。
- [ ] **T3c tau**：官方 pin、解释器/子进程入口、事件与错误 envelope 字节语义保持；跑既有 test_tau_adapter 与无 SDK 的 shim 导入，单独提交。缺少实际 τ 环境时记为未覆盖，不能声明运行等价已验收。
- [ ] 三项分别检查取消清理、Docker复制清单、模块 -m 启动和来源 fingerprint。未完成某项时保留原路径，不批量删除 worker。

### T4：评分实现统一，保持判定等价（M1）

**Files:** 新增 `E/benchmark/scorers/{deterministic,trajectory_judge,rubrics,judge_client,agentic_metrics,agentic_metrics_worker}.py`；修改原 `metrics.py`、`judging.py`、`agentic_metrics.py`、`agentic_metrics_worker.py` 为兼容门面及 scorer 导入、identity；新增 `T/benchmark/test_scoring_compatibility.py`。

**Interfaces:** 公共 `score_task(task, observation)`、`score_response(...)`、`judge_observation(...)`、`score_saved_agentic_metrics(...)` 的原签名与返回结构保持；搬迁使用现有版本/rubric 内容，新源码身份必须改变。正式与诊断角色沿用已有字段。

- [x] 记录固定保存证据上的正式 verdict、check、reason、evidence_refs、三个 GEval rubric Hash；新旧导入得到等价结果；诊断高分不能覆盖正式 FAIL/INVALID。
- [x] 先确认新入口不存在的红灯，再只移动实现及调整导入，保留 worker 的独立入口和请求预算。
- [x] 运行 `test_scoring_compatibility.py`、既有 metrics/oracle/layered_scorers/agentic_metrics/judge 测试；mock Judge 计数验证没有增加请求。不得调用真实模型。
- [x] 搜索生产引用，保证无双份评分算法，旧门面可导入；提交 `refactor(scoring): centralize implementations with compatible facades`。

### T5：不可变注释、难度与覆盖协议（M2）

**M2 交付记录：** 本批按 [独立实施计划](2026-11-06-benchmark-m2.md) 执行 T5–T8；具体接口、增补的版本登记与验收边界见 [M2 验收](../../migration/benchmark-m2-acceptance-2026-11-06.md)。HTML 浏览器视觉抽查仍未验证，未改为已完成。

**Files:** 新增 `C/benchmark_annotations.py`、`E/benchmark/datasets/binding.py`、`CT/test_benchmark_annotations.py`、`E/benchmark/datasets/annotations.py`、`E/benchmark/domains/file_tools_annotations.py`、`T/benchmark/test_annotations.py`、`data/benchmark-annotations/README.md`；在新目录生成版本化 proposed 注释；修改 `E/benchmark/cli.py` 和 T1 的 datasets/loader.py 描述绑定。

**Interfaces:**
- `DatasetBinding` 为 dict，含 binding_version、legacy_identity、manifest_sha256、files；`build_dataset_binding(root: Path, *, contract_version: str) -> dict` 在原 loader 校验后构造，返回 `{"binding": binding, "dataset_sha256": sha256_json(binding)}`，Hash 不写入被摘要的 binding 本体。files 是合同规定的完整任务/引用资产相对路径→字节 Hash，禁止绝对路径。
- `AnnotationSet` 包含 manifest、records_by_case_id、content_sha256；content_sha256 绑定 manifest/annotations/taxonomy 的原始字节 Hash，manifest 自身无自引用 Hash。
- `load_annotations(path: Path, *, dataset_binding: dict, case_ids: set[str]) -> AnnotationSet`，错绑、重复、未知 case、未知 taxonomy、非有限字段、同版本冲突均拒绝。
- `suggest_file_tools_annotations(tasks: list[dict]) -> list[dict]`，输出必须是 proposed；`public_labels(annotation: dict) -> dict` 去掉 basis_refs。
- CLI `annotations-validate --dataset ... --annotations ...` 只读；`annotations-build --dataset ... --output ...` 生成 proposed 新版本。

- [ ] 测试 Hash 不匹配、重复 case ID、同版本覆盖、未知能力拒绝；同 tasks 不同 manifest/contract、同 taxonomy_version 不同内容必须不同身份或拒绝；source_run 的 legacy_identity 与加载结果不等必须拒绝；部分注释允许但明确缺失清单；哨兵依据不能进入 public_labels。
- [ ] 实现设计中的九项能力 vocabulary 与结构难度规则。阈值边界测试 calls=2/7、depth=1/4、turns=1/3、branches=0/2；任何必需特征缺失返回 unknown，不能把 reference 长度当最短路径。
- [ ] 冻结 proposed 资产，校验源 tasks/manifest 原始字节完全不变；正式分桶只消费 reviewed，未审记录进入 unlabeled。
- [ ] contracts 与 evaluator 的新增测试通过，`python scripts/verify_assets.py` 通过；文档说明人工审定后另发版本；提交 `feat(benchmark): add immutable capability annotations`。

### T6：分析模型、可靠性与效率（M2）

**Files:** 新增 `C/benchmark_analysis.py`、`CT/test_benchmark_analysis.py`、`E/aggregator/{populations,reliability,efficiency,analysis}.py`、`E/benchmark/analysis_sources.py`、`T/benchmark/test_{analysis_populations,analysis_sources,reliability,efficiency}.py`；复用 summaries.py 的历史字段，不改旧默认输出。

**Interfaces:**
- `load_analysis_source(run_dir: Path, *, source_artifacts: tuple[Path,...] = (), judge_dir: Path|None = None) -> dict`：返回 selected_result、execution_result、canonical_keys、verified_source_hashes 和可选 judge diagnostics。原始执行无需附加文件；regrade 必须沿设计中的完整显式来源链验证；Judge 派生目录不能作为 --run。
- `AnalysisPolicy`：analysis_version、ks: tuple[int,...]、annotation_policy='reviewed_only'、incomplete_policy='require_complete'、repeat_protocol: dict|None；不接受静默过滤 INVALID 的配置。
- `build_population(source: dict, *, dataset: dict, annotations: AnnotationSet|None) -> dict`：索引所有计划 case/trial，拒绝重复/越界，输出分层计划分母。
- `reliability(population: dict, *, ks: tuple[int,...], repeat_protocol: dict|None) -> dict`。
- `efficiency(population: dict) -> dict`。
- `analyze_run(source: dict, *, dataset: dict, annotations: AnnotationSet|None, policy: AnalysisPolicy) -> dict`：source 是 load_analysis_source 的已验证结果，身份消费 verified_source_hashes；纯函数，不初始化模型。

- [ ] 明确算例：两题各 n=3，c=3 和 c=2，pass_hat_1=5/6，pass_hat_2=2/3，pass_hat_3=1/2；k=4 为 insufficient_trials；k=0/-1/bool 拒绝。
- [ ] 新增来源测试：缺上游文件、链有环、source_trial_sha256 错误、observation 被改、regrade 增减计划拒绝；Judge limit 不缩小执行总体；同执行不同 regrade 的 canonical_keys 相同，comparison_kind=scoring_only；读取路径仅来自显式参数。
- [ ] 缺一条计划 trial 或任一 INVALID 时主要 pass_hat_k 值为 null，状态 unavailable_incomplete_population；有效 INCONCLUSIVE 是非成功；未声明独立重复协议不能标为已验证可靠性。Judge repeat 和 reference demo 不进入 Agent 总体。
- [ ] 按各 token/费用字段分别显示 X/Y 计划 trial 完整覆盖、A/B 计划任务全部 trial 覆盖；usage 对象缺字段不计覆盖，零调用须有完整事件证据才计 0。
- [ ] 用三次消耗 10/20/30、其中前两次 PASS 验证成功条件均值=15、总尝试/成功=30；缺一费用时总体成本=null 且 known_count=2；零成功=null；bool/NaN/inf/负数拒绝，空总体不除零。
- [ ] 新测试红灯后实现上述接口，保留旧 all_trials_pass_rate。多标签从计划 case 构造独立桶，跨层禁合并；micro 与 family macro 并列。
- [ ] 运行新增四文件、contracts 测试和既有 runner/report/quality_audit 回归，全通过提交 `feat(analysis): add explicit reliability and efficiency populations`。

### T7：证据驱动失败归因（M2）

**Files:** 新增 `E/aggregator/failures.py`、`T/benchmark/test_failure_classification.py`；修改 analysis.py 集成诊断；定义规则版本 `failure-rules-v1`。

**Interfaces:** `classify_failure(trial: dict) -> dict` 输出 domain/primary/secondary/rule_version/evidence_refs；`summarize_failures(population: dict) -> dict` 分别统计 agent/infrastructure/scoring/unknown；读取现有 verdict，不重评分。

- [ ] 测试 unknown_tool/参数错误/终态错误/策略违反分别绑定决定性证据；PASS 中先报错后恢复仅为 recovered_error；timeout 根据明确来源区分基础设施和预算结束，来源不明保留 unknown；Judge ERROR 不变成 Agent FAIL。
- [ ] 确认红灯后实现有顺序的结构化规则，文本猜测不能生成“已证实根因”。多个决定性 check 按版本化优先级选择 primary，其余保留 secondary。
- [ ] 运行新测试与 module_oracle/recovery_scoring/metrics 回归，验证分析不修改输入；提交 `feat(analysis): classify failures with evidence references`。

### T8：本地报告、CLI 与比较控制（M2）

**Files:** 新增 `E/benchmark/analysis_cli.py`、`E/benchmark/analysis_report.py`、`E/aggregator/experiment.py`、`T/benchmark/test_analysis_{cli,report,comparison}.py`；修改 benchmark/cli.py、docs/benchmark/metric-specification.md、docs/README.md；根 CLI 只转发新子命令。

**Interfaces:**
- `write_analysis(run_dir: Path, *, dataset_path: Path|None, annotations_path: Path|None, output: Path, policy: AnalysisPolicy, source_artifacts: tuple[Path,...] = (), judge_dir: Path|None = None) -> dict[str,Path]` 产出 analysis.json/md/html、provenance.json；来源校验消费 T6.load_analysis_source，CLI 暴露可重复 --source-artifact 与可选 --judge-source。
- `validate_experiment(baseline: dict, candidate: dict, spec: dict) -> dict` 输出 compatible/descriptive_only/mismatches；不放宽 compare_runs。
- 受控实验的 ExperimentSpec 声明 control_fields、variable_fields；数据、合同、评分、选择、重复协议及执行层必须固定。受控差值只允许模型/运行身份这一组已声明变量；Harness、提示词、工具或环境改变时分栏描述，不生成受控差值。

- [ ] 探索性比较允许无 ExperimentSpec，展示各项控制差异并标 exploratory/descriptive_only；不产生受控差值或因果结论。受控实验仍要求预先指定 spec。
- [ ] CLI 在断网、无模型凭据、无 Langfuse 下读取冻结证据出报告；多标签桶不加总，未审标签显示 unlabeled；报告各层独立显示计划/有效/缺失。
- [ ] 测试源 Hash、注释 Hash、分析源码/策略变化会改变分析身份；相同输入字节稳定。既有 results.json、run.json、summary 和默认 report 文件逐字节不变。
- [ ] 新测试红灯后实现分析 JSON 为单一渲染数据源；旧报告保持，新增失败链接只引用可审查证据。命令显示使用安全参数序列，无凭据或未经转义的任务文本，不自动执行。
- [ ] 对同数据不同模型、不同任务选择、不同 scorer、不同工具和未声明 runtime 差异逐项验证比较资格；历史未知字段给明确不足原因。
- [ ] 运行新增 CLI/report/comparison 与现有 report/native_reporting/quality_audit/根转发测试；手工打开本地 HTML 检查空/缺失/失败页面，再提交 `feat(reporting): add versioned benchmark analysis reports`。

### T9：人工校准工具完善（M3，工程部分）

**Files:** 修改 `E/benchmark/{judge_calibration,calibration_reporting}.py`、新增 `E/benchmark/calibration_protocol.py`、`T/benchmark/test_calibration_protocol.py`；更新 docs/benchmark/judge-annotation-guide.md；不修改冻结的 36 条样本。

**Interfaces:** `validate_calibration_split(dev: dict, validation: dict) -> None` 检查 family 和执行证据交集；`agreement_report(labels: list[dict], judgments: list[dict], *, protocol: dict) -> dict` 区分 human-human/human-Judge、连续与分类分析；现有 compare_human_labels 签名保持。

- [ ] 测试开发/验证复用 family 或 execution evidence 被拒；Judge repeat 不能绕过去重；未审来源不能标 calibrated；盲标 HTML 无预测、理由、总体分布泄漏。
- [ ] 测试连续评分 MAE、分类 κ、expected agreement=1 时 κ 为 undefined；缺标签/ERROR/MISSING/NOT_APPLICABLE 不进入配对分母且分别披露。
- [ ] 实现不可覆盖的原标签、复核、仲裁记录和标签锁定；36 条状态始终为开发试标。rubric 改动必须独立版本任务，不夹带在工具升级中。
- [ ] 运行现有 judge_calibration/calibration_reporting 和新增测试通过；用空白/合成明确标记样本验收页面，不填写真实 human_score；提交 `feat(calibration): enforce independent validation provenance`。

### T10：领域通用性、鲁棒性数据与来源记录（M3）

**Files:** 新增 `T/benchmark/test_cross_domain_acceptance.py`、`B/benchmark_robustness.py`、`packages/dataset-builder/tests/test_benchmark_robustness.py`、`data/benchmarks/file-tools-robustness-v1/`（独立 manifest/tasks/README）、`docs/benchmark/dataset-provenance.md`；必要共享 validator 只放 C。复用现有 mini-agent 数据集和 public Provider 接口。

**Interfaces:** `build_robustness_tasks() -> list[dict]` 返回设计中的六类×两族×两变体共 24 个 dev 实例；冻结走 Builder 既有不可变发布流程，不引入 Evaluator 依赖。

- [ ] SQLite 域通过相同 runner/analysis 产生 PASS/FAIL/INCONCLUSIVE，且无 fixtures 占位；用独立 mock/offline Provider 实际修改本地 SQLite 并可信验证终态，证明架构接入而非模型分数。
- [ ] 新鲁棒性任务逐题验证成功轨迹、至少一条错误轨迹和参考预期；对特殊字符合法写入与真正路径越界分别测试，防止把统一拒绝当正确。
- [ ] 生成/冻结前验证家族变体不跨计划 split，24 条全 dev；旧任务/manifest Hash 不变，新版本重复发布内容不同须失败。
- [ ] 来源台账记录生成方式、人工修订/审核状态、公开时间、访问范围、精确重复与模板家族重复；未经人工审核标 proposed，不声明污染已排除。
- [ ] 并行/schema 变换登记为 blocked_by_execution_contract，写明需要的公开契约，不给旧任务补假覆盖标签。运行 Builder/合同/跨域测试和 verify_assets 后分别提交跨域验收、独立新资产两次提交。

### T11：Langfuse 分析导出与看板配置（M3，本地部分）

**Files:** 新增 `E/benchmark/analysis_export.py`、`T/benchmark/test_analysis_export.py`、`docs/benchmark/langfuse-dashboards.md`；修改 langfuse_export.py/cli.py 为显式新入口。旧 trace 导出行为与历史 ID 不变。

**Interfaces:** `build_analysis_payload(analysis: dict, *, projection_version: str) -> dict` 纯函数；`export_analysis(payload: dict, *, client: Any) -> dict` 显式注入 client；CLI export-analysis 默认为本地 dry-run，真实发送要求显式 execute 参数。

- [ ] 单元测试同源/同分析/同 scope 的 ID 稳定；analysis summary 不复制到每个 trial；重复导出不会创建重复 score；新分析版本产生可区分 ID。
- [ ] 白名单测试移除原始 prompt、私有依据、内部规则、绝对路径与凭据；fake client 回读不一致时只报导出失败，不回写本地 verdict。
- [ ] 实现本地 payload 与 schema 检查；没有可访问 viewer URL 时只保存本地 artifact 引用；SDK 缺失不影响 build_analysis_payload/import。
- [ ] 写总览/比较/下钻/失败四组看板的字段、过滤、聚合层级和样本量说明；雷达图不是必须能力，服务不支持时使用表格/柱图。通过 mock 测试提交 `feat(langfuse): export versioned analysis projections`，不宣称线上已验收。

### T12：完整工程验收与迁移交付（M3）

**Files:** 新增 `docs/migration/benchmark-complete-acceptance-<执行日期>.md`、更新 docs/README.md、相关安装/兼容说明；日志写忽略的本地 artifacts/verification 目录。

- [ ] 搜索旧实现调用，检查 thin wrapper 无重复算法，所有迁移源码在身份闭包中。逐项核对设计与本计划，未完成项目保留未勾选。
- [ ] 运行 Evaluator 全套及相关 Builder/contracts/root 回归、Ruff、verify_assets；隔离真实模型/托管相关环境变量，不通过放宽测试或改冻结资产消除失败。
- [ ] 全新 clone 建立独立 core 环境，pip check；无可选 SDK 导入、ExternalProvider、文件/SQLite 双域、新注释校验、离线 analyze/report/export dry-run 全链路通过。
- [ ] 验证断点恢复、取消、独立 worker、source drift、数据/注释篡改拒绝和旧 API/CLI。真实 Docker/可选 τ 未执行则明确 pending，不以复制输入检查替代。
- [ ] 独立代码审阅并修复确认问题；记录源码提交、依赖版本、测试、样本数、未覆盖项和状态。工程完成只覆盖 M1–M3，不替 M4 打勾。按已有授权本地集成，不自动上传托管服务。

### T13：人工、真实实验与托管交付（M4，独立验收）

**Files:** 新的不可变实验/标注/验证结果目录；既有空白样本和历史报告只读。交付记录引用源码、dataset、annotation、rubric、模型配置与原始证据 Hash。

**Inputs:** 指定实验对象及预算、人工评审安排、获准的托管目标。不得从“实施方案”推定真实 API 预算或代写人类标签。

- [ ] 人工完成开发试标、复核与标签锁定；输出真实覆盖率和分歧分析，不改名为独立验证。
- [ ] 预注册独立验证抽样、family/evidence 隔离、rubric/模型版本、候选阈值和验收线；由实际人工独立评审。没有事先批准门槛时只报告观测结果。
- [ ] 执行明确授权的重复实验；按选定 k 取得真实独立运行，报告缺失/INVALID 与实际用量。预算不足时缩小事先声明的实验范围，不以 Judge repeat 或 demo 凑数。
- [ ] 将已批准的脱敏 analysis 上传指定 Langfuse，验证 payload→服务端回读→界面抽查一致；四组看板可用，run 级指标无重复计数。
- [ ] 完成前核对每项状态；任何 pending 都在交付摘要显式列出。只有工程、目标实验、人工验证和指定看板分别满足预定标准，才能宣布对应范围的完整闭环完成。

## 自检与交付状态

设计各节映射：领域 T1；适配 T2/T3；评分 T4；注释 T5；分母/可靠性/成本 T6；失败 T7；报告与受控比较 T8；校准 T9/T13；领域/数据/污染来源 T10；Langfuse T11/T13；联合验收 T12。性能缓存仅在证据支持时另立任务，不是删除身份检查的理由。

新增代码步骤均有输入/输出与行为验收；文档中具体难度阈值、24 条初版规模和新的 provider 名称是可审查的技术提案，不是已存在的产品能力。
