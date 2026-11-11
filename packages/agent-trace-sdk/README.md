# Agent Trace SDK

基于 Inspect 的业务证据适配 SDK，独立分发。Inspect 提供原生 Transcript、EvalLog 与日志持久化；SDK 不维护另一套日志系统，不执行评测或决定正式 verdict。

## 边界

- SDK：外部 Agent 业务事件接入、字段规则、脱敏、采集状态、持久化读回验证。
- contracts：不依赖 Inspect 的事件身份和关联校验、共享轨迹结构。
- Evaluator Harness Trace：将原生事件和独立环境状态转换为评分输入；文件快照、轮次和执行模式要求留在适配或评分侧。
- Benchmark：DeepEval 正式评分；旧 Suite 评分仅兼容。Agent 返回成功不等于证据完整或评测通过。

自研 Harness 可直接使用 Inspect；外部 Agent 可使用 SDK 或专用适配。转换轨迹引用来源事件，是原始证据的视图，不能作为额外独立证据计数。

## 接口与历史读取

保留 `TraceCollector`、`TraceContext`、`EventRule`、`InspectEvidenceSink`、`LocalEvidenceSink` 和 `EvidenceReader`。`LocalEvidenceSink` 是历史名称；新写入使用 Inspect。历史 `collection.json` / `events.jsonl` 仅提供只读兼容，不重新落盘或升级历史身份。

`EvidenceReader` 在原生日志存在但损坏时返回 `EXPORT_FAILED`，不会回退历史文件或使用 Agent 内存补齐。内存 manifest 只能降低持久化证据状态，不能把缺失日志变成完整证据。缺失、重复、关联不符、写入失败、未正常结束分别保留诊断及采集状态。

SDK 依赖 Inspect 和共享 contracts，保持独立包。Evaluator 仍声明 SDK 为必需依赖，本轮不改变安装配置。验收与兼容边界见[渐进收敛记录](../../docs/migration/convergence-2026-11-11.md)。
