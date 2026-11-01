# 迁移来源与历史验收

本文保存 **2026-10-28 monorepo 迁移**的来源、不可变资产索引与验收事实。验收代码 commit 为 `41892aebbe27c37c676fe58dbf338ede684b42d7`，导入基线为 `08e20ac`。这些数字对应当时的依赖与实现，不代表当前 benchmark 的测试总数或 Agent 成绩。当前用法见[文档导航](../README.md)，分层评测验收见 [v2 状态](../benchmark/status-v2.md)及[验收记录](../../reports/file-tools-v2/verification.json)。

## 导入来源

2026-10-28 导入三个项目的实际工作树，包括未提交内容；仅凭原 HEAD 不能重现全部导入实现。原仓库保持独立、只读且未改动。

| 原仓库 | 记录的 HEAD | 导入时工作树 |
| --- | --- | --- |
| mini_agent | `124a26ac92d2dd5a2be88ad5f69cf7fc8522f954` | 存在未提交修改 |
| agent_dataset_builder | `fa30dcbd9f996a442f450f7649a01e998468c8f9` | 存在未提交修改 |
| agent_evaluator | `76f9209ec9c91bde69e98a1b47bed609668e1e1e` | 存在未提交修改 |

Inspect 固定为 0.3.280，对应上游 commit `dfcb169e1cb170a8fbe2c37a0e3befc45c2c2b85`；导入时没有已跟踪的上游源码改动。业务扩展迁入 `packages/evaluator`，不复制上游源码或嵌套 Git 仓库。原 Git 状态、差异、初始文件 Hash 与基线副本保存在 Git 忽略的 `.migration/`。

## 不可变资产与包边界

- [`frozen-assets.json`](frozen-assets.json) 记录 416 个导入参考文件；[`builder-fixture-provenance.json`](builder-fixture-provenance.json) 记录 756 个由清单绑定的 Builder fixture 文件及各自来源、目标和 SHA256。共 **1,172 个文件**由 `python3 scripts/verify_assets.py` 校验。这两个索引保持原内容。
- 756 个 fixture 分别来自 `full_tools_fixture_v1_full_eval_20261020`（253）、`nanobot_full_eval_20261023`（263）、`nanobot_snapshot_v3`（128）和 `nanobot_snapshot_handoff_v2`（112）。清单要求验证所有文件，不能随意裁剪文件或改写清单。冻结内容中的历史机器路径是溯源数据，不作为当前执行路径。
- 共享快照工具与 Builder 的 Suite、Policy、Profile、Schema 共 115 个文件与私有基线逐字节一致。`capability_snapshot_kit` 移入 contracts，`eval_contracts` 提供共享模型与校验，保留历史导入、类型身份和 Hash 语义；Builder 的生成 IR 与实际评分执行不进入共享包。
- 登记的 `mini_agent@0.1.0` 包含 44 个与原 fixture 逐字节一致的 JSON。Bundle Hash 为 `99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8`，Agent 根 Hash 为 `7f140848d755166188fdd22872a2ab782ab0b37ff51750938e609d6de0614b21`。只增加 `tools/.gitkeep` 保留协议要求的空目录，没有增加 bundle 内 JSON 清单。
- Builder wheel 包含 Schema、Suite、Policy 和 Profile 资源，可在源码目录外加载自定义 Suite；仓库专用的内置 Suite 仍需要对应示例资产。mini_agent wheel 包含字节一致的能力 Markdown 资源，实际在源码目录外导入并编译过能力包。
- 核心 Evaluator 的外部 Provider 不依赖 `minimal_agent`。根 CLI 使用标准库与独立环境子进程，不导入各包运行时；轨迹 SDK 保持独立。

## 原项目基线与全新克隆验收

环境为 macOS、Python 3.11.4。原基线在私有副本中按原同级目录布局执行，并移除模型凭据和真实调用开关；未编辑原项目。原环境含可选依赖：

| 原包 | 基线结果 |
| --- | --- |
| mini_agent | 321 通过，1 跳过 |
| agent_dataset_builder | 357 通过 |
| agent_evaluator | 607 通过，2 跳过 |

迁移仓库通过 `git clone --no-hardlinks` 克隆到原项目外的新临时目录，从头创建环境，按声明依赖与已保存约束安装。所有本地导入均指向该克隆，没有通过 `PYTHONPATH` 注入旧源码或旧环境。

| 测试组 | 当时默认环境 | 当时可选环境 |
| --- | --- | --- |
| 共享 contracts | 1 通过 | 1 通过 |
| Dataset Builder | 353 通过，5 跳过 | 358 通过 |
| 参考 Agent | 323 通过，1 跳过 | 323 通过，1 跳过 |
| Evaluator | 598 通过，14 跳过 | 610 通过，2 跳过 |
| 根集成 | 35 通过 | 35 通过 |
| **合计** | **1,310 通过，20 跳过** | **1,327 通过，3 跳过** |

默认环境多出的 17 个跳过项是可选 DeepEval SDK 或指标测试；其余 3 项需要显式付费 API 调用，当时未执行。旧兼容 API 的弃用警告仍存在：默认 Evaluator 59 条、可选环境 80 条。轨迹 SDK 没有单独测试目录，由 Agent 和 Evaluator 消费方覆盖。

当时执行的命令如下；**当时 DeepEval 尚是可选依赖，当前 benchmark 已将它列为 Evaluator/Core 必需依赖**，不能沿用旧安装状态解释当前环境。

```bash
python3.11 scripts/setup.py
python3.11 scripts/test_all.py
python3.11 scripts/setup.py --only builder --optional-metrics
python3.11 scripts/setup.py --only evaluator --optional-metrics
python3.11 scripts/test_all.py --optional-metrics
```

四个默认/可选环境均通过 `pip check`，两次完整运行后克隆保持 Git 清洁。可选环境使用 `.venvs/builder-optional` 与 `.venvs/evaluator-optional`，不覆盖默认环境。完整本地依赖组合均通过安装解析；当时保存的可选解析报告包含 Builder 71 个、Evaluator 125 个外部依赖。

旧离线演示使用真实 Inspect 执行与评分，输出 `PASS`、`FAIL`、`INCONCLUSIVE` 三个预期结论及原生 `.eval` 日志；Oracle 不进入 Agent 消息。Core 环境在未安装、未导入 `minimal_agent` 时也完成同一演示。此演示现由 `make legacy-demo` 调用，不是当前 `make demo` 的 5 条基准任务，也不是业务 Agent 成功率。

安装后的 CLI 在克隆中解析并重验 `mini_agent@0.1.0`，离线准备 `mini_agent_query_user_intent_v2`。根集成中的 32 个 CLI 测试覆盖固定版本登记、规范校验、源码身份及边界情况。资源 wheel 正常构建并在源码目录外验证，未用跳过依赖安装掩盖冲突。

## 验收中修复的问题

1. 旧测试依赖同级项目路径、外部 fixture 和空 bundle 目录：改为兼容锚点解析、可溯源 fixture 副本与必要的非 JSON `.gitkeep`；冻结 JSON 不变。
2. `git status` 可能漏过 `assume-unchanged`、`skip-worktree` 或 `core.filemode=false` 隐藏的修改：固定源码解析直接对照 commit tree 检查字节、类型、符号链接与权限，禁用 replacement objects，并保留相应回归。忽略文件、依赖和远端部署仍在该身份范围之外。
3. DeepEval 的 Click/Rich 要求与当时默认约束冲突：分别解析可选依赖并使用独立环境。当前依赖关系以后续主线为准。
4. 旧 Suite 等价测试误比较两次独立测量的延迟分位数：只排除嵌套 `latency_p50_ms`、`latency_p95_ms`，继续比较业务判定、性能样本数及 Judge Token；确定性回归证明语义字段变化仍会失败，生产评分未因此变更。
5. 当时主机的 `/usr/bin/make` 为 Xcode 占位程序：验收使用文档中的等价 Python 入口，没有成功执行 Make 目标，也未为此安装系统工具。

独立审查覆盖根调度、资产登记、源码固定、独立安装、共享契约、可选 Agent、资源打包及离线演示，在验收 commit 未发现剩余阻塞项。审查另运行 6 项核心/可选 Agent/源码/演示检查及最后 9 项安装与 Suite 测试，均通过；`git diff --check` 通过。

1,023 个初始导入源文件重新与原位置计算 Hash，未发现变化；三个原仓库的 HEAD 和工作树状态也保持不变。跟踪文件中没有嵌套 Git 仓库、外部源码符号链接、虚拟环境或检测到的凭据文件。详细日志保存在本地 `.migration/clean-clone-*-final.log`、`.migration/profile-integrity.json` 和 `artifacts/verification-clean-clone/`，不随 Git 分发。已完成阶段的详细过程可查 Git 历史。

这次迁移交付的是本地打包与离线执行；未发布 GitHub 仓库、未执行付费评测，也未替代新数据集所需的真实人工审核。2026-11-01 之后的真实 benchmark、GEval 与 Langfuse 结果由各自报告单独记录。
