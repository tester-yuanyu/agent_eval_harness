# 报告与 Langfuse 联动实施计划

> 执行技能：superpowers:executing-plans；用户已确认聊天中的分工、结构化诊断、可选领域配置、标签和 Dashboard 方案，继续在当前工作树完成，不重复索要确认。

**目标：** HTML 和 Langfuse 使用同一份有版本、可追溯的诊断结果，报告直达单条 Trace，并提供按统一口径展示的 Dashboard。

**架构：** 纯本地诊断层读取保存结果和 Hash 绑定的契约，输出独立派生产物；HTML 只渲染它。领域别名由可选配置提供。独立 Langfuse 展示模块负责已导出 Trace 的展示注释、链接清单及 Dashboard，不重复上传原始观察记录、不产生正式评分。

**技术：** Python / 已安装 Langfuse SDK / 离线 pytest / 静态 HTML。

## 边界

- 不调用模型、不重评分、不修改冻结任务或历史 results/trials/Inspect 日志。
- core 无需 mini_agent、Langfuse SDK；远端操作仅显式命令触发。
- 诊断缺失不代表通过，不把诊断自动变成 0/1 正式分数。
- 版本与 Hash 绑定诊断、配置、源结果；未核验或目的地不匹配的链接不显示为已验证。
- 主集与两次补跑分开，Dashboard 过滤固定 run；跨版本不合并趋势。

## 任务

- [x] 1. 用失败测试覆盖可选配置、证据绑定及建议条件；移出业务别名，输出共享诊断 JSON 与历史内容 Hash 归档。
- [x] 2. 报告消费共享诊断；校验本地链接收据，提供逐条 Trace 链接与未导出状态，保留全部离线 Trace。
- [x] 3. 扩展独立 Langfuse 展示模块与显式 CLI；用 mock SDK 检查标签/metadata、回读、幂等与源绑定；不改变正式 score。
- [x] 4. 使用当前授权项目同步 32 条 Trace 的展示诊断，配置主集 Dashboard 并回读/浏览器验证。
- [x] 5. 重建 HTML/ZIP，检查原始 Hash、密钥、测试与 core 离线运行，记录验收。
