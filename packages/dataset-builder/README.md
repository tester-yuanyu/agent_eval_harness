# Agent Dataset Builder 数据集生成

Monorepo 安装、环境和离线演示请先阅读 [根目录 README](../../README.md)。
下方历史 Suite 内的项目相对地址由兼容解析器映射到当前仓库目录；无需恢复旧同级项目布局。

这是一个独立、可复用、由人工审核把关的 Agent 评测集生产框架。Builder 不运行
被测 Agent，也不根据 Agent 的实际回答反推标准答案。

## Capability Bundle 架构

```text
独立 Capability Bundle 目录
→ 安全内核校验
→ 内置可信 Profile 与 Schema 绑定
→ 唯一 Capability Adapter 确定性转换
→ Capability IR
→ Suite + 六类 Policy
→ Coverage Slot → EvalCase
→ 自动校验 → 人工审核 → 显式冻结
```

Builder 只接收 Agent 导出的完整能力包目录，并固定以目录内的 `agent.json` 为根
入口；不查找或依赖 `bundle_manifest.json`。v1 Suite 保留
`mini_agent/capabilities/` 用于复现旧冻结产物，v2 Suite 使用
`mini_agent/exports/trace_v1/`，但公共流水线不 import `mini_agent`、不调用 Agent
CLI、不读取源码、Prompt、YAML 或 `capability_specs/`，也不依赖 PyYAML。

协议兼容由两类机器制品提供：

- `protocol_profiles/`：由 Builder 内部定义可信 Schema Hash、引用字段和 Hash 算法；
- 唯一的 `capability_adapter` 插件：将 Agent、Scope、Chain、Module、Intent、Tool、
  Evidence、Boundary 确定性转换为 Builder 自有的 Capability IR。

Suite 不选择 Profile、Adapter 或协议版本。Builder 内部校验 Bundle 中所有快照的
`snapshot_format_version` 必须为 `"3.0"`，并在生成产物中记录实际 Profile、Schema
与 Adapter 绑定用于追溯。

安全内核负责路径、Schema、单文件 Hash、引用、闭包、DAG 和 Bundle Hash。此类错误
直接拒绝，不能降级为 `unknown`。只有合法 Bundle 中无法映射的能力事实才记为
`unknown`；显式不支持记为 `unsupported`；全部必需声明与 Evidence 完整时才是
`supported`。

公共生成、编译和校验代码只读取 Capability IR，不读取原始快照中的业务字段。
Suite 和 Policy 可以选择评测范围、覆盖要求及生成规则，但不能提升或改写 Agent
能力事实。

## 生命周期

```text
prepare → generate/ingest → compile → validate → review → approve → freeze
```

自动流程最多推进到 `VALIDATED`。能力包、Profile、Schema、Adapter、Capability IR、
Suite 或 Policy 变化后都应重新准备草稿；当前自动 `STALE` 检测主要覆盖能力与实现绑定，尚未逐项重算全部策略和来源，详见[实现边界](AGENT_DATASET_CONSTRAINTS.md#11-需要明确保留的实现边界)。冻结要求：

- 全部 Gate 通过；
- 审核清单逐条勾选；
- reviewer 非空；
- 审核文件与草案 Hash 一致；
- 当前 Capability provenance 与生成时完全一致；
- 输出文件不存在，禁止覆盖。

## Suite 与 Policy

每个 Suite 的 `suite.json` 只装配：

- Bundle 路径与 Bundle Hash；
- Scope/Chain、Intent 和可选 Tool；
- 数据集元数据与执行 Profile；
- 六类 Policy 引用。

六类 JSON Policy 分别是 Source、Coverage、Generation、Validation、Review、Freeze。
候选枚举、编译规则、断言、校验 Gate 和覆盖统计均来自 Schema 校验后的 Policy；
说明性 Markdown 不指定可执行代码；Suite 显式列入来源包的约束文本仍属于需绑定 Hash 的生成输入。

## 开发与校验

需要 Python 3.11+。Builder 不需要安装 mini_agent：

```bash
make setup  # 在 monorepo 根目录执行
(cd packages/dataset-builder && ../../.venvs/builder/bin/python -m pytest -q)
.venvs/builder/bin/python -m ruff check packages/dataset-builder/src
```

Builder 依赖 `agent-eval-contracts`，不依赖 evaluator 或 Inspect。DeepEval 为显式安装的可选扩展，默认环境相应 SDK 测试会跳过。

Wheel 包含可信 Profile、Schema、Policy 和 Suite 配置。内置 mini_agent Suite 还需要此仓库的例子能力包及数据集目录；独立使用请通过 `load_suite_from_path` 加载显式引用输入文件的自定义 Suite。Builder 的 Capability IR 始终留在本包。

## CLI

以下命令在 `packages/dataset-builder` 目录执行。

准备生成请求：

```bash
../../.venvs/builder/bin/python -m dataset_builder.cli prepare \
  --suite mini_agent_query_user_intent_v2 \
  --workspace workspaces/query_user_review
```

导入外部模型返回的严格 JSON：

```bash
../../.venvs/builder/bin/python -m dataset_builder.cli ingest \
  --request workspaces/query_user_review/generation_request.json \
  --response response.json \
  --workspace workspaces/query_user_review
```

也可在显式配置 OpenAI 环境变量后调用 `generate`。密钥不会写入请求或工作区。

校验与生成人工审核清单：

```bash
../../.venvs/builder/bin/python -m dataset_builder.cli validate \
  --suite mini_agent_query_user_intent_v2 \
  --draft workspaces/query_user_review/draft.jsonl

../../.venvs/builder/bin/python -m dataset_builder.cli review \
  --suite mini_agent_query_user_intent_v2 \
  --draft workspaces/query_user_review/draft.jsonl \
  --output workspaces/query_user_review/review.md
```

冻结必须在人工审核并显式批准后执行；本仓库的能力包改造不会自动覆盖 evaluator 中
已有的历史冻结数据集。

## 当前 Suite

- `mini_agent_query_user_intent_v2`：理解层，42 条 Coverage Slot，目标版本 2.1；
- `mini_agent_query_user_intent_v3`：42 个约束增强槽位；25 个可生成候选，17 个因缺少精确缺参映射仅生成输入，整包不可冻结；
- `mini_agent_query_gift_intent_v2`：理解层，23 条 Coverage Slot，目标版本 2.1；
- `mini_agent_add_backpack_gift_intent_v2`：理解层，28 条 Coverage Slot，目标版本 2.1；
- `mini_agent_intent_v2`：通用意图理解回归 Suite，目标版本 2.1。

同名 v1 Suite 继续绑定旧能力快照，仅用于复现已有冻结数据集；不会迁移或覆盖。

默认 Bundle 没有注册 Tool。因而 QueryUser/QueryGift 理解层为 `supported`；需要
Tool 的关键链路或端到端选择为 `unsupported`，不会被误判成批量查询能力或完整
执行能力。

## 接入其他 Agent

其他 Agent 只需交付符合当前快照格式的完整、不可变能力包目录。Suite 只绑定 Bundle
路径、Bundle Hash 和目标能力子图，不参与协议路由；公共流水线也不按 Agent、Intent
或 Tool 名称写分支。

生成请求、阶段账本、校验报告和冻结 Manifest 会绑定 Profile、所有可信 Schema、
Adapter 实现、Bundle、Agent 根快照、Capability IR、Suite、Policy、Coverage Plan
和 Source Pack 的 SHA-256，保证可追溯与可判定过期。

## 完整 fixture 能力包全量生成

`generate-full` 为 `full_tools_fixture_v1` 的全部模块、工具、意图、关键链路和端到端
生成可追溯的评测定义。该编译器含此 fixture 的明确业务规则，尚非任意 Agent 的通用语义编译器。

```bash
../../.venvs/builder/bin/python -m dataset_builder.cli generate-full \
  --bundle ../../examples/mini_agent/exports/full_tools_fixture_v1/bundle \
  --delivery-root ../../examples/mini_agent/exports/full_tools_fixture_v1 \
  --expected-bundle-hash 215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c \
  --workspace workspaces/full_tools_fixture_v1_full_eval_20261020

../../.venvs/builder/bin/python -m dataset_builder.cli validate-full \
  --workspace workspaces/full_tools_fixture_v1_full_eval_20261020
```

生成目录包含分层 JSONL、能力包副本、来源 Hash、覆盖矩阵、阻塞项和审核清单。
行为案例、静态契约检查和阻塞义务分别输出；EvalCase 子集使用 evaluator 实际加载与校验 API。
静态校验不代表 Agent 执行通过：交付保持 DRAFT、NOT_RUN、PENDING，不自动冻结。
赠礼确认恢复、生产后端、跨轮上下文以及缺少运行适配的路径不会被宣称已执行。
上述生成与静态校验使用独立 Builder 环境，无需安装 evaluator。

## Nanobot 独立评测候选集

Nanobot 使用单独的输入适配、候选协议及输出目录。该入口支持本次 handoff 的
OpenAI function envelope 和 fact_id 缺口报告，复用受信任 v3 快照校验，保留
unknown 状态；不会套用 mini_agent 的业务意图、错误码或 fixture。

```bash
../../.venvs/builder/bin/python -m dataset_builder.cli generate-nanobot \
  --delivery-root tests/fixtures/nanobot_snapshot_v3 \
  --expected-bundle-hash 8462eaa3c43061cc6e9f5eefaee216f9fed12e2513d86b3f7efbd476e1d06adb \
  --previous tests/fixtures/nanobot_full_eval_20261023 \
  --workspace workspaces/nanobot_full_eval_v3_20261024

../../.venvs/builder/bin/python -m dataset_builder.cli validate-nanobot \
  --workspace workspaces/nanobot_full_eval_v3_20261024
```

输出分为 Schema 契约用例、源码依据的行为候选、静态声明检查与阻塞义务。
协议为 `nanobot_candidate`，不能直接传入 EvalCase loader；交付包含独立 Schema、
完整来源副本、约束文档、覆盖矩阵、审核清单和 Hash。新版兼容 `delivery/bundle/`
布局；以补齐的执行契约生成 31 条显式行为候选，保留原有 89 条模块/工具源码候选。
所有行为候选仍需 runner 和 fixture 绑定；不自行补写缺失的预期，不把静态声明当作执行通过。
`--previous` 只读旧交付，生成候选、断言与阻塞差异及可移动基线；输出目录必须不存在。
当前包仍缺独立关键链路声明、异常观察器及逐工具完整语义；MCP 条件路径边界冲突保留。

运行本仓库测试时，受限环境可使用 `-p no:rerunfailures` 禁用会绑定本地 socket 的
第三方重试插件；这不跳过任何测试或放宽业务校验。

## 可选 DeepEval Synthesizer 后端

安装 `pip install -e '.[deepeval]'` 后，`generate --backend deepeval` 可按
已有覆盖槽位生成语义候选。先支持带 `rule_refs` 的单轮 intent 套件，沿用
原有编译、契约校验、人工审核和冻结；默认后端与历史数据集不变。
模型生成的预期是待审草稿，缺失预期不会通过复制种子或猜测补齐。
安装、运行、适用范围及追溯信息见 [DeepEval 接入说明](docs/DEEPEVAL_SYNTHESIZER.md)。

架构与扩展边界见[项目概览](PROJECT_OVERVIEW.md)，硬约束见[生成约束](AGENT_DATASET_CONSTRAINTS.md)，历史双后端实验见[实测记录](docs/GENERATOR_COMPARISON.md)。

## 发布就绪验证与来源审计

`readiness --delivery` 已接入现有 `generate-full` 产物，以完整行为案例为分母，
分开报告静态有效、运行绑定、reference 验证和发布状态。当前离线路径覆盖
233 条 JSON Schema、六工具的 35 条行为，以及 97 条 Agent/模块/链路案例。
各类统计分开报告，真实失败和 blocked 义务完整保留。模型边界使用独立确定性
输入脚本，不代表真实模型理解能力或生产后端通过。
最新运行与验收见 [97 条 Agent 接入](../../docs/migration/agent-readiness-2026-11-11.md)；
上一阶段见 [Schema 与六工具执行](../../docs/migration/schema-tools-readiness-2026-11-11.md)。
P1 增加逐事实来源与 bundle 外差异审计，旧 bundle 与冻结字节保持兼容。
见 [产物接入与 P1 使用说明](../../docs/migration/builder-integration-2026-11-11.md)。
已有独立 read_file 切片见 [初始 P0 使用说明](../../docs/migration/builder-readiness-2026-11-11.md)。
