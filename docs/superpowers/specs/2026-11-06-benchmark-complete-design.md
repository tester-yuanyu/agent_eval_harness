# Benchmark 完整改造设计

状态：待实施的完整方案；不代表下列新增功能已经交付。基线为 `04a1cc3`（包含结构整理 `979d84a` 和 Harness P1）。用户本次要求完整方案，本次只编写方案。

## 1. 目标、现状和方案选择

目标是让 Benchmark 独立定义“测什么、如何判定、如何比较”，让新领域和新 Agent 接入时无需改核心编排，并使每个报告结论可追溯到任务、执行、评分和分析版本。

采用渐进迁移：新实现进入明确的职责模块，旧 Python API、CLI、provider 名称和 worker 启动方式保留兼容门面。替换一条路径后验证等价，再迁下一条。整体重写会扩大历史身份和执行语义风险；只增加看板无法解决领域硬编码和分母问题。这是本方案的技术建议，不宣称用户已批准所有新增细节。

已完成：RunContext/InspectRuntime、比较移至 aggregator、file-tools 任务域、共享 JSONL/Hash 基础能力、reference 迁移、通用文件操作与 nanobot SDK 分离、新源码闭包。详见 [已有验收](../../migration/benchmark-boundaries-acceptance-2026-11-06.md)。

尚未完成：runner 的 file-tools 默认装配解耦、mode adapter 拆分、tau/mini/core 归位、scorer 实现进一步收敛、版本化标签、通用可靠性/效率分析、失败归因、分析报告、校准闭环、可视化交付和覆盖缺口数据集。

现有能力继续复用：DeepEval 正式确定性评分，三个 GEval 诊断维度及原生 Agent 指标，all_trials_pass_rate、token/费用与延迟汇总，mini-agent SQLite 领域，τ 集成，人工盲标页面与比较工具。

## 2. 不变约束

- Inspect 执行与记录，DeepEval 承载正式确定性评分，GEval/native LLM metrics 仅诊断，Langfuse 展示本地保存结果。
- 模块、模型决策、关键链路、端到端分母分别计算；不发布跨层“模型总成功率”。
- 任务、manifest、历史结果和参考能力资产冻结；新数据、新评分规则、新 rubric 都发布新版本，不覆盖历史字节和 Hash。
- 私有 Oracle、reference、checkpoint、标签依据及校准标签不进入执行输入和模型消息。
- runtime、参考能力、数据、评分、分析身份分别记录；运行中源码/配置漂移仍拒绝。不能以缓存优化删除漂移检查。
- Agent 集成可选；无 nanobot、minimal_agent、Langfuse 时核心和 ExternalProvider 可用。Builder 的通用验证只依赖 contracts，不引入 Evaluator。
- 保留独立环境、worker 隔离、超时取消与清理。原生 nanobot loop 和自研 Harness 是明确不同的执行路径。
- 测试和 demo 不调用真实模型、不上传托管服务。真实实验和托管交付按明确授权的范围、预算与目的地执行。
- 中文维护说明；保留七项问题清单、语言/冻结边界、复现协议、历史限制和未解决项。

## 3. 目标职责

| 位置 | 职责 | 不承担的职责 |
| --- | --- | --- |
| contracts | 中立任务/证据、注释、分析结构及校验 | Agent SDK、Inspect/DeepEval 运行时 |
| benchmark/datasets | manifest 分发、读取和注释绑定 | 执行代码、宽松吞掉未知版本 |
| benchmark/domains | 公开输入投影、领域规则、可信评分接入 | sandbox 生命周期、AgentLoop |
| integrations/{nanobot,mini_agent,tau} | 可选 SDK、模式适配、独立 worker | 通用统计、正式报告口径 |
| environments | 文件/数据库/工具环境、快照与边界约束 | 私有答案投影 |
| harness + orchestration | 运行循环、Inspect 调度、生命周期 | 新增业务分类规则 |
| benchmark/scorers | 确定性指标、reference、GEval/native Judge、评分证据 | 运行任务、绘图、统计分母 |
| aggregator | 稳定性、效率、分桶、比较、失败统计 | 重跑 Agent、从 Langfuse 获取判定 |
| benchmark/report + 新分析渲染模块 | 本地 JSON/Markdown/HTML 分析 | 修改历史结果 |
| benchmark/langfuse_export | 版本化、脱敏、幂等导出和一致性验证 | 生成正式 verdict |

### 3.1 领域与编排

保留 BenchmarkDomain 的 identity/execution_task/score_task 契约。新增独立 DomainPresentation（可信注册实现）提供 task_name、prepare_sample(public_task)，返回 SampleSpec(input, files, metadata)。输入必须先经过 execution_task，禁止把完整私有 task 交给 Sample 构建层。

FileToolsPresentation 承担现有 fixtures 转换和 file_tool_benchmark 名称；普通 ProviderPresentation 不要求 fixtures。runner 使用 SampleSpec 创建 Inspect Sample，sandbox 仍来自 adapter。旧 domain 对象继续通过兼容 presentation 使用；新领域显式注册，不从任务数据 import Python。默认 file-tools CLI 行为保持。

离线 reference 仅作为显式 reference_smoke_only 路径，名称和结果中保留声明。自定义领域 demo 通过注册的离线 adapter 执行，不让 Domain 接管 runtime。HARNESS_VERSION 是执行实现身份，不能简单从 dataset manifest 读取。

统一 load_dataset 分发只选择已注册的严格合同 loader，返回原始 tasks、legacy_identity 与 DatasetDescriptor，不把不同任务格式强行转成宽松结构。DatasetDescriptor 提供 domain_id、contract_version、task_name、supported_modes、公开工具与类别列表；旧合同从可信代码生成兼容描述，新资产可从受校验的外置描述读取并绑定 Hash。

已冻结契约中的工具枚举、类别和校验规则先保留在其领域实现；新数据集描述允许通过受校验的外置 domain descriptor 提供公开类别/工具配置。不能把任意 Python 规则全部替换成 YAML，也不能改旧 manifest。

### 3.2 Adapter、worker 和集成迁移

拆出 NanobotModuleAdapter、NanobotDecisionAdapter、NanobotAgentAdapter，分别注册显式 provider ID nanobot_module/nanobot_decision/nanobot_agent；模式不匹配在执行前拒绝。provider=nanobot 与 NanobotAdapter 别名继续是兼容 facade，分发到相应实现，保留旧记录中 provider_id。

core 属于 nanobot 的组件域与组件 worker，不作为独立外部 benchmark：core_tasks/core_scoring 归 domains/nanobot_core 与 scorers，core_worker 归 integrations/nanobot。mini 的数据构造归 domains/provider，SDK/worker 归 integrations/mini_agent；τ 的领域规则、官方依赖与 worker 归 integrations/tau。旧入口留转发；worker shim 要能作为脚本和扁平 Docker bundle 导入，不能依赖先安装 Evaluator。

每套集成独立迁移并验证 pin、stdin/events/observation、错误/超时/清理和源码身份。没有等价证据的 worker 不删除，也不批量放入 deprecated。harness.loop 的兼容调用只有在全部调用方和恢复/取消行为有替代测试后才弃用；完整 nanobot 不强制走 harness_solver。

身份检查先测量耗时。可缓存一次解析后的文件清单和不可变声明，动态源码/配置仍校验；真正采用不可变运行快照才可另行优化重复 Git 查询，不作为本轮必须上线的性能功能。

### 3.3 Scorer 收敛

正式指标实现从 metrics.py 归入 scorers/deterministic.py；GEval 引擎、版本化 rubric、DeepEval 模型客户端分别归 scorers/trajectory_judge.py、rubrics.py、judge_client.py；原生诊断与其 worker 随同迁入 scorers。旧 metrics/judging/agentic_metrics/oracle 作为薄兼容门面。先保持评分、理由、证据引用、请求预算和 rubric 内容等价，不在搬文件时调判定。

新诊断统一输出 metric_id/name/version/formal/status/value/evidence_refs；沿用已有契约的正式记录不重写。formal=false 的记录不能通过聚合覆盖正式 verdict。只评价可观察动作、恢复与回复证据，不评价不可观察的内部推理。

## 4. 注释资产和覆盖

新增独立资产 `data/benchmark-annotations/<dataset-id>/<version>/`，包含 manifest.json、annotations.jsonl 和 taxonomy.json；不增加 v3 capability bundle 内文件。

注释键为 dataset_sha256 + case_id。这里 dataset_sha256 是新建 DatasetBinding 的规范 JSON Hash，不重解释任何旧字段：binding 包含 binding_version=dataset-binding-v1、原 loader 返回的 legacy_identity、manifest 原始字节 SHA-256，以及该合同规定的全部任务/引用资产的相对路径→原始字节 Hash。加载时先按原合同验证，再构造 binding；file-tools/core 至少包含 tasks.jsonl，Provider 包含其 manifest.files 的完整闭包。使用 contracts 现有 sha256_json 算法，禁止绝对路径进入 binding。相同 tasks 配不同 manifest/contract 得到不同 binding。

分析时 source_run.identity.dataset 必须与 loader 的 legacy_identity 完全一致，旧任务 Hash/引用闭包必须通过原校验，再匹配 annotation 的 binding。历史 run 没记录 manifest 字节 Hash 时，记录 historical_manifest_bytes_verified=false：当前 manifest 字节已绑定到新分析，但不能声称证明了原执行时 manifest 的字节形式。

manifest 绑定 dataset_id/contract_version/taxonomy_version/annotation_version、annotations.jsonl 和 taxonomy.json 的各自原始字节 Hash、规则源码身份、来源和审查状态。版本字符串相同而内容不同必须拒绝。AnnotationSet.content_sha256 是由 manifest/annotations/taxonomy 三份原始字节 Hash 构成的规范对象摘要；manifest 不包含自己的 Hash，避免自引用。相同版本不可覆盖。原始记录包含 capabilities、difficulty、structural_features、basis_refs、review_status；公开报告只投影非敏感标签，不输出私有依据。

能力 vocabulary v1：single_tool、multi_tool_selection、tool_sequence、parallel_calls、irrelevance_rejection、schema_robustness、multi_turn_state、error_recovery、policy_compliance。业务 category 保留。一个任务可属多个桶，桶间不可加总为总数；领域、执行层、split 与能力维度独立。

标签表示任务明确要求什么，不根据某模型是否调用工具倒推。只有任务合同实际允许且检验并行调用时才标 parallel_calls；schema_robustness 要有配对扰动协议。没有证明的标签保持 proposed 或 unknown；正式分桶默认只用 reviewed 标签，同时报未标注任务数。初始启发式分类只能提交 proposed，人工确认之前不能冒充已审标签。

难度 v1 是“结构复杂度”而非普适模型难度。四个特征为 reference_tool_calls、dependency_depth、interaction_turns、recovery_branches。参考路径长度不宣称最短必要调用数。特征缺失为 unknown；已知时：任一 reference_tool_calls>=7、dependency_depth>=4、interaction_turns>=3、recovery_branches>=2 判 hard；否则 calls<=2、depth<=1、turns<=1、branches=0 判 easy；其余 medium。这些是待人工校准的版本化启发式，阈值变更生成新注释版本。按固定 baseline 的经验成功率另存诊断，不改变结构标签；不引入难度加权正式总分。

能力覆盖矩阵至少含：适用、已设计任务、已冻结、已执行、有效证据、已评分的任务/任务族数量。未覆盖与不适用分开；框架安全单测不得计入 Agent 能力覆盖。

## 5. 分析身份与统计口径

新增独立 `analysis.json`，不覆盖 results.json 或已有 summary。analysis identity 绑定源结果字节 Hash、数据集身份、评分/运行身份、annotation/taxonomy Hash、analysis_version、统计策略与工具源码 Hash。相同源和配置应生成相同内容；生成时间放不参与内容身份的外层交付记录。分析是只读，不运行 Agent/Judge。

analysis 默认处理一份真实执行结果；不自动拼接不同 run，不把复评或 Judge repeat 当执行重复。

入口与 lineage 规则：

1. `--run` 接受原始 execution results，或正式 regrade results。regrade 必须通过重复的 `--source-artifact <results.json>` 显式提供其完整来源链，按 source_results_sha256/source_identity_hash/source_trial_sha256 验证每条边、检查无环并验证到原始 execution；不自动跟随 provenance 中的本机绝对目录或网络地址。
2. 原始 execution 的 planned_case_ids、trials_per_case、execution identity 和 observation 定义总体；选择的 --run 中正式 scoring identity/assessment 定义本次判定。regrade 不增加 trial，也不能新增/删除计划任务或改写 observation。canonical trial key 为 execution_run_id + execution_identity_hash + case_id + trial。
3. `--run` 为 judge_saved_evidence 时拒绝并提示使用原始/正式 regrade 源；可用独立 `--judge-source` 附加诊断。Judge 的 limit 子集只决定诊断覆盖率，不改变执行计划分母。附加 Judge 来源也须验证 Hash 链与 canonical trial key。
4. 来源文件缺失、Hash/identity/observation 不一致或 lineage 无法验证时，正式 analyze 拒绝并给出缺失来源清单；不静默回退为新执行。比较同一 execution 的不同 regrade 必须标 scoring_only，禁止将其汇总为多次独立运行或模型能力变化。

reference/demo 只输出明确标记的框架验收视图，不进入 Agent 成绩。旧 compare_runs 严格条件保留；横向分析若允许 model/runtime 为变量，必须有预先指定的 ExperimentSpec：control_fields、variable_fields、计划 case/trial、环境重置与随机性策略。未声明的身份差异拒绝，合法变量也必须显示；不同系统控制项无法统一时分栏陈列，不给受控差值。

### 5.1 成功率与 pass^k

沿用 planned/valid 两个分母和 INVALID/INCONCLUSIVE/MISSING 状态，不把运行成功当评测成功。各桶计划分母从任务选择和注释确定，不能从已观察成功记录倒推。任务实例 micro 与任务族等权 macro 分开，macro 不取代现有指标。

新增 pass_hat_k：对每题 n 次独立、相同协议的真实运行，有 c 次正式 PASS，估计值为 comb(c,k)/comb(n,k)，再按任务等权平均；c<k 为 0。k 必须为正整数，默认请求 1、3、5，不改变 runner 目前 1–5 repeats 限制；k>n 返回 insufficient_trials 而非 0。必须声明重复协议，否则只能显示 descriptive_not_verified_independent。

若计划总体存在缺失或 INVALID，主要 pass_hat_k 返回 unavailable_incomplete_population，仍报告计划、完成、有效和失败数量；不悄悄剔除不完整任务。可选 eligible_subset 诊断明确标记条件总体及排除数。有效 INCONCLUSIVE 计为非成功，单独披露数量。all_trials_pass_rate 保留原有“所有计划 trial 均 PASS”的保守口径；它在 n=k 且完整有效时对应 pass_hat_k 端点。复评若复用原 execution evidence 只分析该执行一次。

本版不给未经设计的统计显著性结论。未来区间估计以任务族为聚类单位，另行冻结抽样规则；避免把同族变体当独立样本。

### 5.2 成本、效率与长度

分别输出全体有效/已保存样本描述、成功样本条件均值和总尝试成本/成功数。后者只有计划执行完整且相应字段全已知时才给主值；否则为空并报告 known_subtotal、known_count、planned_count。零成功、空总体返回 null，附原因。

统计 input/output/total/cached token、cost_usd、latency_seconds、tool_calls、generation_calls；定义从已保存事件提取的方法和覆盖率，不推断不存在的 usage。布尔值、NaN、无穷、负数不是合法费用/计数。Agent、Judge、用户模拟器分栏；同一调用的别名不重复相加。延迟沿用记录的 scope，旧口径不混算。

三轴展示采用结果质量、可观察输出长度、成本；verbosity 为描述性字段，不默认越短越好，不合成任意加权总分。

### 5.3 失败归因

先用结构化错误、评分检查与事件证据进行确定性归类，输出 domain（agent/infrastructure/scoring/unknown）、primary、secondary、rule_version、evidence_refs。错误标签包括 unknown_tool、invalid_arguments、workspace_policy_violation、state_mismatch、checkpoint_violation、timeout、runtime_error、evidence_missing、judge_error、unknown；没有证据保留 unknown。

优先识别 INVALID 的基础设施/证据问题，再定位正式 FAIL 的首个决定性检查；工具失败但后续成功恢复的 PASS 不计为失败，只记 recovered_error 诊断。路径被环境拦截不自动证明 Agent 安全；拒绝任务按自己的成功条件判定。LLM 聚类不进入本版必交范围。

## 6. 本地报告和 CLI

新增 `benchmark analyze --run ... --annotations ... --output ... --k 1 3 5`，默认无网络。任务计划信息不足以构造分桶分母时要求显式数据集路径，不能猜测。输出 analysis.json、analysis.md、analysis.html 和 provenance.json。

报告包含：逐层成绩/完成率、能力与难度分桶（分母/未标注数）、pass^k/现有严格稳定性、成本与长度、失败证据、比较控制项、历史限制与复现入口。已有 report/compare 的默认文件与返回格式保持，新报告显式选择。错误案例必须能定位 run/case/trial/evidence；复现命令只引用本地配置模板或环境变量名，不嵌入密钥、原始私有 prompt 或未经转义的外部文本，不自动执行。

## 7. 人工校准闭环

保留三个 GEval 维度和当前请求预算。36 条样本继续是开发试标，不改名为独立验证。工具支持盲标、标签锁定、双人分歧复核、版本化仲裁记录、来源/独立性审核状态；机器不填写 human gold。

分别报告人工间一致性与人工-Judge 一致性、MAE、阈值混淆矩阵、误放/误杀数及分母、标签/配对覆盖率。Cohen κ 仅用于声明了分类或固定有序分档的分析；单一类别导致期望一致率为 1 时返回 undefined，不伪造 1。0.7 不设为统一门槛。

rubric/证据选择修改升 JUDGE_VERSION 与 rubric Hash。阈值探索使用开发标签；独立验证必须 family 和 execution evidence 都不重叠，揭盲前冻结模型、配置、代码、抽样、阈值和门槛。缺少真实独立标签或事先批准门槛时状态为 pending_human_review / pending_independent_validation，不宣称已校准。即使完成校准，本方案也不自动授予 Judge 正式判定权。

## 8. 领域与鲁棒性扩展

先用已有 mini-agent SQLite 任务证明新领域无需改 runner/aggregator，保留自身合同、参考能力与正式 scorer。用 ExternalProvider 离线合成 PASS/FAIL/INCONCLUSIVE 和真实本地 SQLite 状态变更验收；这些结果只证明框架链路，不能宣称真实模型能力。τ 的官方域是单独可选集成，官方 pin 不变。

新增独立 `file-tools-robustness-v1` 开发集：初版六类各 2 个任务族、每族 2 个参数实例，共 24 个实例。六类是无适用工具、未知工具诱导、路径穿越/符号链接边界、参数特殊字符的字面处理、可恢复工具错误、多轮状态/规则冲突。每题有确定性成功条件、失败证据要求与可信参考；不接受“没有调用工具即安全”的笼统 Oracle。路径穿越和正常带特殊字符的输入必须区分授权边界，避免以安全名义错误拒绝合法任务。24 是初版工程预算，不宣称覆盖充分或占现有任务固定比例；全部是 dev，不伪造未见 holdout。

并行/schema 变换先登记覆盖缺口。只有 Harness/adapter 已支持真实并行语义、schema 变体身份和顺序比较契约后，再构建独立扩展版本，比较最终状态/决策漂移；原始任务的元数据不能代替这些实验。若现有 SQLite 和τ仍不能证明某项领域无关契约，再增加新领域，而非强制另造零售任务。

污染防护先建立任务来源、生成/人工修改、公开日期、访问范围、模板/家族去重记录；只声明做过哪些检查及其局限。私有文本不自动外发检索，公开模板的抽样检索也不能证明未进入训练语料。历史已参与开发的 holdout 保留事实说明。

## 9. Langfuse 交付

以 analysis.json 为唯一新增分析来源。导出白名单包括 run/case/trial、execution_level/domain/runtime、数据/评分/分析/注释身份及公开分桶。默认不导出 raw prompt、内部规则、reference、标签依据、绝对路径或凭据。版本化导出规范与现有导出策略隔离；新模块纯函数构造 payload，client 延迟导入。

case/trial 的分数留在对应 trace；run 级 pass^k 不复制到每个 trial 后再平均，使用单独 analysis summary 记录，稳定 ID 绑定 source_hash+analysis_hash+metric+scope。重传幂等；回读只验证传输一致性，不能反向覆盖本地结果。

看板四组：分层总览、受控实验比较、证据下钻、失败原因。趋势只连接控制项兼容的实验；未知和样本量可见。先交付本地 payload/schema/配置说明与 fake client 测试，再按授权做真实导出、服务端回读与界面抽查。Inspect viewer 只有存在可访问且获准的 URL 才生成远端链接，否则给本地 artifact 引用。

## 10. 分工、里程碑与完成判定

Benchmark 任务负责 domain/dataset/scorer/aggregator/report/analysis/export；Harness 任务负责循环、并发、停止、取消、工具执行和证据采集。AgentAdapter 协议、composition 注册、shared contracts、SampleSpec 边界及新增 trace 字段为共享修改：先约定字段与文件所有者，再单方落代码，另一方消费；禁止双方同时编辑。

当前另有 Environment 任务使用 workspaces/environment-refactor / codex/environment-refactor，负责 environments/**、harness/core/tool_router.py 契约及相关 Harness 导入、integrations/nanobot/environments/**、integrations/nanobot/sources.py。本轮方案不修改这些产品文件；实施 T1/T2/T3 时先吸收其完成的公共契约，sources.py/bundle 清单由协商后的单一所有者修改，不回迁或覆盖新的 Environment 实现。

- M0：已完成基础结构整理；不会重复计为本方案新增交付。
- M1：领域编排、模式适配和评分职责收敛；集成逐一迁移；兼容和隔离验证通过。
- M2：注释、指标、失败归因、本地报告完整离线可用，历史字节不变。
- M3：校准工具、SQLite 泛化验收、新鲁棒性 dev 集、Langfuse 本地导出和看板配置交付。
- M4：按授权完成真实重复运行、人工独立验证和托管看板验收；未具备数据/人力/预算时明确 pending，不影响报告工具工程验收，但不能说完整业务闭环完成。

工程完成必须包含：每项任务可追溯提交、回归、完整源码闭包、冻结资产检查、无可选包的全新安装与 demo、独立代码审查、迁移说明与已知限制。目录更整齐、测试数增加或离线 demo PASS 都不能单独代表评测能力完成。

## 11. 方法来源

- 仓库 [指标规格](../../benchmark/metric-specification.md)、[人工校准指南](../../benchmark/judge-annotation-guide.md)、[职责边界验收](../../migration/benchmark-boundaries-acceptance-2026-11-06.md)。
- [τ-bench pass^k 定义](https://arxiv.org/html/2406.12045v1)：只采用其可靠性定义，不宣称本数据可与官方榜单直接比较。
- [BFCL 分类参考](https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html)：用于 vocabulary 映射，非统一行业标准。
- [Langfuse Custom Dashboards](https://langfuse.com/docs/metrics/features/custom-dashboards)：实际交付验证目标服务版本的支持能力，不假定任意图表或聚合均可配置。

## 12. 对最初结构建议的逐项处置

| 原建议 | 最终方案 |
| --- | --- |
| nanobot SDK 从 benchmark 移出 | 已完成基础迁移；T2/T3 收敛剩余适配/worker，环境实现归 Environment 任务 |
| inspect_runtime 强制只走 harness_solver | 不强制统一原生 Agent 与组件循环；通用装配 T1 解耦，旧调用按证据逐路径替代 |
| 删除 runner 手工源码清单 | 已提取 identity 并补 layer_sources；保留历史标签兼容，新实现闭包强制覆盖 |
| 删除 oracle.py | 实现已迁出，旧入口保留薄转发，T4 完成评分实现收敛 |
| NanobotAdapter 拆三类 | T2，兼容 facade 与显式模式 provider 并存 |
| tasks 常量全部改 JSON/YAML | 旧合同规则留在领域模块；新公开域配置使用受校验 descriptor，禁止执行代码混入数据 |
| tau/mini/core 全移 adapters | T3 按 SDK/worker、领域数据、可信 scorer 分别归位，不把三类职责换目录后继续混放 |
| worker 全部归档 | 保留有隔离意义的 worker；没有等价替代不删除 |
| compare_runs 移 reporting | 已移 aggregator，旧入口兼容 |
| _run 参数封装 | 已完成 RunContext/InspectRuntime |
| BenchmarkDomain 用起来或删除 | T1 保留可信评分/公开投影，补独立 presentation；sandbox/loop 继续由 adapter/Harness 负责 |
