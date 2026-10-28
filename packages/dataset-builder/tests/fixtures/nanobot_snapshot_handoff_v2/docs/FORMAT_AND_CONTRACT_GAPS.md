# 快照格式与评测边界

本包为 Capability Snapshot 3.0，沿用生成时的 conversation 规范，原文在
`evaluation_specs/conversation/`。没有新增评测策略、评分器或实际业务执行结果。

## 入口和路径

- `manifest.json`：包根目录清单；`bundle_path` 指向 `bundle`，全部文件以包根目录为相对基准。
- `bundle/agent.json`：能力入口；其中快照引用路径以 `bundle/` 为相对基准。
- `bundle/schemas/`：9 份协议 Schema；工具参数约束内嵌于各工具的 function_schema，
  SDK 输入/输出 Schema 内嵌于 agent、module 和 evidence 快照中。
- `capability_contract_gaps.json`：原 `gaps.json` 的逐字副本，包含 30 条已记录的 unknown 缺口。
- `validation_report.json`：原 `validation.json` 的逐字副本，校验结构、引用与摘要，不证明执行成功。
- `facts.json`、`inputs.json`、`provenance.json`：结构事实、原始采集输入和来源关系。
- `sources/`：47 份哈希核验后的源码、配置与 Skill 文件。验证 FactDocument 的来源时，
  使用 `sources/` 作为 source_root；这只是证据文件子集，不是完整可运行仓库。
- `selection.json`、`resolution.json`：原有对话链选择与解析结果（unknown）。
- `original_delivery_manifest.json`：原交付清单。根 manifest 保留原版本及能力包 Hash，
  更新 files_sha256 覆盖此次附带的全部资料；不包含自身，避免自引用。

两个报告文件只做文件名兼容，没有声称已满足未提供的下游专有报告 Schema。
若下游还要求不同字段结构，请按本格式说明映射。

## 契约信息和未明确声明的部分

- 工具名称、描述、参数类型、required、enum、范围等约束来自真实注册对象。
  具体工具是否具有某种约束，以其 function_schema 为准。
- 21 个工具的返回值仅有注册器级通用说明，没有逐工具完整结果 Schema 或错误码表。
  `ToolResult.is_error` 是已有错误标记，不能据此推导业务错误码。
- 工具职责见 description，模块职责见 responsibility；关键链路只有已有对话链。
  完整模块调用图、各工具业务分支和工具组合执行链尚未结构化。
- 幂等和重试为 unknown；batch_behavior.declared=false 表示未声明批处理契约，
  不等于已证明不支持批处理。副作用与权限没有逐工具完成审计。
- requires_confirmation=false 仅描述本离线采集配置没有统一确认网关，
  不得据此推断任意动作均免确认或具有权限。风险等级为保守适配标签。
- 最终输出接口依据真实 SDK RunResult；没有运行轨迹、工具结果样本或业务断言基准。
- 没有业务测试数据集、服务凭据、可回放模型响应或外部服务测试夹具。
  不应将本包作为已经准备好的业务执行环境。

以上缺失细节属于补充契约缺口，本说明与 gaps.json 一起阅读。
对于没有明确声明的规则，请保持未知，不能自行生成已支持的契约。

## 环境条件

采集环境为 Python 3.11，nanobot 源码版本 0.3.0，独立 Kit 0.1.0。
配置见 `sources/integrations/capability_snapshot/offline.json`。
临时会话、cron、子 Agent 和 shell 会话管理对象只用于构造注册表；
未启动调度器、未运行工具、未连接 LLM。
CLI apps、图像生成、my、外部 entry-point 插件和 MCP 连接在该配置中关闭。
真实执行需要完整 nanobot 环境、明确配置的服务与相应测试数据。

10 项集成测试及 58 项相邻回归测试此前通过。它们验证采集与协议一致性，
不代表 21 个工具、业务任务或真实模型表现已通过评测。
