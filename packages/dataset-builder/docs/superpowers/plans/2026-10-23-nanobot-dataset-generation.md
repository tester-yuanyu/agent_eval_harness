# Nanobot 独立评测候选集实施计划

> 使用 executing-plans 在当前工作区完成实现及最终独立审查。用户已明确不再询问，直接完成；保留已有未提交工作。

**Goal:** 从用户交付的 Nanobot 0.3.0 能力包生成独立、可溯源的完整候选集，与 mini_agent 完全分开。

**Architecture:** 复用受信任 v3 Schema/Hash/引用校验及 Capability IR 适配器；新增 nanobot_generation 输入适配、参数契约生成和来源绑定的行为候选协议。原 full_generation 保持原语义，不套用 mini_agent 意图/状态/工具错误码。

**Tech Stack:** Python、Pydantic、jsonschema、现有 Builder trusted v3 kernel。测试使用 PYTHONPATH=src ../agent_evaluator/.venv/bin/python。

**Spec:** 本文件的以下范围与约束。

## 范围与约束

- 来源目录只读；纳入所有 35 个快照、31 个主要目标、21 个工具、8 个模块。
- 输入兼容 OpenAI function envelope 和 fact_id 型缺口报告；所有原文件、unknown、原始 Hash 保留。
- 保留 conversation 边界；模块/工具独立案例不冒充该链内路径。
- 没有声明的 critical chain 生成明确缺口记录，不捏造链或任意组合。
- 行为候选使用快照或哈希绑定源码中的明确预期，仍标为需适配/阻塞；不将源码观察升级为快照 supported。
- 无模型、Agent、工具或外部服务调用；DRAFT、NOT_RUN、PENDING；不冻结。
- 不承诺现有 EvalCase 可消费：交付独立严格协议与 Schema，明确适配缺口。
- 正式目录 workspaces/nanobot_full_eval_20261023；mini_agent 原目录 Hash 验证不变。

## Review Focus

- 不同 function_schema envelope 和 unknown 字段不能错误推断受支持能力。
- 嵌套参数、nullable、enum、required、上下界和 additionalProperties 均需覆盖。
- conversation 禁止模块与真实运行依赖的冲突须显式记录，错误/早停不可伪造证据。
- 每个行为候选必须有实际存在的源码锚点及已哈希来源，不能凭名称猜结果。
- 交付必须独立、可移动复验、不可覆盖、文件被篡改后验证失败。

## Tasks

- [x] 1. 测试先行：新输入适配与全量库存；检查111文件Hash、35快照、31目标、30 gaps，未知保留。
- [x] 2. 测试先行：确定性参数契约用例，覆盖嵌套/nullable/枚举/上下界与错误值；case schema 与来源验证。
- [x] 3. 构造工具和模块行为候选目录；所有来源锚点核验；端到端与关键链缺口显式化。
- [x] 4. 测试先行：独立原子发布、复验、计数/覆盖矩阵/审核清单/约束文档/格式Schema；CLI generate-nanobot/validate-nanobot。
- [x] 5. 全仓测试、Ruff、独立审查、修复；生成正式目录与ZIP；复验并检查mini_agent原文件不变。

## 决策记录

- 独立适配器而非改动mini_agent生成器：两包的业务契约不同，现有mini_agent编译器具有专用假设。
- 未提供运行夹具和评分器，因此新增产物是可校验候选协议，不伪装成已接入evaluator的EvalCase。

## 实施进展

- 输入适配、Schema用例、模块/工具候选目录、严格协议、来源检查、独立交付与CLI已完成。
- 新增测试先观测失败后实现；当前全仓220项通过，受影响代码Ruff通过。
- 测试环境原有pytest-rerunfailures插件尝试绑定本地socket，被sandbox限制；仅禁用该插件重跑，无测试被跳过。
- 当前静态编译2378条：1599 Schema用例、529声明检查、90行为候选、160阻塞义务；219缺口/阻塞记录。
- mini_agent既有253个交付文件与实施前Hash逐一一致。
- 正在进行独立审查，之后正式生成、复验与ZIP归档。

## 完成交付

独立审查未发现重要问题；70条工具候选重点抽查和19条模块候选逐项复核均与源码一致。
正式目录 `workspaces/nanobot_full_eval_20261023`：129个JSONL、263个文件，磁盘复验 valid=true。
ZIP `workspaces/nanobot_full_eval_20261023.zip`（741367 bytes）通过CRC及全部文件SHA-256一致性检查。
mini_agent原253文件Hash保持不变。交付DRAFT/NOT_RUN/PENDING，0 EvalCase，不宣称执行通过。
全仓220项测试通过；新增包、测试与CLI Ruff通过。未运行任何Agent、工具、模型或外部服务；未提交/合并原有工作区变更。
