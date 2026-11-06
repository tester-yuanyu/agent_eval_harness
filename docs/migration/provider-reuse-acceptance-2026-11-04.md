# Provider 复用、可选 Langfuse 与 mini_agent 准备度

本轮按用户要求完成 Agent 接入解耦和依赖调整，并评估后续 mini_agent 评测。所有验证离线进行，不调用真实模型、不上传托管服务，不修改冻结数据或历史成绩。工作基于 `39703bf` 的现有分支工作树。

## 实现与复核

- 复用 `EvaluationProvider`、`ExecutionSpec`、`AdapterOutput` 和 `ProviderRegistry`，补充 `AgentAdapter` 所需的 Inspect 启动、身份、模式与采证接口。nanobot 默认值留在 composition，文件 runner 不再直接认识它。
- 直接注册的离线适配器和现有 `ExternalProvider` 的 worker 桥均通过同一 runner；缺失证据不会因进程执行成功变成 PASS。自定义工厂从可信 Python 注册，不从任务/配置动态导入代码。
- Harness v4 固定逐模式身份；源码或运行身份漂移拒绝恢复，v3/v4 报告均核对原生日志内嵌结果。
- Langfuse 改为 `langfuse` extra 和 `--with-langfuse` 显式安装，SDK 延迟导入；DeepEval 保持必装，删除重复 `conversation` extra，保留旧可选环境参数。
- 独立审阅发现沙箱降级、逐模式身份未固定、线程超时无法终止及后代进程未清理，均以失败测试复现后修复。最终复核通过。

清理复用现有能力：Inspect 管理 worker；worker 的 SIGTERM 转成异常，使 ExternalProvider 的既有 killpg/wait 和 cleanup 执行。真实 stdio 子进程及其后代在超时、父取消后不再写文件。本机桥是合作式离线协议，不是任意程序的 OS 沙箱；Provider 不能吞掉终止异常，SIGKILL 不保证 finally 执行。真实模型仍需 Inspect model bridge。

## 验证证据

日志位于忽略目录 `artifacts/`，包回归及新克隆运行验收清除了服务凭据及付费 smoke 开关。

| 检查 | 结果与证据 |
| --- | --- |
| Contracts | 1 passed，`provider-reuse-regression.log` |
| Builder | 353 passed / 5 skipped，缺少可选 DeepEval 的测试跳过 |
| mini_agent 包 | 323 passed / 1 skipped，付费 smoke 跳过 |
| SDK | 无独立测试，由消费者回归覆盖 |
| Evaluator | 1,138 passed / 4 skipped；Docker 与付费 smoke 未启用，见 `provider-reuse-evaluator-final.log` |
| 根集成 | 58 passed，`provider-reuse-integration-final.log` |
| 新适配边界 | 12 passed，`provider-adapter-final.log`；覆盖替换、Oracle 隔离、身份、预算、超时/取消、后代进程清理 |
| Lint / diff | 包目录内运行 Ruff，通过；`git diff --check` 通过 |
| 冻结资产 | `scripts/verify_assets.py` 验证 1,172 个导入参考资产与 fixture |
| 全新安装 | 从本地 Git 新克隆，叠加本次未提交源码，`setup.py --only core` 和 `pip check` 通过；`provider-reuse-clean/install.log` |
| 无 SDK/Agent 验收 | 确认 Langfuse 和 minimal_agent 均未安装、DeepEval 4.2.9 存在；根 CLI benchmark demo/report、旧 ExternalProvider demo 成功；benchmark 及核心边界 471 passed / 24 skipped（缺少可选 SDK、环境或本地历史证据）；见 `provider-reuse-clean/acceptance.log` |

新克隆保留独立 `.venvs/core`，不是借用原 Evaluator 环境。默认 benchmark demo 验证参考流程；旧 demo 分别产生 PASS、FAIL、INCONCLUSIVE 三类结论；这些都不是 mini_agent 的真实成绩。测试对 Langfuse 专有功能按 SDK 是否安装跳过，有 SDK 的原 Evaluator 环境继续执行对应离线回归。

## mini_agent 能否评测

**可以，已有 Provider 可复用，但尚不能将旧 Suite 直接当作当前 DeepEval 主线结果。** 本轮只进行了数据校验与代码审查，没有真实模型执行或新的性能分数。

按当前编译/语义校验，冻结数据得到以下结果；原始校验记录在 `artifacts/mini-agent-readiness/validation.json`：

| 数据集 | 用例数 | 当前静态校验 |
| --- | ---: | --- |
| `module_query_user_intent_v2_1` | 42 | 通过 |
| `module_query_gift_intent_v2_1` | 23 | 通过 |
| `module_add_backpack_gift_intent_v2_1` | 28 | 通过 |
| `module_intent_v2_1` | 15 | 整组被阻止；011、012、013、014 含多轮 user_responses，与 module 单次调用契约冲突 |

前三组共 **93 条通过静态校验**，不等于运行通过，也不代表当前 Agent 能力身份已完成真实运行兼容验收。第四组不能修改冻结 JSON 以消除错误；应创建有来源的新版本，或明确标记过滤子集及独立身份，不能声称整组完成。

现有 `MiniAgentProvider` 已有 module / full 生命周期、能力校验与 model_client_factory 注入。默认工具绑定仅支持 `query_user_info`，默认 handler 返回无 fixture 匹配；`gift_sqlite_v1` 只支持 `add_gift_to_backpack`，是本地隔离 SQLite 测试环境。因此意图模块评测和完整工具链评测需要分别组织，不能把静态/mock 工具结果称为真实业务端到端结果。

后续建议按以下顺序接入，保持通用 runner 无 Agent 名称分支：

1. 注册 mini_agent 工厂，复用现有 Provider；补 Inspect 模型传输与 `ExecutionSpec → AdapterOutput → 观察证据` 的薄映射。
2. 保留旧用例与 Oracle 分离，复用已有领域断言逻辑包装 DeepEval `BaseMetric`；不把历史 Inspect 分数改标签成 DeepEval 分数。
3. 首轮使用上述 93 条模块用例，按模型、预算、运行能力身份固定一次小批试跑，再扩到完整集和重复运行。
4. 工具链另配显式 handler / fixture 或测试服务、状态采证与工具契约；修订多轮任务时发布新资产版本。

模型名、接口、密钥环境变量、预算和工具绑定应放配置/可信工厂中；参考答案只进入评分端。真实评测启动前仍需明确模型与调用预算，本轮未使用现有凭据自动调用。
