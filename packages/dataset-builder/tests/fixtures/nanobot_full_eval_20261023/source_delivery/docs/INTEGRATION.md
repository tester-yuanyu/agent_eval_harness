# Nanobot 能力快照适配

这是可选的源码仓库集成：独立 `capability-snapshot-kit==0.1.0` wheel 加上
nanobot 自己的 Collector。无须修改 Kit、AgentLoop、工具实现或 nanobot 的必需依赖。
Collector 不依赖 `mini_agent`，此目录不随 nanobot wheel 发布。

## 本地验证结果

本次最终交付位于 `exports/nanobot_snapshot_v2/`，首先阅读其中的 `coverage.md`。

- 23 个自动发现的工具类中，本配置注册 21 个；全部 21 个进入快照，没有漏项。
- CLI apps 与图像生成关闭；另一个由核心单独注册的 `my` 也关闭。
- 8 个子系统、11 份内置 Skill 文件、32 条事实，事实来源覆盖 32/32。
- 47 份来源摘要及外层清单中的 54 份交付文件摘要已核对。
- 30 条 unknown 缺口保留在 `delivery/gaps.json`；对话链解析结果为 unknown。
- 10 项集成测试及 58 项相邻注册/加载测试通过；新集成的 Ruff 和 BasedPyright 通过。
- 当前环境未安装 `minimal_agent`；使用的 Kit 来自独立 wheel。

上述测试验证适配、导出和协议一致性，不是 Agent 业务执行评测。
重新运行时，选择尚不存在的输出目录，例如 `exports/nanobot_snapshot_v3`。

## 安装与生成

在已安装 nanobot 依赖的项目虚拟环境中安装独立组件（替换 wheel 路径）：

```bash
.venv/bin/python -m pip install /absolute/path/capability_snapshot_kit-0.1.0-py3-none-any.whl
.venv/bin/python -m integrations.capability_snapshot \
  --source-root "$PWD" --output exports/nanobot_snapshot_v1
```

输出目录必须不存在。已有交付不会覆盖；配置或代码变化后生成新的版本目录。

```text
exports/nanobot_snapshot_v1/
  delivery/
    bundle/                 # 原有 Snapshot 3.0 消费协议
    facts.json
    inputs.json
    provenance.json
    gaps.json
    validation.json
    manifest.json           # Kit 交付完整标志
  coverage.json             # 工具、模块、技能盘点及边界
  coverage.md               # 中文覆盖报告
  selection.json
  resolution.json           # 对话链预期为 unknown
  collection-manifest.json  # 标准交付及外围报告的 SHA256，最后写入
```

再次验证并解析：

```bash
.venv/bin/python -m capability_snapshot_kit validate \
  --input exports/nanobot_snapshot_v1/delivery/bundle
.venv/bin/python -m capability_snapshot_kit resolve \
  --input exports/nanobot_snapshot_v1/delivery/bundle \
  --selection exports/nanobot_snapshot_v1/selection.json
```

也可以直接用 Kit 的标准插件入口（只生成标准交付，不带覆盖报告）：

```bash
.venv/bin/python -m capability_snapshot_kit export \
  --collector integrations.capability_snapshot.collector:create \
  --source-root "$PWD" --profile conversation --output exports/nanobot_delivery_v2
```

## 本次配置和信任边界

`offline.json` 指定 `profile_id`、`file_tools`、`exec_tool`、`web_tools`。
后三项为严格布尔值，默认 true。自定义配置须在源码根目录内，通过
`--profile-config relative/path.json` 选择；未知配置字段会拒绝。

Collector 使用真实 ToolLoader、ToolContext 和 ToolRegistry，初始化真实的
消息总线、会话管理、cron、子 Agent 管理和 shell 会话管理对象。临时工作区及
会话文件只存在于临时目录，采集后删除；不会执行工具、启动调度器或发送模型请求。
独立 `my` 运行控制、CLI apps、图像生成、外部 entry-point 插件和 MCP 连接在此配置中关闭。
不读取 `~/.nanobot/config.json`，不导出凭据，不代表用户当前 gateway 的配置。

工具名、描述、function schema 和并发属性直接来自真实注册对象。
风险等级只是适配器的保守标签；幂等性、重试、权限与副作用没有逐工具审计。
`requires_confirmation=false` 表示该采集配置没有统一确认网关，不能替代具体工具的权限判断。
所有工具执行能力均为 unknown，已注册不等于业务调用成功。

`configured` 是 Collector 对该离线配置的声明；来源有 SHA256，但不证明语义正确。
SDK 返回对象的结构取自真实 RunResult dataclass，响应证据指向可观察的返回接口，
不包含运行轨迹。对话、记忆、MCP、外部服务与业务任务效果仍为 unknown。
内置 Skill 只盘点文件，不将 Markdown 说明直接提升为执行能力。
提供商和渠道按子系统记录，没有逐个启动或验证。

本次使用 Kit 内置 conversation 评测规范，包含工具快照，但没有工具执行评分器。
“注册表导出覆盖率”只对本配置的真实注册集合有意义，不是“所有 Agent 能力覆盖率”。
真实 LLM 提取、业务意图细化和运行中 Agent 的注册表接入仍需后续配置与验证。

## 测试

```bash
.venv/bin/python -m pytest tests/test_capability_snapshot_integration.py \
  tests/tools/test_tool_registry.py tests/tools/test_tool_loader.py \
  tests/agent/test_tool_loader_scopes.py tests/agent/test_tool_loader_entrypoints.py -q
.venv/bin/python -m ruff check integrations tests/test_capability_snapshot_integration.py
```

未安装 Kit 时集成测试会跳过，nanobot 正常功能无需此依赖。
