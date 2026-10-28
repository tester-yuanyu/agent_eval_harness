# 通用、可插拔的 Agent 能力快照生成

用户已确认执行：复用独立 Kit，增加受约束的 LLM 能力抽取和 Adapter 事实入口，输出仍为 Snapshot 3.0。

## 边界

生成流程不依赖 minimal_agent、LLM 厂商、LangGraph 或 Directory 服务。不自动安装插件、不执行输入文档里的导入路径、不把模型推断认定为执行验证。已有 API 和冻结快照保持兼容。工作区已有未提交改动，本次在原目录增量实现，不替用户提交或覆盖。

## 设计

1. `FactDocument` 是版本为 1.0 的输入协议，承载五组现有 Facts、文件来源（相对路径、SHA256、类型）和事实到来源的映射。与最终 Snapshot 3.0 分开版本化。拒绝重复 ID、悬空来源和未知字段。
2. `FactCollector.collect(source_root)` 返回 FactDocument。调用方通过显式 `module:factory` 选择可信本地插件；框架专属读取逻辑留在插件。现有 Adapter 可以通过包装器接入。
3. LLM 路径支持 `prepare` 生成约束、输入 Schema 和显式选中文件的请求包；支持手工调用任意 LLM 后导入候选 JSON，也支持显式 `extractor` 插件。无默认付费调用。
4. 文件来源只允许 source_root 内的普通文件，校验内容摘要；不递归扫描整个项目。请求限定文件大小和总大小。候选文件的来源通过 request manifest 绑定，事实缺少来源会进入缺口报告。
5. 可信 Collector 声明属于 configured，不能据此声称 observed。LLM 独有的支持/不支持声明均归为 unknown，报告保留原声明。LLM 无法新增已注册 Tool；已有 Tool 必须与 Collector 一致。重复事实有差异时拒绝导出，不静默覆盖。
6. 输出交付目录包含 `bundle/`、`facts.json`、`provenance.json`、`gaps.json`、`validation.json`、`manifest.json`。额外报告不进入 Builder 的 bundle；清单绑定根快照哈希、子包哈希及报告文件摘要。输出目录已存在时拒绝写入，失败不留下成功交付。
7. Spec Pack 是调用方选择的评测边界，不能由能力声明反推。附带不依赖 Tool 的 conversation profile，保留任意 `--spec-root`。Module/Intent/Chain 数量不固定。
8. 用非工具客服示例验证：FAQ 回答、追问、转人工建议（无外部转人工接口），声明与可观察输出对应；不虚构生产后端。用 mini_agent 六工具 Collector 验证旧协议等价。
9. 通过独立构建脚本从单一 Kit 源码生成可安装 wheel，包含约束和 conversation profile，只依赖 Pydantic 与 PyYAML。离开仓库、未安装 minimal_agent 时仍可 prepare/import/export/validate/resolve。

## 验收

两类 Agent 均导出合法 Snapshot 3.0；无工具客服链可 resolve；LLM 候选不自行提升支持状态；冲突、路径逃逸、来源变更、插件错误和覆盖写入均明确失败；重复导出一致；原有测试不回归；独立 wheel 在仓库外验证。

Schema/摘要通过只能证明结构与来源完整性。业务事实的正确性、生产就绪和评测通过仍由接入方审查及 Evaluator 确认。
