# 能力快照一致性与跨 Agent 复用改造

用户已批准上一轮 review 的五项改造，确认通用插件应可复用于其他 Agent。沿用现有工作树，直接实施并进行一次独立审查。

## 边界与设计

- shared capability_snapshot_kit 负责语义描述协议、来源与实际加载模块的绑定检查、不可变交付发布；不得依赖 minimal_agent。
- MiniAgent Adapter 负责明确列举内置 normalizer/constraint/policy 的类型、版本与参数，未知自定义实现必须提供通用语义描述接口。保持规则顺序，将完整描述纳入新 Intent 契约版本与 Hash，v3 JSON 布局不变。
- MiniAgent runtime 仅新增可选 intent_registry 注入参数，默认行为不变。现有 API 调用方式保留。
- Collector 一次性收集 FactDocument，full exporter 从这份文档编译 bundle 和生成 sidecar。核对实际导入模块路径和源目录；导出前复核源 Hash。不声称签名认证或检测任意进程内恶意篡改。
- 交付目录独占创建、manifest 最后发布，失败清理本次创建的部分结果；不改变旧底层可替换 bundle API 的兼容语义。
- 新语义使用新契约标识/Hash；历史冻结文件、Hash 算法及已生成评测集不重写。无需插件宿主重构或 resolver 搬迁。

## 任务与验收

- [x] 语义描述：先复现约束/normalizer 配置变化同 Hash，再验证参数、顺序和 policy 变化产生不同身份；自定义实现没有描述时拒绝。
- [x] 运行配置：验证自定义 registry 同时用于 runtime 与 adapter；默认行为回归。
- [x] 来源与单次采集：错误 source_root 拒绝；新进程/正常源码路径可用；factory 只调用一次，编译 Facts 与导出记录一致。
- [x] 通用交付发布：manifest 最后出现，故障不残留最终交付，不覆盖已有目录。MiniAgent 和通用 ingestion 共用。
- [x] 跨 Agent：不安装/禁止导入 minimal_agent 的环境中运行独立客服 Agent 的采集、编译、校验与发布；保留通用协议可用性。
- [x] 包回归、独立审查、全新克隆安装及离线生成/就绪验收；记录新旧 Hash 与兼容边界。

## 重点审查

遗漏自定义规则参数、描述返回非 JSON 值、两次采集、非当前源码目录、来源导出期间漂移、发布失败/并发已有目录、共享层反向依赖 MiniAgent。

## 执行记录

用户授权按已 review 方案实施，采用当前会话直接实现和一次独立审查，不重复索要批准。

新语义默认用于未来导出，发布 `mini-agent-capability-contract-v4` / Intent `+semantics-v2`；仅保留 v3 文件协议，不复写历史产物。测试确认行为相关配置影响新 Hash。

审查追加两个边界修复：实际配置组件来源逐事实绑定（collector 不接受 Adapter 子类）；语义入口只接受原生 dict，拒绝模型实例绕过校验。详细结果见 [验收与复用说明](snapshot-hardening-2026-11-11.md)。
