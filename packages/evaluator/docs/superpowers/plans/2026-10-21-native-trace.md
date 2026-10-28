# 原生 Trace 替换方案与执行记录

用户已明确授权替换通用采集与存储。按既有 Inspect / Evaluator / Langfuse 边界直接执行，不新增第二套采集引擎。

## 设计

- Inspect `Transcript.info` 承担事件收集，公开 `write_eval_log` / `read_eval_log` 承担存储与读取。
- 每 Trial 保存一个原生 JSON EvalLog `trace.inspect.json`，Sample.events 为业务 InfoEvent，Sample.metadata 保存证据计数、完整性和结束状态。输入和 target 留空，不含 Oracle。每次业务事件同步保存，使用 Inspect 原生原子写入与 fsync。
- `agent_trace_sdk` 包名保留以兼容独立 Agent；实现缩减为业务协议适配。新的生产类名 `InspectEvidenceSink`；旧 `LocalEvidenceSink` 仅是兼容别名，没有旧写入实现。
- 删除 SDK 自研内存事件列表、JSONL 写入、collection.json 检查点；旧 JSONL 只有只读解析用于历史材料。运行与报告里的 association.json 仍是业务身份契约，不是事件存储。
- Inspect 主执行日志记录证据源引用，停止把同一批业务事件再逐条复制入主 Transcript；Langfuse 读取正式结果中的事件投影。
- 原生 JSON 快照每次重写当前 Trial，优先保证小规模评测的同步取证与原子性；本次不声称适用于高吞吐长轨迹。以后优化应使用原生增量能力，不恢复自研存储。

## 执行计划

- [x] 先增加原生格式、事件/状态同快照和历史读取测试，确认旧实现失败。
- [x] 替换 Collector / Sink / Reader，保留字段白名单、脱敏、关联与序列政策；切换 Runner、报告链接，移除二次复制。
- [x] 更新故障注入测试，覆盖写失败、进程退出、缺失/损坏日志、跨 Trial 关联、并发与复制报告；运行完整扩展测试及 lint。
- [x] 独立审查、修正、更新技术方案和验收结果。

## 重点验收

失败不能回退到内存或旧格式；未知不能变 PASS；原生快照中的完成状态与持久事件一致；最后一次写失败仍保留前次可读证据；新格式损坏不能被旧文件掩盖；历史格式继续可读；不增加云端上传或付费调用。

## 验收记录

- 扩展自身配置全量测试：378 passed、2 个付费测试跳过；全量 Ruff 通过。
- Agent 完整测试（Evaluator 集成环境）：321 passed、1 个付费测试跳过；最终 Reader 去重修改后，Agent 通道测试再次 3 passed。
- 新增覆盖原生日志格式、历史只读、损坏原生源不回退、写失败保留已提交快照、内存不能升级完成状态、非 JSON 值不绕过脱敏，以及问题去重。
- 独立审查发现并修复原生类型校验提前触发导致业务采集中断的问题，修复后复核无剩余问题。
- 未修改 Inspect 上游核心；未执行付费模型调用或云端上传。
- 依赖迁移：SDK 现在显式依赖固定 Inspect，不能继续按无框架依赖的独立采集引擎描述。

- Agent 自有 `.venv` 已安装本地 Inspect clone 与更新后的 SDK；该环境全量测试也为 321 passed、1 个付费测试跳过。
