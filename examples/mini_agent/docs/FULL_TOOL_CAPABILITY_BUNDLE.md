# 包含全部工具定义的能力快照

完整评测配置对应 7 个模块、7 个意图、6 个工具、5 个 Scope、2 条关键链路和 1 条端到端链路。`unsupported` 意图没有工具，所以工具数量为 6。

本配置的六个工具都有可调用的 handler，统一标记为 **test_fixture**。它们操作独立的内存数据，供 Builder 理解契约、供本地集成测试执行，不表示已经连接生产服务。现有零工具冻结包继续保留。

## 位置与重新生成

在 `examples/mini_agent` 目录运行；`examples` 是仓库内的示例集成，不随 minimal-agent 安装包分发。

```bash
../../.venvs/evaluator/bin/python -m examples.full_tool_fixture.export \
  --output exports/full_tools_fixture_v1
```

该命令拒绝覆盖已存在的交付目录；需要重新导出时选择新目录。产物结构：

```text
exports/full_tools_fixture_v1/
  bundle/agent.json
  bundle/tools/*.json
  bundle/...其他快照及 schemas
  capability_inventory.json
  capability_contract_gaps.json
  validation_report.json
  manifest.json
  README.md
```

**交给 Builder 的是整个 `bundle/` 目录，根入口是 `bundle/agent.json`。** 外层报告描述当前完整性与缺口，Manifest 为各文件绑定字节 Hash。

`capability_inventory.json` 列出全部 17 个 Module／Intent／Chain 目标、6 个工具和 Scope／Chain × Intent 的组合解析。它是能力清单，不是能力—案例覆盖矩阵；本命令没有生成评测用例。

## 六个工具及实现范围

| 工具 | 参数约束 | fixture 行为 | 返回 data |
| --- | --- | --- | --- |
| query_information | resource_type、environment 必填 | 查询本实例资源；仅允许 test 环境 | resources 列表 |
| prepare_resource | 增加正整数 count、非空 request_id | 在本实例创建资源；同 request_id 同参数返回原结果，冲突拒绝；单次最多 1000 | resources 列表 |
| query_user_info | user_id／room_id／email／phone 至少一个，多条件 AND | 对示例用户做精确匹配 | user 对象或 null |
| query_gift_info | gift_id／gift_ids／gift_name 三选一，limit 可选 | 按 ID 或不区分大小写的名称子串查找；ID 列表必须全部存在 | gifts 列表 |
| query_pool_config | gift_id／pool_id 二选一 | 查询奖池或包含礼物的奖池 | pools 列表 |
| add_gift_to_backpack | 用户、礼物选择各择一种模式 | 外部 fixture owner 授权一次后才能写入；先验证全部 ID，再记录模拟发放 | grants 列表 |

返回对象具有字段级 Schema：ID、名称、资源环境、邮箱、手机号、数量、有效期等均声明类型、必需字段及适用约束；禁止未声明字段。工具成功、空结果和业务失败的 data Schema 分别声明。fixture 实际成功返回也通过这些输出模型验证。

所有匹配规则、结果结构和资源准备行为都属于这个明确版本的示例契约；它们不是对未知生产后端的推断。生产接入需用生产契约和 handler 再生成独立能力包。

## 运行和导出使用同一工厂

```bash
../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli export \
  --tool-registry-factory examples.full_tool_fixture:create_registry \
  --require-complete-tools \
  --output exports/full_tools_raw

../../.venvs/evaluator/bin/python -m minimal_agent.capabilities.cli validate \
  --input exports/full_tools_raw
```

运行 CLI 使用同一个显式工厂：

```bash
../../.venvs/evaluator/bin/python -m minimal_agent.cli run "查询用户 ID 10001" \
  --tool-registry-factory examples.full_tool_fixture:create_registry
```

运行 CLI 仍需要原有模型环境配置，可能调用付费模型；仅导出不调用模型。每次 factory 调用创建独立状态。需要多次调用共享 fixture 状态时，程序化创建一次 Registry 并交给同一 Agent。

工厂格式为 `module:callable`，必须返回 ToolRegistry。这个参数会执行用户明确选择的本地 Python，不能从不可信能力包或案例字段自动加载。

`--require-complete-tools` 检查所有业务 Intent 所需工具都已注册，缺失时在写文件前失败。默认不选择工厂仍为零工具配置，会在 stderr 给出 `tool_count=0` 提示，stdout 保持机器可读 JSON。

接入方可以使用 `minimal_agent.runtime.tool_binding.bind_tools(contracts, handlers)` 统一装配：契约重名、缺失 handler、多余 handler、不可调用 handler 均被拒绝。

## 尚未补齐的业务能力

- 六个工具的生产后端均未连接；完整注册不等于生产可用。
- `add_backpack_gift` 仍在 NEED_CONFIRMATION 停止，没有确认后恢复状态机。fixture 的一次性外部授权用于直接工具测试，不是 Agent 的会话确认功能。
- 上下文继承、状态覆盖、取消和会话清理未实现，context 仍为 unsupported。
- `prepare_resource` 现有 Intent 使用 read policy，而本 fixture 创建资源；生产语义和确认策略需另行确定。
- 礼物 Intent 要求 environment，但原工具参数模型无该字段；当前仅允许隔离 fixture，真实写入前需明确环境绑定。
- 各层 JSONL、能力—案例覆盖矩阵和人工审核不由快照导出完成。

这些限制记录在 `capability_contract_gaps.json`。组合解析为 supported 只代表声明的 requirement 和证据满足，不能替代实际执行验收。
