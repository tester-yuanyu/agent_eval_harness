# V3-Only Capability Protocol Design

## 目标

`mini_agent` 工程只保留 Capability Snapshot Protocol v3。删除 v2 的生成、读取、校验、
CLI、制品、文档和测试，但保留现有无版本公共名称与命令路径，并将它们全部切换为 v3。

最终只有一套能力协议事实来源：

```text
capability_specs/
+ MiniAgentCapabilityAdapter / capability_facts
→ capability_snapshot_kit
→ capabilities-v3/
```

Builder 继续只消费完整的 `capabilities-v3/` 目录，不依赖 `mini_agent` Python 包、源码、
YAML 规格或 CLI。

## 公共接口

以下顶层名称继续保留：

```python
build_capability_bundle
export_capability_bundle
validate_capability_bundle
```

它们分别映射到 v3 的构建、导出和校验能力，返回 `CapabilityBundleV3` 或
`BundleValidationResultV3`，只处理 `snapshot_format_version: "3.0"`。

`minimal_agent.capabilities` 保留为无版本公共门面：

```text
minimal_agent.capabilities
├── __init__.py      # 无版本名称映射到 v3
├── cli.py           # 无版本命令委托给 v3 CLI
└── v3/              # 唯一协议实现入口
```

显式的 `minimal_agent.capabilities.v3` API 和 CLI 同时保留。两个 CLI 路径运行完全相同的
v3-only 逻辑：

```text
python -m minimal_agent.capabilities.cli
python -m minimal_agent.capabilities.v3.cli
```

它们生成相同的 v3 Bundle，且都拒绝 v2 输入。

## 删除范围

删除以下 v2 内容：

- `capabilities/` 目录及其 v2 JSON、Schema 和 `.gitkeep`；
- `minimal_agent.capabilities` 下的 v2 `bundle.py`、`catalog.py`、`models.py` 和
  `hashing.py`；
- v2 专属版本常量和协议分支；
- v2 协议文档及只服务于 v2 的迁移说明；
- v2 协议、导出、CLI 和字节兼容测试；
- README 和 v3 文档中的 v2 兼容说明。

当前放在 v2 `versions.py` 中、但实际上属于 Agent 运行时的公共版本信息，需要移动到
不带能力协议含义的模块，再更新 MiniAgent Adapter 的引用。不能因为删除 v2 而丢失
Agent 包版本、模型客户端协议版本或工具注册表版本。

## 保留范围

保留以下 v3 内容：

- `capabilities-v3/` 完整交付目录；
- `capability_snapshot_kit` 通用包；
- `capability_specs/` 自然语言说明与结构化 Front Matter；
- `minimal_agent.capability_adapter` 和 `minimal_agent.capability_facts`；
- `minimal_agent.capabilities.v3` 兼容门面；
- 无版本 Python API 和 CLI 路径，但其语义全部改为 v3。

`PyYAML` 继续作为 Agent 生成端依赖，因为 v3 编译器需要读取 `capability_specs/`。它不是
Builder 的依赖。

## 数据流

无版本 Python API 的数据流为：

```text
IntentRegistry + ToolRegistry
→ MiniAgentCapabilityAdapter
→ capability_specs
→ capability_snapshot_kit compiler/exporter
→ CapabilityBundleV3 / capabilities-v3 directory
```

无版本 CLI 直接委托 v3 CLI，不保留版本探测、v2 分派或自动迁移逻辑。

## 错误与降级规则

以下情况必须直接拒绝，不能转换为 `unknown`：

- 根快照不是格式版本 `3.0`；
- 缺少 `agent.json` 或必需 Schema；
- JSON、Schema、路径、引用、Hash、DAG 或 Bundle Hash 校验失败；
- 输入指向已删除的 v2 Bundle；
- 调用不存在的 v2 专属 API 或模块。

只有通过协议与结构校验后，能力事实缺失或无法解析时，才能在 v3 三态模型中标记为
`unknown`。工程不提供 v2 自动迁移、兼容读取或静默回退。

## 测试策略

实施遵循测试先行：

1. 先修改公共 API 和 CLI 测试，使其要求无版本入口产生 v3，并观察当前 v2 行为失败；
2. 增加仓库边界测试，要求 v2 制品、实现和协议文档不存在；
3. 切换无版本门面和 CLI 到 v3；
4. 移动仍有价值的运行时版本常量；
5. 删除 v2 文件与测试；
6. 验证两个 CLI 导出结果一致；
7. 运行 Builder、QueryUser、v3 Validator、全量测试和 Ruff。

## 验收标准

- 工程不存在 `capabilities/` v2 Bundle；
- 工程不存在 Capability Protocol `2.0` 的实现或兼容解析分支；
- 无版本能力 API 返回 v3 类型并生成 v3 快照；
- 两个 CLI 路径只生成和校验 v3；
- v2 输入被明确拒绝；
- `capabilities-v3/` 仍可独立交付给 Builder；
- Builder 和 QueryUser 契约测试通过；
- 根 `minimal_agent.__all__` 保持现有 13 个公共名称；
- 全量测试、Ruff 和 `git diff --check` 通过。
