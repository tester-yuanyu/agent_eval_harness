# Provider 复用与可选展示依赖

## 目标与授权

本轮按用户要求完成两项工程调整：优先复用现有 Evaluator Provider 接口，降低 benchmark 对 nanobot 的直接依赖；将 Langfuse 改为可选安装并清理重复 extra。随后评估 mini_agent 的真实评测可行性。本轮只做离线验证，不调用付费模型或上传服务。

## 现状与方案

现有 `EvaluationProvider` 已定义创建运行时、模块/链路执行、独立观察结果、清理和元数据；`ProviderRegistry` 负责显式工厂注册。benchmark 则直接调用 nanobot 的异步 Inspect bridge。二者的输入、结果、沙箱和运行身份协议不同，不能仅替换类名。

选择复用 `ProviderRegistry`，增加显式的 `AgentAdapter` 扩展，并提供现有 `EvaluationProvider` 的薄桥接。nanobot 的身份、执行模式和沙箱选择收进适配器。领域输入/输出映射由可信接入代码提供，不读取 Oracle，不从配置导入任意 Python 代码。保留 Inspect 执行和 DeepEval 正式评分。

未选择重建第二套注册系统，也不把旧 Provider 强制改成文件工具协议。现有 Provider 的公共接口、冻结 JSON 和历史 Hash 算法保持兼容；新的 Harness 源码与适配器实现进入新运行身份，旧目录不冒充相同身份续跑。

Langfuse 使用 `langfuse` extra，核心及两个 CLI 不预加载展示 SDK。显式调用导出/同步/审核导入而缺少依赖时给出安装指令。DeepEval 是正式评分核心，保留必装；重复 `conversation` extra 删除，相关帮助同步更新。

## 验收

- 同一 benchmark runner 通过注册工厂执行第二个离线适配器，不依赖 nanobot 源码。
- 现有 Provider 经 Inspect worker 桥接复用创建、执行、清理；SIGTERM 进入 Provider 异常清理路径，输入不含私有预期。此为合作式 local 离线边界，非通用进程树隔离。
- 未知适配器、身份漂移、不完整证据保持失败或未确定，不自动 PASS。
- 屏蔽 Langfuse 后核心导入、CLI、离线 demo 与本地报告仍可用；相关显式命令给出可操作错误。
- 运行相关测试、包回归、冻结资产核验及干净副本安装/demo 验收。
- mini_agent 可行性区分旧 Provider 能力、当前 benchmark 领域契约和真实业务工具环境，避免把 mock 测试当作真实成绩。
