# 能力快照一致性与跨 Agent 复用

本轮落实代码 review 的五项改造。通用快照框架继续位于 `packages/contracts/src/capability_snapshot_kit`，不导入 MiniAgent。MiniAgent 特有的事实规则保留在其 Adapter/Collector 中。

## 职责与变化

| 层 | 位置 | 本轮变化 |
| --- | --- | --- |
| 通用快照框架 | capability_snapshot_kit | JSON 语义描述协议、显式模块来源绑定、manifest 最后发布及失败清理 |
| MiniAgent 适配器 | minimal_agent/capability_facts、capability_adapter | 实际 normalizer/constraint/completion policy 的参数和顺序进入语义身份；提供配置实现来源 |
| MiniAgent 采集/导出 | examples/full_tool_fixture | 单次 FactDocument 采集，从同一文档生成 bundle 与来源记录；校验实际加载模块路径 |
| MiniAgent 运行时 | runtime/agent.py | 新增可选 `intent_registry`，默认行为不变 |
| 第二个 Agent | examples/customer_service | 使用同一个来源绑定和通用导出协议，无 MiniAgent 运行时依赖 |

因此，这不是完全不触及 MiniAgent 的插件修改：运行时增加了一个可选注入参数，特有规则由其适配器描述；通用框架本身可以被其他 Agent 独立使用。

## 修复的行为

1. 改变语义约束、normalizer 参数或顺序、completion policy，会改变新快照的语义身份。内置规则使用明确类型、版本和配置；自定义实现必须显式提供描述，禁止根据类名或 repr 猜测语义。
2. 来源绑定核对当前模块实际 `__file__` 与指定 source_root。来自另一个 checkout 的文件即使自身 Hash 正确，也不能作为当前加载实现的来源。配置的参数模型、规则和工具 handler 来源同样进入对应事实记录；缺少文件来源或超出 source_root 拒绝。
3. full fixture exporter 共用一套 registry、一次 FactDocument 采集。bundle、collected_facts 和 audit 从同一份事实生成，不再独立采集两次。
4. 通用 ingestion 与 full fixture exporter 使用同一发布函数。独占创建输出，manifest 最后落盘；失败只清理本次新建的部分交付，不覆盖已有结果。
5. runtime 与 Adapter 可显式使用同一 IntentRegistry。现有默认构造方式不变。

`full_tool_fixture` Collector 专门服务 MiniAgent，拒绝 Adapter 子类以防遗漏覆盖方法的来源；其他 Agent 应实现自己的 Collector，不应伪装为 MiniAgent Adapter。

## 语义协议

共享接口：`capability_snapshot_kit.semantics.SemanticProvider`。描述示例：

```python
class MyNormalizer:
    def snapshot_semantics(self):
        return {
            "component_id": "my_agent.normalize_phone",
            "version": "1.0",
            "parameters": {"country_code": "86", "strip_spaces": True},
        }
```

只接受原生 JSON dictionary：类型标识、版本及 parameters；拒绝模型实例绕过校验、任意对象、集合、非有限数、非字符串对象键。规则列表顺序保留。共享函数 `describe_semantics` / `validate_semantics` 返回独立副本。

这些是由实现方负责的语义声明，不是自动形式化证明。改变规则实现时，仍需维护其版本和声明；source Hash 与实际 runner 身份另行记录。不能因此将静态 supported 当成实际运行通过。

## 其他 Agent 接入

1. 实现通用 `CapabilityAdapterV3`：返回 Agent、Module、Intent、Tool、Evidence Facts。也可直接构造现有 `FactDocument`。
2. Agent 自己确定 registry/配置来源，并给行为相关规则提供明确语义描述；通用框架不扫描业务 AST。
3. Agent-owned Collector 显式传入相关模块，调用 `ingestion.sources.bound_module_sources` 绑定来源，并填写逐事实 origins。源目录必须对应实际加载的实现。
4. 使用 `ingestion.service.export_delivery` 及对应 capability specs 导出；共享层完成 reconcile、编译、校验和不可变交付。
5. Builder 的执行适配仍需由具体 Agent/领域提供。能力快照可导出不代表现有 reference runner 能执行任意 Agent。

客服 Agent 的隔离测试在子进程中主动禁止 `minimal_agent` 导入，仍能完成 collector → portable compiler → validate → delivery。它是跨 Agent 复用的可执行证据，不要求复制 MiniAgent 源码。

MiniAgent 配置同源示例：

```python
intents = build_default_intent_registry()
tools = create_registry()
agent = MinimalAgent(model_client, tools, intent_registry=intents)
adapter = MiniAgentCapabilityAdapter(intents, tools)
```

## 版本与兼容

- Snapshot 文件协议仍为 v3；不在 bundle 中增加 JSON 清单，不修改既有 Hash 算法。
- 新 Agent 契约为 `mini-agent-capability-contract-v4`；新 Intent 契约在原版本上加 `+semantics-v2`。实际规则描述保存在现有 parameter_semantics 的 execution_semantics 中。
- 新导出内容应产生新的 capability_bundle_sha256；历史冻结文件和 `output/mini_agent_full_eval_20261111` 保留原样。
- 旧快照仍可校验和读取；新实现需要重新导出、生成并运行 reference，不能将旧证据冒充新运行器的验证。
- 共享底层 `export_capability_bundle_v3` 的历史替换式 API 不改；需要不可变交付时使用 ingestion/full fixture delivery 入口。
- `bound_module_sources` 校验磁盘来源及模块位置，不是内存字节码认证。采集 CLI 应使用正确环境的新进程；不支持把修改磁盘后未重载的长驻进程当作新代码执行证明。

## 验收

- Builder：378 passed / 5 optional skipped；Evaluator：1529 passed / 9 optional skipped；MiniAgent：337 passed / 1 paid-smoke skipped；contracts：35 passed；根 integration：61 passed。
- 独立审查发现自定义规则来源遗漏和模型实例绕过 JSON 校验，均先复现失败、修复并通过增量复核。最终无未解决的重要审查问题。
- Ruff 与 git diff --check 通过。
- 全新 Git 克隆叠加当前工作树修改，独立安装 builder/evaluator，两个环境 pip check 通过；确认新克隆生产源码与当前工作树一致。
- 新 builder 环境不安装 minimal_agent；客服 Agent 在主动禁止导入 MiniAgent 的子进程中通过采集、编译、校验与交付。
- 新克隆完成 full fixture 导出 → generate-full → validate-full → readiness；历史 full delivery 同样可 validate。源码目录检查、自定义语义、单次采集专项在新环境通过。
- 新 bundle Hash：`2da8731dd0df1a93a03b7b7be2f4252d87fb3d9be4a485800ea4383c37f54dbe`；旧 full fixture Hash：`215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c`。
- 新快照包含 7 个 Intent 的 execution_semantics。Builder 对这些新语义尚无专用 stimulus/predicate 绑定，明确追加 7 项阻塞义务：新交付共 854 项（365 行为、202 静态契约、287 阻塞）。这是新证据暴露的待适配范围，没有缩减分母或声称已验证。
- P0 实际 reference 验证仍为 2/365；整包 release_ready=false。该改造修复快照一致性，不增加 MiniAgent reference runner 的执行覆盖。
- 已逐文件核对此前 `output/mini_agent_full_eval_20261111` 的 capability delivery 和 dataset manifest Hash，原产物字节保持不变。

安装与端到端验收日志保存在 `tmp/snapshot-hardening/`，本轮包回归摘要为 `tmp/snapshot-*-regression.log` / `tmp/snapshot-*-final.log`。未调用真实模型或托管服务，未审批冻结正式数据，未暂存或提交代码。
