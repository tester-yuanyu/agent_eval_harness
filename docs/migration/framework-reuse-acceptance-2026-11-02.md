# 框架复用验收记录

实施从 2026-11-01 开始，2026-11-02 验收。最终代码提交为 `0416ec8`（主改造 `956f18a`、τ 兼容修复 `743476d`），起点为 `f5cc152`；已快进整合至原项目分支 `codex/tool-benchmark-deepeval`。依赖仍固定 Inspect 0.3.280、DeepEval 4.2.9、Langfuse 5.0.2。

## 完成范围

| 优先级 | 交付 |
| --- | --- |
| P0 | Inspect 原生 Sample.files、sandbox、Agent Bridge、预算、Epochs、eval_set 与日志；移除重复的工作区/进程组/模型事件管理；保留真实 nanobot 边界和独立文件证据 |
| P1 | DeepEval TaskCompletion、StepEfficiency、ArgumentCorrectness 与 GEval；通过公开 tracing API 评审保存证据；保留文件真值与声明检查点；重复候选审计移至显式命令 |
| P2 | Inspect 原生查看器与多运行视图、来源绑定和比较门禁；Langfuse 官方 API/OTel 与新增原生 chain 分数映射；补齐根 CLI、配置与说明 |

[当前框架分工与用法](../benchmark/framework-reuse.md)列出必要自研边界。冻结任务、参考答案、历史结果及其 Hash 未改变。未升级依赖，没有新增付费模型评测或托管写入；工程测试不增加历史 Benchmark 执行数。

## 分包回归

隔离工作区首先运行 `python3.11 scripts/test_all.py`，1,741 项通过、15 项跳过。随后原项目执行完整分包回归，发现并修复下文记录的兼容问题；最终在代码 `0416ec8` 上重跑受影响包 `python3.11 scripts/test_all.py --only evaluator`，1,025 项通过、4 项跳过，151.35 秒。其他包未受后续修复影响。每个包使用独立环境，下表记录各包最后一次结果。

| 检查 | 通过 | 跳过 |
| --- | ---: | ---: |
| Contracts | 1 | 0 |
| Builder | 353 | 5 |
| 参考 Agent | 323 | 1 |
| Evaluator | 1,025 | 4 |
| 根集成 | 57 | 0 |
| 合计 | 1,759 | 10 |

最终跳过项为可选 Builder DeepEval 环境（5）、付费模型 opt-in（参考 Agent 1、Evaluator 2）以及默认未启用的 Docker 集成（2）；Docker 已单独显式执行。原项目的历史证据与真实 τ 离线用例均已运行。轨迹 SDK 由消费者测试覆盖，没有独立测试目录。

Evaluator 全量 Ruff、修改过的根 CLI Ruff、`git diff --check` 通过。`scripts/verify_assets.py` 校验 **1,172 个既存导入资产与测试 fixture**，与原字节一致。10 个既有相关测试的 import 排序在全量 Ruff 中修正，不改变断言。

## 真实执行边界与评分验收

协调者独立执行：

```bash
DEEPEVAL_TELEMETRY_OPT_OUT=1 OTEL_SDK_DISABLED=true \
RUN_DOCKER_BENCHMARK_TESTS=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
.venvs/evaluator/bin/python -m pytest -q \
  -c packages/evaluator/pyproject.toml \
  packages/evaluator/tests/benchmark/test_inspect_bridge_integration.py
```

结果 **2 passed，62.28 秒**。使用真实 Docker 29.9.2、nanobot AgentLoop/ToolRegistry 和 Inspect mock provider：验证 Agent 两个独立 epoch、decision 不执行工具、Token/消息限制的原生事件与正式 `VALID/FAIL`、显式 Docker 模块 PASS、实际镜像/环境绑定，以及每个容器在 eval 返回后删除。模型是本地确定性替身，没有真实模型请求。

DeepEval 另有真实 worker 子进程 + 本地 HTTP fake OpenAI Judge 的成功路径：StepEfficiency 返回 `SCORED=0.8`，严格产生两次请求和两条调用证据；socket guard 只允许 loopback，无 Confident 请求，密钥不进入 stdin、请求正文或评分记录。新进程公开 Python import 与确定性评分也验证零网络连接。

## 独立审查与修复

独立审查复现并推动修复 11 项问题：Provider 错误分类、原生媒体目录越界、模块沙箱身份、独立 API 消息限额、不完整事件投影、未知 Judge 请求预算、报告日志来源绑定、Docker 解析环境绑定、整轨迹 chain 分数导出、预算终止的正式分母，以及身份漂移被样本错误恢复吞掉。

最终独立定向回归 49 项通过，另有新进程隐式联网边界 1 项通过；审查未发现剩余 P0/P1/P2 阻断项。报告还核对 sample ID/epoch、显示分数、内嵌 record 与保存结果；较新 partial 日志不会覆盖较早的完整证据。Langfuse 相关回归为 153 项，通过离线保存/导出/读回，未触发线上交付。

原项目的可选 τ 环境补充回归捕获 3 项失败：τ worker 仍引用主执行器已移除的旧日志 helper，修复后又发现脚本模式的相对导入问题。现将 τ rendezvous 证据内聚于 `tau_worker.py`，不恢复主链路的重复模型日志；保留官方 Orchestrator 与 reward。新增无需 τ 环境的延迟导入、独立进程身份、脱敏与截断证据测试，并将来源摘要算法纳入 τ 源码身份。最终专项 **51 passed、0 skipped**，含全部 3 项真实 τ/Agent 离线传输用例。独立审查分别复核 48 项及来源绑定补充 30 项通过。

联合回归还捕获 Langfuse 补证目标 ID `24481393e7248852` 被 JSON 解析为科学计数法的偶发失败。新增补证 v2 对目标 ID、来源 Hash 添加类型前缀，保持 core parent/trace 精确校验；旧 v1 回执按旧格式重建，拒绝未知版本，不接受不可逆浮点近似。定向 **34 passed**，覆盖强制该 ID 的完整导出/读回、64 位纯数字 Hash、旧回执不重复写入和六种补证损坏场景。原始轨迹及结果未改变。

最终独立 Langfuse/τ Harness 回归 **75 passed**。审查者另行动态加载修改前的实现，比较 3 种 ID × 2 种来源 Hash：新实现显式选择 v1 后，6 组 `model_dump` 与 JSON 字节均与旧实现一致；v2 正常读回通过，篡改 parent 或 trace 均为 `MISMATCH`。

未将 Langfuse 的连接重试改成显式 HTTPTransport：本地实测发现这样会绕过环境代理，不能保持部署语义。继续复用官方 API/OTel，仅保留稳定 ID、证据/回执与连接建立错误重试；SDK 对含糊写响应的默认重试已明确关闭。

## 全新克隆安装

通过 `git clone --no-local --branch codex/framework-reuse` 建立独立克隆，再运行 `python3.11 scripts/setup.py`。新建 Builder 和 Evaluator 环境，未复用工作区虚拟环境；两个环境的 `pip check` 均通过。Evaluator 实际安装 Inspect 0.3.280、DeepEval 4.2.9、Langfuse 5.0.2。Builder / Evaluator 的 OpenAI 依赖分别为 2.54 / 3.40，继续使用独立约束。

在新环境中运行根 CLI：baseline 和 candidate 各 5 条离线 demo、两份原生报告以及带 Inspect View 的严格比较，5 对样本全部完成、差值为 0。`test_agentic_metrics.py`、`test_harness_integration.py`、`test_native_reporting.py` 合计 **29 passed，10.44 秒**；资产校验 1,172 项通过。安装和 demo 证据保存于 `fresh-setup.log`、`fresh-smoke.log`、`fresh-install-demo/`。

兼容修复提交后，独立克隆快进到 `0416ec8`，在同一新安装环境补跑评分、报告、τ Harness、nanobot runtime 和 Langfuse 读回：**105 passed、3 skipped，14.93 秒**。跳过的 3 项需要额外 τ 解释器，已在原项目可选环境实际通过；没有把该环境链接到干净克隆。两个环境再次 `pip check` 通过，资产再次校验 1,172 项通过。补充日志为 `fresh-final-smoke.log`。

最终代码还重新执行 baseline/candidate 各 5 条 demo、两份原生报告及比较，全部成功；命令输出为 `fresh-final-demo.log`，产物为 `final-code-demo/`。

## 报告浏览验收

通过根 CLI 运行 5 条离线 demo 并生成原生 `inspect-view`。使用本地 HTTP 服务实际打开 Inspect View，核对五条样本、PASS 展示、单样本 Transcript、DeepEval v2.3 评分理由及证据引用，页面正常渲染。该 demo 是参考闭环验证，不能用作真实 Agent 成绩。

本机 `/usr/bin/make` 因缺少 Xcode Command Line Tools 无法运行，验收使用 Makefile 对应的根 CLI 命令；未安装系统开发工具。

## 证据位置与剩余边界

本地证据汇总于 `artifacts/framework-reuse-acceptance/`：包含审查报告、实施报告、Docker 日志、工作区回归、demo 与 `sources.json` 文件 Hash。执行工作区和独立克隆均保留在 Git 忽略的 `workspaces/` 下，未复制凭据。外部 nanobot 原有未提交修改保持原样。

人工校准、独立留出阈值验证、更多业务任务覆盖仍需独立工作；本轮没有用机器生成标签冒充人工验收。local sandbox 不提供操作系统隔离；Docker 新运行仍可能解析范围依赖，但同一运行恢复会绑定并校验实际镜像与环境。事后 Judge/历史纯 JSON 结果仍使用兼容 domain 报告，不伪造原生执行日志。
