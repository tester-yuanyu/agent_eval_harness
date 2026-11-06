# Environment 领域改造验收（2026-11-06）

实现提交 `4b96e6e`，整合提交 `91ebb96`；整合包含并行 Benchmark 方案提交 `c057ed2`。本任务没有修改 Benchmark runner、Scorer、任务数据或评分规则。并行 Benchmark M1 在独立 worktree 中继续，交界文件所有权已经确认。

## 实现与兼容

- 将新 Harness 已有的 Environment Protocol 和两类异常迁入 `environments/base/protocol.py`；旧 ToolRouter 位置重新导出同一对象。
- 文件环境归 `environments/file_tools/`，包含 Inspect 沙箱实现、同步离线实现、异步离线适配、工具 schema 和 worker payload 装配。旧 `file_tools` 模块路径变成同名包，旧同步签名及返回值保持。
- `_fs_utils.py` 成为公共路径/快照逻辑的唯一源码；`local_files.py` 与旧 worker helper 保留薄转发。保留旧本地绝对路径/2,000,000 字节限制及沙箱相对路径/无该限制两套策略，CRLF、排序和拒绝行为不随搬迁改变。
- worker 在 `python -I -c` 下使用由包内可信源码生成的自包含 payload，任务仍走 JSON stdin；旧文件执行、`python -m` 和扁平导入可用。nanobot bundle 清单增加 `_fs_utils.py` 并保持源码身份闭包。
- nanobot 原生执行桥迁入 `integrations/nanobot/environments/`，旧 import 和包顶层入口保留。共享 Docker 绑定逻辑保持原位置。
- 新路径工具错误可恢复；reset/snapshot、损坏 worker 响应及基础设施失败终止试验；取消和 Inspect limits 不改写。旧同步和原生 nanobot 桥的异常约定保持。
- 内存库存 demo 通过 `environment=` 注入既有 Harness，验证库存不足后的工具错误恢复；不修改核心来注册该示例。

开发说明见 [Environment 开发约定](environment-development.md)。

## 已执行验证

| 验证 | 结果 |
| --- | --- |
| 改造前相关基线 | 58 passed |
| 工作树完整 Evaluator 回归 | 1,303 passed / 14 skipped；审查兼容修复另由专用测试验证 |
| 最终新增契约测试 | 20 passed |
| 整合后完整 Evaluator 回归 | **1,310 passed / 9 skipped**，281.62 秒 |
| 根 CLI 与 contracts | 61 passed |
| 包级 Ruff 与 Git diff 空白检查 | 通过 |
| 冻结资产 | 1,172 项通过 |
| 全新 clone 独立 core 安装与 pip check | 通过，未安装 nanobot、minimal_agent、Langfuse |
| 新 clone 定向回归 | 89 passed |
| 非 editable wheel 构建/安装/依赖检查 | 通过；确认实际从 site-packages 导入 |
| wheel 环境契约回归 | 19 passed / 1 deselected；源码路径漂移测试只适用于源码安装，已在前两种源码环境通过 |
| wheel 离线演示 | 原生文件 Harness 正式 PASS；库存 demo 完成且剩余 apple=1；根 CLI 五条 reference demo 和 Inspect 报告生成成功 |

独立只读审查发现两处兼容遗漏：旧模块函数/异常名字、worker 模块启动；均以失败测试复现并修复。额外保留 worker helper 的 `root=` 关键字及 flat import 行为。没有留待以后处理的审查问题。

## 验收边界与取舍

- 最终根回归跳过 2 项 Docker、5 项可选 nanobot 组件、2 项真实模型 smoke；独立 worktree 另外缺少根目录已有的历史证据与可选 τ 环境，所以此前跳过 14 项。没有以 bundle 或本地 Inspect 测试宣称真实 Docker/真实 Agent 已验收。
- 旧 worker 的支持范围是安装目录内的文件/模块执行及扁平导入；单独复制该 shim 文件脱离其资源目录不受支持。沙箱交付应使用自包含 payload，不能只复制 shim。
- 整个 `eval_framework` 父包仍有既存 Inspect 依赖；本次保证 Environment 不新增反向 Agent/Harness 依赖，不扩展为父包惰性导入改造。
- 原有 TOCTOU/特殊文件处理、自动 CLI 领域选择、通用领域报告及正式评分不在本次修改范围。保留 observation 历史 `before_files/final_files` 字段。
- 以上 demo 只验证框架，不代表真实 Agent 成绩。未调用真实模型、上传托管服务、改写冻结数据或历史结果。新源码产生新运行身份，历史 Hash 规则及已有绑定保持。

## 复核位置

根全量回归 `.migration/environment-root-tests.log`；根 CLI/contracts `.migration/environment-root-contracts.log`。全新 clone 为 `.migration/environment-clean-20261106/`，独立环境为其 `.venvs/core`；同级 `environment-clean-install.log`、`environment-clean-tests.log`、`environment-wheel-build.log`、`environment-wheel-install.log`、`environment-wheel-tests.log` 和各 `environment-*-demo.log` 保存输出。演示产物在 clone 的 `artifacts/environment-*`。
