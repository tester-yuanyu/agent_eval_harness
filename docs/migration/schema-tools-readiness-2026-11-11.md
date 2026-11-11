# MiniAgent Schema 与六工具离线验证

## 执行范围

本轮按用户授权，先执行 233 条 JSON Schema，再执行六个工具的 35 条已定义行为。沿用现有 `generate-full → readiness run → assess`，没有改 mini_agent 业务代码，没有调用真实模型或托管服务，没有冻结或发布数据集。

新交付位于 `output/mini_agent_full_eval_20261111_v3/`。历史 `20261111`、`20261111_v2` 保留。完整行为定义分母仍是 365，不删除未绑定案例；总定义 854 = 365 行为定义 + 202 契约检查 + 287 阻塞义务。

| 分类 | 本轮绑定目标 | 执行方式 |
|---|---:|---|
| Schema 校验 | 233 | Draft 2020-12 接受/拒绝输入，禁止外部 `$ref`，不创建 fixture、不调用 handler |
| 直接工具调用 | 26 | 独立 FixtureEnvironment + 真实 ToolRegistry/handler，包含业务失败分支 |
| 选择模式校验 | 7 | 真实 Pydantic 参数模型，不调用 handler |
| 一次性授权 | 1 | owner 授权 → 实际调用 → 再调用；逐步记录授权消费和业务状态 |
| 幂等性序列 | 1 | 同 request_id 同参数重试，再改变参数；验证返回资源、CONFLICT 和状态不变 |
| Agent/模块/链路 | 97 | 尚未绑定，不计为执行失败 |

Schema 是已声明参数协议的执行验证，不代表自然语言理解能力。工具在隔离的内存示例后端运行，验证真实 fixture 实现，不代表生产服务。202 条静态契约检查与 287 条 blocked 不计入 365；其中新语义义务和 Agent 端能力缺口仍需单独补齐。

## 使用

从仓库根目录执行；输出 workspace 必须不存在：

```bash
.venvs/evaluator/bin/python -m agent_eval_suite.cli readiness run \
  --delivery output/mini_agent_full_eval_20261111_v3/dataset \
  --workspace output/mini_agent_full_eval_20261111_v3/readiness-rerun
```

`readiness run` 返回码 1 表示整份数据集尚未满足发布门槛。应查看 `report.json` 的 `category_counts`、`results`、`unbound_case_ids` 与 `issues` 区分实际失败和未绑定。当前仍有未绑定行为和 blocked，不能进入发布冻结。

`dataset/` 保留原始定义及 NOT_RUN 静态标记，实际 reference 执行结果位于 `readiness/evidence.json`、`report.json`、`logs/*.eval`。不能将定义文件中的静态状态与独立 reference 证据混为一谈。

## 实现与边界

- Builder 创建 v2 request，使用 manifest 绑定的 13 个 intent/tool Schema，不依赖 Evaluator 或 mini_agent。历史 v1 两例 runner 保留。
- 共享 `operation_readiness.py` 只解释已列举 operation、前置条件与两个精确文本 fixture 模板；根据输入参数补齐隔离记录，不读取 Oracle 或 result_branch 构造结果。
- Evaluator 在 Inspect solver 内实际执行 validator/handler，并记录 `deterministic_reference_not_agent`。此路径不调用模型，不产生正式 DeepEval Agent 分数，也不伪装为完整 Agent 对话。
- 每例独立 fixture；序列例内共享。记录实际初始状态、setup 调用与状态、主调用返回值、逐步状态、授权状态。完整结构和前后连接都参与验证，空对象不能证明 unchanged。授权令牌属于控制状态，单独记录；业务状态包含 users/gifts/pools/resources/requests/grants。
- input、fixture、Schema 构成公开执行计划；Oracle 仅在执行后评估。Inspect Sample target 为空，私有 Oracle 哨兵回归确保它未进入执行日志。
- 新证据绑定完整数据集 Hash、来源文件 Hash、当前运行实现与依赖身份、断言实现 Hash。代码变更后旧证据会过期，需要重新运行。

## 验收记录

见本页末尾的最终验收结果及输出目录中的 `build_steps.json`、`build_summary.json`。相关回归覆盖：233 接受/拒绝结果、35 工具执行、Oracle 哨兵隔离、禁止远程 Schema、真实参数校验不调用 handler、runtime Schema 漂移、缺失/篡改状态、未知前置条件、授权消费、幂等重试、旧 v1 路径与完整分母。

独立审查发现并已修复：空状态仍被判定为 unchanged；异常 preconditions/steps 形状中断全批运行。两项均先复现失败，再修复并回归。没有修改冻结任务或期望答案来通过测试。

本次业务序列实测：授权序列 `OWNER_AUTHORIZED → OK → CONFIRMATION_REQUIRED`，授权标志逐步为 `[true, false, false]`；幂等序列 `OK → OK → CONFLICT`，同参数重试与冲突调用均不增加业务状态。六工具通过数分别为：add_gift_to_backpack 12、prepare_resource 5、query_gift_info 6、query_information 4、query_pool_config 5、query_user_info 3。

### 最终验收结果

- 实际新交付：233/233 Schema、35/35 工具行为通过，合计 268/365（73.4%），97 未绑定，287 blocked，`release_ready=false`。
- Builder 包回归：378 passed、5 optional skipped。
- Evaluator 包回归：1556 passed、9 optional/paid-smoke skipped、164 既有依赖警告。
- contracts 包：35 passed；根 CLI 集成：61 passed。
- 新增 operation 回归：27 passed（已包含在 Evaluator 总数）；独立 fresh clone 同样 27 passed。
- Ruff 本轮涉及文件与 `git diff --check` 通过。
- 全新 clone 叠加当前工作树来源，分别安装 builder/evaluator 环境并运行 `pip check`，完成导出、生成、静态校验、268 reference 验证及历史数据集校验。无 mini_agent 的 Builder 环境检查通过。
- 本轮 fresh clone 源码与当前实现字节一致；验收日志、来源 SHA256 和演示产物保留在 `tmp/schema-tools/acceptance-logs/`、`tmp/schema-tools/artifacts/`，临时 clone 与独立虚拟环境已清理。
- 三个新旧交付分别验证 capability_delivery 的 56 个文件和 dataset 的 254 个文件全部符合原 manifest Hash。历史文件未修改；没有改 mini_agent 业务实现。
- 最后使用当前实现重新 `readiness check`，268 条仍通过，唯一 gate issue 为整份交付尚含未验证行为或阻塞义务。

本轮改动保留在工作树，未创建提交或执行远端发布。实施计划见 [步骤与决策记录](schema-tools-readiness-plan-2026-11-11.md)。
