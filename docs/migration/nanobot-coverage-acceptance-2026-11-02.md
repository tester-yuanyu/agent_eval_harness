# nanobot 覆盖补齐验收（2026-11-02）

本次从 `53d29b4` 开始，按用户授权补“版本与有效配置 → 覆盖矩阵 → 优先场景 → 重复与复核”。只修改本仓库；外部 nanobot 只读。未调用真实模型、发送消息或上传托管服务。

## 交付与身份

- 独立 `nanobot-core-task-v1` 合同及 `nanobot-core-v1` 数据集：32 条、12 个家族；24 dev、8 reserved holdout。冻结 SHA256 为 `3718d896425366db7388fcd9c17e4f8d8d2433ec57fd37f80331ef816992c94c`。
- Inspect 管理 Sample/Epochs、local sandbox、限时和原生日志；DeepEval BaseMetric 在执行边界外检查私有 Oracle。执行输入只有 settings/operations。
- 15 个显式能力域，分别记录源码、启用、任务、执行、通过及人工审核；当前两个 profile 与历史运行分开。
- 目标 commit `415df576b46464445121fe1bc68d24cd5b649635`，dirty 工作树，567 个清单文件。源码清单 Hash `5ada630fbf47faae8181732472ffcb392a34e9533c85c36f11c9a60af3c94730`。
- 本轮 snapshot Hash `5f6ae8d8186a78731b68d96d45351c734bc3971e843e0c404945abd92e34ae5e`，run identity Hash `223e95dad503e737d51b057ba736edb11ac7ea55ced5aac7714781165764e2dc`。解释器、依赖名称版本及源码/适配/评分代码范围见公开 snapshot，不能将它解释为全部外部依赖字节锁定。

## 真实离线运行

24 个 dev 任务各 3 次：72 次观察、72 次有效，69 PASS、3 FAIL、0 INVALID、0 INCONCLUSIVE、0 缺失。23 个任务三次全通过，24 个任务三次判定一致。Memory、Context、Skills 各 18/18，通过；Session 15/18。耗时为各 trial 合计 382.03 秒，包含来源重验和独立快照，不是并发墙钟耗时。

三个 FAIL 均来自 `core-session_legal_replay-orphan`。冻结 Oracle 要求保留孤立 tool 之前的 user 消息，当前 API 采取合法后缀策略返回空历史。保留原失败、答案与 Hash，标记需求/Oracle 待裁定，未称为已确认产品缺陷。8 个 holdout 仅做合同与 Hash 校验，未执行；人工审核/标签为零。组件重复不代表 LLM 稳定性。

原始证据在本次工作树的 `artifacts/nanobot-coverage/dev72/`，包含 Inspect 日志、run/snapshot/results 及 72 个 trial 文件。公开摘要按原始 results SHA256 `92ce64447f70dbe65b09d90cdbbbbc5f2c10f47ed819a60b9a40d1e88b8ff098` 绑定。公开四文件不复制 observation、完整提示、Oracle 或绝对路径。四个历史运行共 612 trials 单列，不升级为当前 profile 的执行证据。

## 独立审查与修复

| 发现 | 修复及验证 |
|---|---|
| 原生超时可能丢失 trial | 真实 Inspect time limit 故障注入先复现失败；取消后保存记录，由原生限时事件转为 INVALID，保留计划分母 |
| 数据两次读取可能错绑新 Hash | load 前后、每 trial 前后及发布结果前核验；临时副本在 snapshot 时变更，执行边界调用为零且不发布 results |
| 来源探针和 worker 启动规则不同 | 使用 `-I -B` 隔离启动、显式源码路径与导入入口校验；真实子进程验证 source sitecustomize 不执行 |
| 未绑定子模块/字节码可能被导入 | 拒绝可导入源码、扩展、直接 pyc 的清单遗漏和符号链接；独立空缓存前缀避免使用旧 pycache，等长同 mtime 的旧缓存回归先红后绿 |
| core 事件是数值时间，矩阵原先只识别 ISO | core 使用有限非 bool 数值时间，文件工具仍用带时区 ISO；非法时间不计完整执行 |
| 运行身份未包含共享实现/第二解释器环境 | profile 包含共享快照与限时辅助代码，snapshot 同时记录目标与 Harness 环境 |

独立审查已复核本轮发现的实现阻断项关闭。公开报告的当前/历史分母、失败争议、未执行留出、人工待完成及隐私字段也经复核。审查由另一自动化代理执行，不计入独立人工标注。

## 回归与安装

旧导入资产校验：1,172 项保持一致。新增定向测试 96 passed；按 Evaluator 配置执行 Ruff 与 `git diff --check` 均通过。分包离线回归共 1,850 passed、15 skipped：Contracts 1、Builder 353、mini_agent 323、Evaluator 1,116、根集成 57。SDK 由消费者测试覆盖，没有独立测试组。Evaluator 在最终源码冻结后单独复跑，仍为 1,116 passed、9 skipped；其余跳过为 Builder 的可选依赖及真实模型开关。真实模型与可选 Docker 检查未由本次自动开启。

全新克隆 `74563ac` 后，`scripts/setup.py` 完成 Builder/Evaluator 两个独立环境安装及 `pip check`；新 `core-validate` 返回 32 条、24 dev/8 holdout、`executed=false`。本机 `make` 因缺少 Xcode Command Line Tools 无法启动，未安装系统开发工具，直接按 Makefile 运行同等 Python 根 CLI：5 条离线参考 Demo 全部通过、Inspect 静态查看器生成，1,172 项资产再次验证一致，克隆工作树干净。该 Demo 是评测框架参考验收，不增加真实 Agent 或本轮 core 执行数。

根 CLI 的三个新命令转发另经红绿测试补齐，并重跑 57 项集成回归通过。干净克隆更新到 `8c08a4b` 后，根 `benchmark core-validate` 及 `core-run/coverage --help` 均成功，工作树仍干净。安装与 Demo 日志保留在本次工作树 `artifacts/nanobot-coverage/clean-clone.log`、`clean-demo-cli.log`、`clean-root-cli.log`；没有再次调用模型或执行核心 holdout。

使用方法见[覆盖指南](../benchmark/nanobot-coverage.md)，实际结果见[公开报告](../../reports/nanobot-coverage-v1/README.md)。Shell、Web、MCP、子代理、渠道/定时等仍需各自任务与执行证据；本次不构成完整 nanobot 产品验收。
