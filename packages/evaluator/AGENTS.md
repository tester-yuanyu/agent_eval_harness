# Evaluator 扩展约束

本包提供任务数据集 + Harness 基准。用户于 2026-11-01 授权使用 DeepEval 正式评分，并保留 Inspect 执行与日志。原有 Inspect 评分路径仅用于历史兼容。维护 Python 命名空间、冻结契约、Provider 隔离、独立证据、领域结论及历史结果兼容性。

- 使用本包配置执行检查：`python -m pytest -c pyproject.toml tests` 和 `ruff check --config pyproject.toml src tests examples scripts`。
- 迁入代码沿用扩展包现有风格；新增 Inspect 接口应有类型注解。不要跨上游与扩展包批量改格式。
- Suite、证据与审计存储明确使用本地文件；不得静默解释远程 URL，也不得执行数据或配置文件中的代码。
- Oracle／参考答案不得进入 Provider 的 ExecutionSpec 或 Agent 消息。业务任务的 Inspect Sample target 保持为空，由可信 Scorer 私下解析 Oracle。
- Agent 实现保持在独立包中。SQLite Provider 是真实隔离的本地测试环境，不是 Docker 沙箱；容器支持与验证状态必须明确。
- 付费模型测试须显式启用。默认本地评测不上传托管服务。
- 使用 Inspect 的公开执行／日志 API 和 DeepEval 的公开 Metric API。领域专有要求留在扩展包；修改上游核心前须证明公开 API 存在缺口，并添加针对性测试。
