# 新 Agent 评测交付接入

> 本文属于旧 Suite／Provider 兼容路径；其中 Inspect 评分、指标和产物约定不适用于当前任务基准。新基准由 Inspect 执行与记录、DeepEval 正式评分，入口见[包说明](../README.md)。以下包内命令在 `packages/evaluator` 目录执行。

Evaluator 接收本地交付目录或 ZIP，校验来源和契约，将能够确定转换的候选记录编译为现有 Suite，再交给 Inspect 执行、评分和聚合。原始交付和候选状态保留；缺失执行绑定、参考答案或独立证据的记录进入导入账本，不能以推测补齐。

## 命令

先校验并查看哪些记录可以执行：

```bash
../../.venvs/evaluator/bin/agent-evaluator validate \
  --input /path/to/delivery.zip \
  --output-dir artifacts/new-agent-intake
```

`validate` 编译所有生成的分区，不创建 Agent 运行时。省略 `--output-dir` 时，产物保存在本地临时目录，命令输出包含 `intake.json` 路径。

已注册的 Nanobot 本地 SDK 适配器可以用 Agent 项目路径选择：

```bash
../../.venvs/evaluator/bin/agent-evaluator run \
  --input /path/to/delivery \
  --agent-root /path/to/nanobot \
  --output-dir artifacts/nanobot-evaluation
```

其他 Agent 使用显式提供的受信执行绑定：

```bash
../../.venvs/evaluator/bin/agent-evaluator run \
  --input /path/to/delivery.zip \
  --binding /path/to/trusted-binding.json \
  --output-dir artifacts/new-agent-evaluation
```

没有 `--agent-root` 或 `--binding` 时，静态契约分区仍可执行，需要 Agent 运行时的记录保留在 blocked 账本中。未知 Agent 的源码不能自动推断成可信执行适配器。

`--input` 也支持既有 Suite JSON、包含唯一 `suite.json` 或 `*.suite.json` 的目录，以及既有 EvalCase JSONL。它们复用原来的编译流程；旧 `--suite`、`--dataset` 命令继续可用。`--input`、`--suite`、`--dataset` 必须选其一。执行绑定只用于候选交付，`--agent-root` 与 `--binding` 不能同时使用。候选交付也不能混用旧式 Provider、过滤、Judge 或运行覆盖参数。

## 支持的交付

当前识别版本为 1.0 的 `agent_candidate` 和 `nanobot_candidate` 协议，格式别名不决定 Agent 身份。身份来自验证后的 Agent 契约和显式绑定，两者必须一致。目录内已识别的 candidate `manifest.json` 优先于生成的 Suite 文件。

导入检查 Manifest、数据文件、源引用、JSON Pointer 和 SHA-256，将原始 ID 映射为文件系统安全的 EvalCase ID，并保留反向映射。ZIP 中的越界路径、链接、重复路径、歧义根目录和超限内容被拒绝；数据文件中的命令、模块路径或程序入口不会被执行。

能力包目录优先采用已受顶层 Manifest hash 约束的 `source_delivery/manifest.json` 中的 `bundle_path`，兼容 `bundle`、`delivery/bundle` 等布局。没有该路径声明时，仅接受来源清单中唯一的 `*/bundle/agent.json`；明确声明的路径越界或未受清单绑定会被拒绝，不回退猜测其他目录。

生成的用例仍使用 `EvalCase`：

- `execution.adapter_input` 含操作输入、fixture 声明及必要的来源 hash；不含参考答案、Oracle checks 或权重。
- `oracle.evaluation.checks` 保存私有 `observations_match` 条件。
- Provider 只返回实际 observations，由既有 Inspect Scorer 比较。
- `equals` 比较严格 JSON 值；`contains`、`not_contains`、`ends_with` 使用文本语义；`schema_valid` 校验本地 JSON Schema，不解析远端引用。
- 路径使用标准 JSON Pointer，例如 `/result/text`、`/items/0/name`；缺失值与明确的 JSON `null` 区分。
- `returned` 是 Agent 返回值，不能证明文件、数据库或其他独立状态。`independent` 只能使用明确配置的 Provider 环境快照。缺失证据产生 unknown；已经观察到的不匹配不会被其他缺失值覆盖。

静态 schema/声明检查作为独立 `framework_self_test` 分区运行，业务行为作为 `agent_benchmark` 分区运行。当前候选导入始终是 provisional，保留 DRAFT/审批状态，不升级为冻结基准。未支持的操作和待上游修复的契约分别记录原因，不伪造失败 Trial。

## JSON-over-stdio 绑定

绑定文件由操作者显式提供，必须与交付数据分开管理。示例：

```json
{
  "version": "1.0",
  "agent_id": "my_agent",
  "adapter": "stdio",
  "python": "/absolute/path/python",
  "argv": ["/absolute/path/evaluation_worker.py"],
  "env_names": ["AGENT_API_KEY"],
  "timeout_seconds": 30,
  "max_output_bytes": 1048576
}
```

Python worker 推荐使用上例的显式 `python` 与绝对脚本路径；Provider 将两者组合后直接启动，不经过 Shell。`env_names` 只引用当前环境变量的名称，绑定文件不能包含凭据值；评测元数据只记录名称和文件身份。

`prepare_input` 会在本机为所选解释器、脚本或可执行文件生成 SHA-256 身份快照。绑定文件格式保持不变，操作者不需要添加这些 hash。生成的 Suite 在 Provider 配置中保存与 `binding` 并列的 `runtime_files`，形式为 `[{"path": "/absolute/runtime/file", "sha256": "…"}]`，并纳入编译身份。Provider 预检和每次启动前重新校验所需文件集合与 hash；缺失身份或文件变化会拒绝执行。stdio 还会绑定参数中绝对路径的 `.py`、`.js`、`.mjs`、`.cjs`、`.sh` 文件；不应依赖相对路径隐式发现 worker。静态适配器没有外部执行文件，使用空列表。

这些记录绑定的是显式选定的运行文件，不代表整个 Python 环境、动态库或任意 worker 依赖都被完整封装。更新运行文件后应重新准备并编译 Suite，保留新的运行身份用于审计。

stdio worker 是操作者明确选定的受信本地进程。临时工作目录、有限环境变量、超时、输出限额和进程组清理提供生命周期控制，不能阻止任意 worker 访问宿主文件或网络；当前适配器没有提供操作系统或容器安全沙箱。需要此类限制时，应由显式运行环境提供并单独验证。

worker 从 stdin 接收一个 JSON 请求：

```json
{
  "protocol_version": "1.0",
  "execution": {
    "user_input": "operation description",
    "tool_profile": "candidate",
    "adapter_input": {
      "input": {"operation": "echo", "value": "actual input"},
      "preconditions": []
    }
  }
}
```

上例省略了 `ExecutionSpec` 的默认字段；实际请求包含完整执行协议。请求不包含 `oracle`、评分预期或 Suite 文档。stdout 必须只输出协议响应，诊断信息使用 stderr：

```json
{
  "protocol_version": "1.0",
  "observations": {"result": {"text": "actual output"}}
}
```

worker 不返回分数、PASS/FAIL 或独立状态证明。stderr、Agent 自述和 stdout 中的 COMPLETE 字段不会自动成为独立业务证据。

Nanobot 当前本地适配范围是 `RunResult` 构造/序列化与 `result_from_response` 返回对象操作。固定 worker 使用指定项目的 Python 环境，仅按 Evaluator 固定路径直接加载 hash 已绑定的 `nanobot/runtime_context.py` 与 `nanobot/sdk/types.py`，跳过 `nanobot/__init__.py` 和 `nanobot/sdk/__init__.py`，避免初始化完整 Agent。fixtures 是请求中明确声明的内存对象，不启动模型、工具或真实会话。

上述两个文件还需匹配可信来源的 hash；包中缺失的依赖 hash 由独立运行身份记录，不冒充原始交付的声明。固定 worker 的受支持操作和模块集合有限；这不构成对任意修改后 Python 源码的操作系统级权限限制。未支持的工具、模块、会话边界留在 blocked 账本。Evaluator 不修改 Nanobot 或 Dataset Builder 源码。

## 结果与退出码

导入产物包括 `intake.json`、原始输入快照、ID/来源映射和生成的 Suite。每个非空分区在 `runs/static` 或 `runs/behavior` 下产生标准正式运行目录。所有分区在任一 Agent 运行时创建之前完成编译。

`intake.json` 的 `counts` 是静态、业务和 blocked 的记录数量；`runs` 只引用正式运行 ID 和报告路径。业务通过率从正式结果的 summary 读取，不在导入报告中重新计算。blocked-only 交付也产生账本，但不生成虚构评分。静态、草稿和覆盖不完整的导入结果不能通过发布门禁。

| 退出码 | 含义 |
| --- | --- |
| `0` | 校验或执行流程完成，且无 blocked 记录；业务质量结论仍需读取正式结果或运行 gate |
| `2` | 输入、绑定或编译校验失败，未启动分区运行时 |
| `3` | 运行/评测基础设施错误；优先于 blocked 状态 |
| `5` | 交付有效但仍有 blocked 记录，已执行其余可运行分区（validate 仅校验） |

默认不调用付费模型或上传托管系统。显式配置的外部 worker 是否调用模型取决于操作者选择的 Agent；Langfuse 导出仍需单独运行 `export-langfuse`。
