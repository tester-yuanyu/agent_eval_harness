# DeepEval Synthesizer 接入

Builder 新增可选的 `deepeval` 生成后端，默认仍为 `openai`。DeepEval 生成待审语义候选，已有 Builder 负责能力契约、覆盖计划、编译、校验、审核和冻结。

## 支持范围

- 按 coverage plan 每个槽位生成一条单轮候选。首轮使用 v2；约束修复使用独立的 `mini_agent_query_user_intent_v3`，仍为 42 个槽位，保留 v2 和首轮失败记录。
- 候选协议必须包含 `rule_refs`，每个槽位必须声明规则和 `scenario_type`。现有无规则引用的 v1 套件会明确拒绝。
- 可用于同类单轮 intent 套件；此次没有把 `generate-full`、`generate-nanobot` 的独立候选协议转换成 DeepEval 输入，也没有新增多轮 Agent 执行器。
- 原 mini_agent、nanobot 历史交付不变，已有阻塞项不会因接入生成器而消失。

## 完整流程

```text
prepare：受信任快照 → Capability IR + 来源清单 + 覆盖计划 + request
  ↓
generate --backend deepeval
  校验 request 与当前来源、候选 Schema、覆盖计划的绑定
  → IR 和允许的来源文件（不含整张覆盖计划）+ 当前槽位
  → Synthesizer.generate_goldens_from_contexts
  → Golden(input, expected_output)
  → expected_output 严格解析为 Candidate JSON
  → 核对原始 input、slot、intent、status、scenario_type、rule_refs
  → 逐候选契约校验 + 槽位 acceptance 谓词检查
  → 可选有限次重新生成，保留每次原文与拒绝原因
  → 原有 Candidate parser → 确定性编译 → draft.jsonl
  ↓
validate：格式、契约、覆盖、重复、泄漏、质量、来源时效性
  ↓
review：人工检查输入与预期的语义对应、业务合理性、关键场景
  ↓
freeze：校验通过 + 与 draft hash 绑定的审核批准 → 不可覆盖的版本
```

`expected_output` 要求模型针对**本次生成的 input**输出完整 Candidate JSON；不会读取 seed_catalog、复制种子答案或把普通自然语言回答直接当 Oracle。缺少预期、无依据返回 null、非 JSON、字段越界、规则/槽位漂移会拒绝，不自动修补。生成成功只代表候选通过已配置的确定性检查；最终自然语言语义是否正确，仍需独立初审与人工审核。

v3 将 `policies/validation.json` 和 `authoring_constraints.md` 显式加入 source pack，以哈希绑定到 request。覆盖计划启用 `scenario_requirements_version=1.0`，42 个槽位各自声明 `acceptance`：输入必须/不得包含的模式、输出字段集合、边界值、值出现次数、不同值数量、纠正时最终值和参数接地检查。每条必须引用实际 Capability IR JSON pointer；未知字段、非法正则、失效来源在模型调用前拒绝。覆盖门禁也执行同一套检查，不能通过手工导入绕过。

这些条件是有限的测试选择标准，不是对任意中文语义的完整判定器。来源指针存在也不自动证明所有预期成立；契约未规定的分支仍应阻塞审批，不能从旧种子答案补出规则。

Python API 可设 `DeepEvalGenerationClient(suite=suite, model=model, max_slot_attempts=3)`；默认 1 次，上限 10 次。候选被拒绝时，根据校验诊断重新生成完整输入和预期，不修改原答案。成功后的 `metadata.attempt_audit` 保留所有尝试；耗尽预算或 SDK 异常时，pipeline 写入 `generation_failure.json`，不创建可编译草稿。SDK 自身网络重试与此槽位预算是两层不同机制。

适配器 `deepeval-slot-v3` 在接受输入前按大小写、空白和标点归一化去重，已接受的普通候选和无 Oracle 输入共同参与比较。重复项消耗同一个槽位重试预算，原始 Golden 和拒绝原因保留；首次接受的内容不会被覆盖。此检查不等于语义近重复识别。

## 安装与运行

在已满足本项目及相邻 `agent_evaluator` 依赖的环境中安装可选依赖：

```bash
python -m pip install -e '.[deepeval]'
```

固定 SDK 为 `deepeval==4.3.2`，其他版本明确拒绝，升级需要重新验证 SDK 契约。默认后端不导入 DeepEval。

显式设置 `OPENAI_API_KEY` 与 `DATASET_GENERATOR_MODEL`。CLI 使用 DeepEval 的 `OpenAIModel`，不隐式选择默认模型。密钥不写入生成清单。Python API 也接受 `DeepEvalBaseLLM` 自定义模型。

```bash
python -m dataset_builder.cli prepare \
  --suite mini_agent_query_user_intent_v3 \
  --workspace workspaces/query_user_deepeval_run_01

python -m dataset_builder.cli generate \
  --backend deepeval \
  --request workspaces/query_user_deepeval_run_01/generation_request.json \
  --workspace workspaces/query_user_deepeval_run_01

python -m dataset_builder.cli validate \
  --suite mini_agent_query_user_intent_v3 \
  --draft workspaces/query_user_deepeval_run_01/draft.jsonl

python -m dataset_builder.cli review \
  --suite mini_agent_query_user_intent_v3 \
  --draft workspaces/query_user_deepeval_run_01/draft.jsonl \
  --output workspaces/query_user_deepeval_run_01/review.md
```

这里的 `generate` 会调用付费模型；接入验证只使用离线模型。每槽位包含输入生成、评分、样式转换和预期生成等 SDK 调用，不等于“一条 case 一次请求”。不会执行被测 Agent，也不会调用其业务工具。

每次生成使用新 workspace。既有 stage ledger 会拒绝在已记录 generate 阶段的目录重跑，包括失败阶段；修正后重新 prepare 到新目录。不会默默回退至 OpenAI 后端或使用种子补足条数。

## 约束与配置

当前适配器固定配置并记录在原始响应中：

| 项目 | 设置与原因 |
| --- | --- |
| 并发 | 同步逐槽位，避免返回结果串槽 |
| 数量 | 每槽位恰好 1 条；空结果/多结果均拒绝 |
| 演化 | 0 次，防止增加能力契约之外的事实或约束 |
| 通用质量过滤 | 阈值 0、评分 1 次，保留刻意缺参/歧义；该评分不作为本地门禁通过凭据 |
| 样式转换 | 明确要求保留缺参、无效值、歧义；是否遵守仍需后续验证和人工审核 |
| 预期 | 严格 Candidate JSON，生成依据必须来自上下文契约 |
| 遥测 | 导入 SDK 前默认设置 `DEEPEVAL_TELEMETRY_OPT_OUT=1`；不自动登录或上传 Confident AI |

本地校验不等于完备的 LLM 语义证明，DeepEval 的评分也不是契约正确性判定。本次没有新增 LLM-as-Judge，更没有自动勾选人工审核。覆盖仍以显式计划为分母，不能声称覆盖所有可能的自然语言场景。

## 追溯与版本

- `raw_response.json`：标准 candidates、原始 Golden input/expected_output/context/metadata、适配器版本、SDK 版本、实际模型名、生成设置、上下文哈希，标记 `oracle_status=unreviewed`。
- `generation_manifest.json`：沿用快照/IR/策略/覆盖计划绑定，新增生成器 metadata 与原始响应文件哈希。编译前检查保存的原始响应与传入对象一致；验证和冻结路径检查原始响应哈希，DeepEval 缺少该绑定时拒绝。旧版 manifest 未声明该字段时保留兼容。
- `draft.jsonl`：仍是现有 evaluator 可读取的格式。人工审核与冻结沿用原流程；本次不自动执行冻结。
- 新 Agent 能力、策略或新生成器版本应使用新工作区和新数据集版本。历史冻结版本不被覆盖，基线对比仍基于同一冻结集合。

## 验证

`tests/test_deepeval_generation.py` 包括坏格式/数量/槽位/规则漂移、过期请求、缺少依赖或模型配置、CLI、编译与门禁，以及**真实 Synthesizer + 离线 DeepEvalBaseLLM**的 42 槽位契约测试。真实 SDK 测试禁止网络连接，输入和预期使用固定测试 fixture，仅用于验证接口而非展示生成质量；未安装可选依赖时该测试跳过，其余后端单元测试仍可运行。

```bash
DEEPEVAL_TELEMETRY_OPT_OUT=1 PYTHONPATH=src python -m pytest \
  -p no:rerunfailures tests/test_deepeval_generation.py -q
```

实际模型的自然语言质量、审核通过率、成本与耗时，需要后续真实生成实验测量，此次不作效果提升承诺。

2026-10-28 接入验证：项目 `.venv` 已安装 SDK 4.3.2，新增 24 项测试通过；安装 SDK 的全仓回归 270 项通过，Ruff 与 `pip check` 通过。独立审查提出的配置哈希和原始 Golden 证据绑定缺口已修复并复核通过。对 mini_agent、nanobot v2/v3 历史交付的 806 个文件核对 SHA-256，无新增、删除或内容变更。以上均为离线工程验证，没有运行付费生成或被测 Agent。

未安装 DeepEval 的相邻环境也完成兼容回归：269 项通过，仅真实 SDK 契约测试因可选依赖不存在而跳过；该测试在已安装 SDK 的项目环境再次执行通过。

API 依据：[官方 Synthesizer 文档](https://deepeval.com/docs/golden-synthesizer)、[从 contexts 生成](https://deepeval.com/docs/synthesizer-generate-from-contexts)，并核对 PyPI 4.3.2 SDK 源码。

## v3 契约缺口与发布阻塞

目前 IR 只列出 `missing_parameters` 的允许值和部分澄清语义，没有逐分支的精确数组映射。v3 的 17 个澄清槽位因此声明 `acceptance.oracle_gaps`。已知缺口的槽位调用 SDK 时设置 `include_expected_output=False`，只生成输入，不请求或保存猜测的预期。其余有定义的槽位继续生成。最终 coverage 门禁对每个缺口硬阻塞，人工批准不能绕过校验。补齐 Agent 来源契约并建立新套件版本后，才可重新生成、审核和冻结。

这与一次候选因格式/场景错误而重生成不同：重新调用模型不能补出来源契约。`candidate_issues` 负责可确定的逐候选错误；发布门禁另外检查未解除的契约缺口。生成遍历结束后若仍有缺口，会以 `SynthesisBlocked` 写入 `generation_failure.json`：状态 `CONTRACT_BLOCKED`，包含 `partial_generation` 中的25条候选、17条 `blocked_slots` 输入及所有审计记录。它不会写出 `raw_response.json` 或完整 `draft.jsonl`；不能伪装成完整评测集。
