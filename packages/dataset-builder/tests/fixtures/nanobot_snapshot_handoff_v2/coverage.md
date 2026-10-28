# Nanobot 能力快照覆盖报告

配置：`nanobot_offline_core_v1`。采集真实 nanobot 内置工具注册表，使用隔离的临时服务。
这不是当前运行中的 gateway 配置，也没有执行模型推理或工具业务。

- 注册工具：21；导出工具：21。
- 注册表漏项：0；额外虚构工具：0。
- 事实来源覆盖：32/32。
- 子系统：8；内置 Skill 文件：11。
- 未验证等缺口：30，详见 `gaps.json`。
- Snapshot 3.0 结构、引用和摘要由 Kit 校验；`execution_verified=false`。

## 工具盘点

| 类 | 注册名称 | 状态 |
| --- | --- | --- |
| ApplyPatchTool | apply_patch | registered |
| CliAppsTool | — | disabled |
| CreateGoalTool | create_goal | registered |
| CronTool | cron | registered |
| EditFileTool | edit_file | registered |
| ExecTool | exec | registered |
| FindFilesTool | find_files | registered |
| GrepTool | grep | registered |
| ImageGenerationTool | — | disabled |
| ListDirTool | list_dir | registered |
| ListExecSessionsTool | list_exec_sessions | registered |
| ListSessionsTool | list_sessions | registered |
| MessageTool | message | registered |
| ReadFileTool | read_file | registered |
| ReadSessionTool | read_session | registered |
| SearchSessionsTool | search_sessions | registered |
| SendSessionMessageTool | send_session_message | registered |
| SpawnTool | spawn | registered |
| UpdateGoalTool | update_goal | registered |
| WebFetchTool | web_fetch | registered |
| WebSearchTool | web_search | registered |
| WriteFileTool | write_file | registered |
| WriteStdinTool | write_stdin | registered |
| MyTool（核心单独注册） | my | disabled |

## 覆盖边界

- Registry completeness only applies to the explicit offline profile.
- Tool execution, model output quality, memory and business competencies are unverified.
- MCP servers, external tool plugins and user-installed skills are not discovered.
- Channels/providers are represented at subsystem level, not per-integration verification.
- Skill files are inventoried; their semantic abilities and requirements are not evaluated.
- Conversation evaluation profile does not evaluate individual tool execution.
- Risk levels are conservative adapter labels; confirmation/idempotency need per-tool review.

## 如何解读

注册表中的工具全部进入快照，只代表这个明确配置内的结构覆盖。
不能据此宣称 nanobot 所有能力已完整识别，也不能把 unknown 当成不支持。
对话链解析预期为 unknown：本次没有配置和验证真实模型。
下一步可接入经过授权的运行中 Agent 注册表，并补充工具执行、业务意图和真实 LLM 抽取评测。

本交付包以 `manifest.json` 为清单入口，能力入口为 `bundle/agent.json`。
