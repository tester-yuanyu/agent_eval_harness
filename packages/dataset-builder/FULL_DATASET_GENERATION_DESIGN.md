# 完整能力包的全层级评测集生成方案

日期：2026-10-20。状态：用户已确认设计，进入实施计划阶段；本文不代表已经生成或验证了全量评测集。

## 1. 目标与输入

根据用户提供的完整能力包，覆盖全部模块、工具、关键链路和端到端行为；交付 JSONL、能力—案例覆盖矩阵、校验结果、审核清单和阻塞清单。

输入目录：

`/Users/yuanyu/Documents/ChatGPT/mini_agent/exports/full_tools_fixture_v1/bundle`

Bundle SHA-256：

`215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c`

辅助资料：外层 `capability_inventory.json`、`capability_contract_gaps.json`、`manifest.json` 和使用说明。辅助资料用于解释运行前提、列出缺口，不能覆盖快照事实。

## 2. 已完成的接入核对

- 交付 Manifest 中 54 个文件的字节 Hash 全部匹配。
- 使用 Builder 原有 `load_trusted_profile` 和 `load_validated_bundle` 完成安全内核校验，通过现有可信 v3 Profile，无需放宽 Schema。
- 快照数量：Agent 1、Module 7、Intent 7、Tool 6、Scope 5、Chain 3、Evidence 5、Boundary 7。
- 六个工具全部为 `test_fixture`，不连接生产后端。
- 本次安全内核检查单独加载了能力校验模块，未通过依赖 evaluator 的包初始化入口；因此不代表完整生成流水线已经可运行。上次主入口导入因缺少 `langfuse` 阻断，实施前须恢复并验证依赖。

## 3. “全量”的验收定义

全量指对有限能力清单逐项覆盖，不是穷举自然语言和无限参数组合：

1. 7 个 Module、7 个 Intent、6 个 Tool、3 条 Chain 均有明确覆盖记录。
2. 对快照声明的能力、参数约束、决策分支、结果类型、边界和必需 Evidence 分配覆盖项。
3. 每个覆盖项必须关联具体案例，或者关联带来源依据的阻塞原因。
4. supported、unsupported、unknown 均保留；后两者不得自动转换为“预期成功”。
5. 单独统计直接测试、通过链路间接观察、仅契约检查、阻塞。不得把有一条案例等同于该目标已全部覆盖。
6. 支持状态、静态校验通过、实际运行通过、人工批准四者分别记录。

## 4. 四层生成范围

| 层级 | 目标 | 覆盖内容 |
|---|---|---|
| 模块 | agent_orchestrator、execution_guard、intent_router、model_gateway、observability、tool_loop、tool_registry | 已声明能力、输入输出契约、事件、终止条件与不支持边界 |
| 工具 | query_information、prepare_resource、query_user_info、query_gift_info、query_pool_config、add_gift_to_backpack | 参数合法性、模式组合、声明结果、权限前提、幂等、副作用、输入边界 |
| 关键链路 | understanding_to_planning、planning_to_result | 适用 Intent／Tool 组合的正常路径、错误、提前终止、节点顺序和 Evidence |
| 端到端 | end_to_end | 单次用户请求到可观察终态，成功、空结果、业务失败、追问、拒绝、确认等待 |

意图理解覆盖全部 7 个 Intent。既有三个专用 Suite 的案例可作为重新审核的来源，但需重新绑定新能力包、复核语义后生成新版本，不沿用旧批准。

## 5. 必须保留的业务限制

- `add_backpack_gift` 的 Agent 流程以 NEED_CONFIRMATION 为合法终点；不得生成“用户确认后 Agent 自动完成发放”的正向期望。
- `add_gift_to_backpack` 的直接工具测试可使用 fixture owner 的一次性授权，但必须注明这不是 Agent 会话确认。
- 上下文继承、覆盖、取消、会话清理不生成支持这些能力的正向案例；列出能力缺口，具有明确拒绝或终止契约时才生成对应负向案例。
- `prepare_resource` 的创建副作用与 Intent read policy 不一致，记录契约争议；可以分别测试明确的工具行为和意图声明，不把争议组合自动发布为成功端到端案例。
- 礼物写入的 environment 未进入工具参数，只能按隔离 fixture 评测，禁止推导生产环境绑定。
- 重试、异步、限流等必须依据声明处理，不能机械地为每个工具套用“失败后自动恢复”期望。
- 没有冻结的初始 fixture 数据时，不能猜测某 ID 必然存在或返回某条记录；使用明确测试前置条件或列为运行阻塞。

## 6. 当前协议与执行器的适配缺口

已检查当前 evaluator 代码：

1. `EvalCase.test_scope` 是 `module/link/end_to_end`，Builder 配置仍有 `critical_path` 命名，输出需显式映射到 `link`。
2. `ExecutionSpec` 以 `user_input` 为入口，没有直接工具 arguments、模块输入、fixture 初始化和授权字段。
3. `MiniAgentAdapter.run_module` 固定执行 `run_intent_only`，不按目标分派到其他模块。
4. `run_full` 明确拒绝原生 fault_injection；不能生成带故障设置的案例后宣称当前执行器可运行。
5. 当前七个 Module 的 input_schema/output_schema 都是宽泛 object；只能依声明和 Evidence 建立部分行为断言，不能虚构完整独立调用协议。
6. 当前 evaluator 对 end_to_end 要求 goal_state；字段存在不代表任意自造的状态谓词已有对应 scorer。

因此，输出必须区分“当前 evaluator 可消费的 EvalCase”和“需要新增执行适配的契约测试定义”。不能把直接工具测试伪装成自然语言意图测试。

## 7. 方案比较与推荐

| 方案 | 收益 | 限制 |
|---|---|---|
| 只生成现有 EvalCase | 改动少，现有消费链路可复用 | 无法真实覆盖直接工具和全部模块 |
| 扩展 Builder 的全层级生成，分开标明执行适配状态（推荐） | 可完整交付定义、覆盖关系和可用子集，保留缺口 | 部分直接模块／工具定义需要 evaluator 后续接入 |
| 同时改造 Builder、Agent 与 evaluator 运行系统 | 可追求所有已支持能力的直接执行闭环 | 超出单纯生成数据的范围，且不能靠修改系统掩盖原契约缺口 |

推荐第二种：完成全层级数据生产，明确数据协议和运行适配要求；不擅自扩展 Agent 的业务能力，也不把 blocked 项计入可执行覆盖率。

## 8. 拟实施结构

1. 增加全量能力目录与来源绑定：覆盖所有目标，而非单个 selected Intent。
2. 扩展内部表达：保留工具参数／结果协议、模块 Evidence、链路节点与 Boundary，所有字段可追溯到快照路径。
3. 建立确定性覆盖规划：依据约束和声明分支生成稳定 Slot；语义规则使用显式映射，不能仅靠字段名猜测。
4. 分层编译：意图、直接模块／工具、链路、端到端分别编译；后两者复用 evaluator 真正支持的断言。
5. 定义独立且带版本的契约案例 Schema，用于当前 EvalCase 表达不了的直接测试。包含目标、前置条件、输入、Oracle、Evidence、来源和 runner_requirements；执行配置不能读取 Oracle。
6. 模型／文本生成只提供契约内的表达变体；不以 Agent 实际运行结果反推答案。首次采用本地确定性生成，不依赖付费 API。
7. 生成覆盖矩阵及可执行状态，运行结构、参数、来源、覆盖、重复与泄漏检查。
8. 生成待人工审核文档；不自动勾选、不自动批准、不覆盖历史冻结集。

为减少影响，新入口与现有意图 Suite 并存；已有 Suite 和冻结集保持原有绑定。

## 9. 拟交付目录

`workspaces/full_tools_fixture_v1_full_eval_20261020/`

```text
capability_bundle/           本次输入快照副本
manifest.json                版本、来源 Hash、各文件状态与数量
inventory.json               全量目标与能力条目
coverage_plan.json           全量覆盖项
coverage_matrix.json         覆盖项到案例或 blocker 的映射
datasets/
  modules/                   按模块拆分
  tools/                     按工具拆分
  critical_links/            按关键链路拆分
  end_to_end/                按意图和终止分支组织
schemas/                     契约案例 Schema（若使用）
reports/                     静态校验、覆盖、重复、来源一致性
blockers.json                业务契约缺口与执行适配缺口
review.md                    未勾选的审核清单
README.md                    数据入口、数量、运行前提与限制
```

不同协议文件必须标明 `dataset_format`，不能让契约测试定义被误认为现有 EvalCase。可消费子集与待适配定义分别统计；覆盖数量从实际 Slot 和结果产生，不预先承诺任意案例总数。

## 10. 验证与验收

- 输入：完整包通过原有可信校验，交付报告字节 Hash 匹配。
- 规划：23 个 Module／Intent／Tool／Chain 目标都有覆盖记录，Scope／Evidence／Boundary 作为依赖与约束保留。
- 案例：每条具备稳定 ID、来源依据、预期、评测边界和运行前提；正向参数通过对应 Schema，非法输入案例明确预期拒绝且不会误判为生成错误。
- 覆盖：无悬空 case_id、无遗漏 Slot、无重复 ID；间接覆盖不冒充直接测试。
- 契约：确认停止、幂等冲突、all-or-nothing、环境限制等逐项检查。
- 消费：现有 EvalCase 经真实 evaluator 校验；新增契约定义通过独立 Schema，未接入 runner 的案例明确标记。
- 回归：现有意图 Suite 测试继续通过，新增加载、规划、编译和缺口分类测试。
- 人工：交付保持 DRAFT／待审核；即使静态校验通过，也不声明运行 PASS 或已冻结。

## 11. 范围决策

需要审核的核心选择：按上述推荐方案扩展 Builder，交付全层级案例定义和现有执行器可消费的子集；直接模块／工具执行接口、生产后端、确认恢复和上下文能力不在本次生成工作中隐式实现。

本方案通过后，再按项目技能流程编写具体实施计划，明确改动文件、测试及执行顺序。
