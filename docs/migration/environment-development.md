# 领域 Environment 开发约定

## 边界与入口

新 Harness 使用 `eval_framework.environments.Environment`，定义位于 `environments/base/protocol.py`；只依赖标准库。Environment 管理公开任务状态、业务规则、工具实现与可信快照，不引用 Agent SDK、ToolRouter 实现、Oracle 或 Scorer。Harness 调用生命周期，ToolRouter 校验 schema 并调用 step，Inspect 保存 transcript 和管理沙箱生命周期。

文件主入口为 `SandboxFilesEnvironment`。`FileToolsEnvironment` 保留旧同步 API，供离线测试与旧调用使用；`AsyncFileToolsEnvironment` 是其新接口适配器，不提供 OS 隔离，也不替代生产沙箱。nanobot 原生进程桥在 `integrations/nanobot/environments/`，旧导入路径保留转发。

## 新领域最小接口

- `async reset(initial_state: dict[str, Any]) -> None`：只接收公开执行状态，创建本 sample 的领域状态；失败不能继续试验。
- `tool_schemas() -> list[dict[str, Any]]`：返回独立的 JSON Schema 工具声明。只使用当前 ToolRouter 能无损投影到 Inspect 的 schema 约束。
- `async step(name: str, arguments: dict[str, Any]) -> str`：执行一个允许的工具操作，返回可进入模型消息的字符串；不得暴露私有答案。
- `async snapshot() -> dict[str, Any]`：独立测量状态，返回可 JSON 序列化且与内部状态不共享可变对象的快照。
- `async teardown() -> None`：清理本实现拥有的资源；Inspect 拥有的沙箱由 Inspect 清理，避免提前删除证据。

实例按 sample 创建，不能跨 sample 共享可变状态。重复 reset 的行为由领域定义：offline 会替换临时工作区；sandbox 仍依赖 Inspect 新建 sample，保留先写 fixture 再核对完整状态的历史行为，不会清空未知残留。

`Protocol` 用于结构化类型约束，不等于运行时自动验收。必须通过真实 Harness 的契约测试验证 schema、状态变化、错误恢复、快照和清理。

## 错误分类

工具参数/规则错误、读取不存在的业务目标等抛 `ToolExecutionError`，供 Agent 恢复；沙箱失败、worker 响应损坏、存储故障抛 `EnvironmentFailure`。同样的文件错误出现在 reset/snapshot 时，意味着状态装配或证据测量失败，应终止试验。取消和 Inspect 的 `LimitExceededError` 保留原样，不当作 Agent 可修正参数错误。

## 文件公共工具与沙箱交付

`_fs_utils.py` 是文件路径和快照实现的唯一源码，`local_files.py` 只是兼容入口。旧本地/nanobot 策略允许工作区内绝对路径并限制每个快照文件不超过 2,000,000 字节；沙箱策略拒绝绝对路径、不增加该大小限制。保持 UTF-8、原始换行、排序和 symlink/traversal 拒绝行为。策略收敛属于独立行为变更，不能随目录迁移悄悄修改。

`file_tools/payload.py` 只读取已安装包中的 `_fs_utils.py` 和 `worker_script.py`，装配自包含可信源码供 `python -I -c` 使用；动态任务值通过 stdin JSON 传入，绝不插入源码。不要求沙箱安装 Evaluator。nanobot 扁平 worker 的模块闭包由 `integrations/nanobot/sources.py` 声明；新依赖要进入 bundle 和源码 Hash。旧 worker 文件仍可独立执行。

沙箱隔离能力取决于 Inspect backend 和配置；local 不是 OS 沙箱。网络/资源限制需要明确配置，不能仅因使用 Inspect 就声称已经启用。

## 扩展示例与验收

`packages/evaluator/examples/simple_retail_environment.py` 实现内存库存，直接通过 `execute_native_task(..., environment=...)` 注入。demo 用固定 mockllm 输出验证库存不足后恢复，不调用真实模型或服务。新增领域无须修改核心路由；CLI 自动选域和正式领域评分属于另一层接入。

运行：在 Evaluator 环境执行 `python examples/simple_retail_environment.py --output artifacts/retail-demo`。

当前 Harness observation 的历史字段 `before_files/final_files` 仍承载快照；本次保留格式，示例不宣称已建立通用领域报告或正式成绩。

至少覆盖：公开导入无 Agent 依赖、旧接口兼容、合法/越界路径、symlink、CRLF、大小边界、worker 无 site-packages 执行、工具错误恢复、生命周期失败、取消/限制传播、源码身份变化、Inspect 本地清理。安装验收使用独立环境，不以 Docker bundle 测试冒充真实 Docker 运行。
