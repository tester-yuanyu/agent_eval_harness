# Agent 接入与 Provider 复用

文件 benchmark runner 通过 `AgentAdapter` 执行，不直接导入 nanobot。已有 `EvaluationProvider`、`ExecutionSpec`、`AdapterOutput` 和 `ProviderRegistry` 继续复用；新接口补充 Inspect 所需的启动、沙箱、身份与异步采证边界。

| 接口 | 责任 |
| --- | --- |
| `ProviderRegistry.register` / `create` | 保留旧 Provider 工厂注册和 Suite 创建行为 |
| `ProviderRegistry.create_adapter` | 调用工厂的 `create_adapter(config=...)`；不支持 benchmark 的旧工厂明确报错 |
| `runtime_identity` / `fingerprint_sources` | 提供总体及逐执行模式身份，声明 worker、Provider、映射函数等实现文件闭包 |
| `needs_model` / `inspect_model` / `sandbox_spec` | 声明模型需求、Inspect 模型与执行环境，不能静默降低用户指定的隔离级别 |
| `execute` / `execution_kind` | 只接收公开任务，返回观察证据，明确实际执行类型 |
| `EvaluationProviderAdapter` | 在 Inspect 管理的离线 worker 中复用已有 Provider 生命周期，由可信函数完成领域输入/输出映射 |

`NanobotAdapter` 封装原有模块、模型决策与 AgentLoop 分发。配置省略 `provider` 时仍选 nanobot，默认值位于 composition 层；未知 ID 明确失败。core/τ 的独立领域 runner 保留原有适配，本轮不声称所有领域入口都已统一。

自定义接入在可信 Python 代码中注册：

```python
registry.register("my-agent", MyAgentFactory())
run_benchmark(
    tasks, dataset=dataset_identity,
    config={"provider": "my-agent"}, output=output,
    provider_registry=registry,
)
```

工厂实现 `create_adapter(*, config)`；若还用于旧 Suite，同一工厂保留 `create(dataset, ...)`。不从任务 JSON、配置或模型回复读取 Python 导入路径，也不执行其中的代码。新 Agent 不需要给通用 runner 增加按名称判断的分支。

## 旧 Provider 桥接

旧输入 `ExecutionSpec` 与文件 benchmark 的公开任务字典不能直接等同。`EvaluationProviderAdapter` 接受可信 worker 命令、Provider ID/版本、执行投影、观察投影、身份函数和源码列表。worker 示例见 [offline_provider_worker.py](../../packages/evaluator/examples/offline_provider_worker.py)。

1. 工厂固定绝对解释器与 worker 命令；预算取 Provider 声明与本次配置上限的较小值。
2. Inspect `sandbox().exec` 经 stdin 传入公开 `ExecutionSpec` 和 scope，管理超时与取消。
3. worker 在可信代码中创建 Provider，调用 `execute_provider_request`，复用 `create_runtime → run_module/run_full → runtime_metadata → cleanup`。stdout 返回 JSON，诊断日志写 stderr。
4. 父进程核对 Provider ID/版本，还原 `AdapterOutput`。缺失证据不能被投影提升为完整证据，执行成功不等于任务通过。

当前桥仅用于本机离线 Provider，不继承模型/服务凭据，不提供 OS 隔离，也不能要求 Docker 后退回 local。真实模型 Agent 仍需 Inspect model bridge。worker 把终止信号传入 Provider 异常清理路径；Provider 必须清理自己创建的进程和资源，不吞掉终止异常。此协议不为任意不合作程序承诺进程树隔离，SIGKILL 不能保证 finally 执行。

身份函数应覆盖所有行为配置、版本与依赖；源码声明须覆盖 worker、Provider 与投影实现。Harness v4 固定 `runtime_modes`，逐 trial 前后核对源码与运行身份，变化时保留日志并拒绝续跑。冻结任务、旧 Hash 和历史结果不改写；v3/v4 报告都核对原生日志中的结果。

## 可选依赖

```bash
# 核心不安装 mini_agent 或 Langfuse，保留 Inspect、DeepEval。
python3.11 scripts/setup.py --only core
# Evaluator 开发环境含 mini_agent，Langfuse 仍可选。
python3.11 scripts/setup.py --only evaluator
# 显式启用展示/导出。
python3.11 scripts/setup.py --only evaluator --with-langfuse
```

包 extra 为 `agent-evaluator[langfuse]`。删除重复的 `conversation` extra，因为 DeepEval 已是必装。旧 `--optional-metrics` 保留环境选择兼容性；Builder 的可选 DeepEval 与 `mini-agent` extra 保留。约束中的 Langfuse pin 不会触发安装，也不主动删除已有 SDK。

缺少 Langfuse 时核心导入、CLI、离线执行与本地报告可用；显式导出/回读/审核导入给出安装提示。未配置自动交付时为 `DISABLED`；已启用但缺 SDK 时为 `DEPENDENCY_MISSING`。

替换性通过独立离线适配器和旧 `ExternalProvider` 进程桥两组测试验证，不调用模型、不读取 Oracle，不作为真实 Agent 成绩。详见[验收与 mini_agent 评估](../migration/provider-reuse-acceptance-2026-11-04.md)。

## mini_agent 接入 OpenCode

mini_agent 的 Inspect bridge 对 `opencode.ai` 请求补充自己的客户端标识
`agent-eval-suite/0.1.0`，并为每个 trial 生成独立的 `x-opencode-session`。
同一 trial 的多轮和工具续接复用该 session；不会把不同用例合并成同一会话。
实现使用 Inspect 公开的 generation filter，只修改传输请求头，保留原有输入、
工具、预算、日志与判分。其他 API 域名不添加这些请求头。
接入要求见 [OpenCode Go 文档](https://opencode.ai/docs/console/go/#where-can-i-use-it)。

`.env` 保存凭据；运行时显式指定 `--env-file .env` 与模型 JSON 配置。
JSON 中的 `model`、`base_url` 必须与本次选择一致，`api_key_env` 使用
`OPENCODE_API_KEY`。修改 `.env` 的模型或地址不会自动改写 JSON。
DeepSeek 的执行配置显式设置
`inspect_model: "openai-api/opencode/deepseek-v4.1-flash"`，选择 Chat Completions，
并以 `extra_body: {"thinking": {"type": "disabled"}}` 关闭 thinking。
原因是 mini_agent 严格解析 JSON，而 Inspect 的 Responses 桥接会将推理与
内部元数据编码进 `output_text`。更换模型时也需同步检查 `inspect_model`
和供应商参数；不得通过放宽 Agent 输出校验或修改 Oracle 来掩盖协议错误。
本适配仅覆盖 mini_agent 执行 bridge，不表示其他 Agent 或独立模型 Judge
已完成 OpenCode Go 验收。接口返回 402、403 等错误时记录 `INVALID`，
不能据此判断被测 Agent 的能力，也不能宣称真实评测成功链路通过。
