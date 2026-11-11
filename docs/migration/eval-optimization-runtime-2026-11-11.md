# Environment / Harness 优化验收（2026-11-11）

本批只增加离线实现与新测试 fixture；没有调用付费模型、上传托管服务、构建 Docker 镜像或重跑历史正式结果。v4 冻结任务、历史 76 个单轮 Agent 结果和原评分文件均未改写。全包与全新克隆验收由协调者统一执行。

## 镜像身份与静态探测

复用 `inspect_docker.bind_docker_environment` 原有 `sandbox-environment.json` 字段及环境 Hash 算法。首次实际绑定后、以及恢复已有构建时，Compose 的 image 改为已验证的实际 `sha256` ID，移除 build 指令；仍核对原 tag 是否漂移，漂移/缺失拒绝继续。旧 binding 文件保持原字节，源码更改产生新运行身份，不回写历史身份。

`RuntimeEnvironmentCache` 仅保存包版本/Python 版本等静态探测结果，按 Compose 路径与已绑定 image ID 分区，并发首次探测使用锁合并。每次取用先验证绑定，返回深拷贝；不缓存 sandbox、数据库、工具输出、用户对话或模型响应。Full adapter 使用这个缓存，Inspect 的每 sample 隔离生命周期保持不变。构建层缓存仍由 Docker/Inspect 负责，未引入常驻共享容器。

离线验证包括 tag/依赖漂移拒绝、Compose 固定实际 ID、同镜像两次读取只探测一次、调用者修改返回值不污染后续样本、镜像 ID 改变使缓存失效；现有真实 SQLite 多轮测试验证不同 trial 数据库隔离。未做 Docker 实机性能实验，因此不声明容器启动提速比例。

## 中立边界与配置

- `eval_framework.runtime_model.inspect_model` 是中立模型工厂；`benchmark.inspect_runtime.inspect_model` 保留兼容导入。Harness 不再从 benchmark 导入模型工厂或源码身份函数。
- 复用已有 `source_identity.py`，迁移 `layer_source_paths()` 的原路径集合/排序逻辑；旧 `benchmark.layer_sources` 入口保留。新 `runtime_layer_identity()` 返回 `execution-layers-v1`，独立列出 harness/environment/model/contracts 的文件 SHA256，不包含 benchmark scorer/dataset 源码；RawModel runtime 在原 `sources` 之外追加 `execution_layers`，历史身份算法和保存值不重写。
- `validate_runtime_config(config, strict=False)` 复用 Model/Harness/Environment Spec，仅校验共享已知字段，保留显式缺省、数字原始字面值（如 `30` 不变成 `30.0`）及外部 Provider 扩展。`strict=True` 拒绝未知字段并限制内建 provider；`RuntimeControlSpec` 明确 `log_realtime`、`preflight`、`max_model_requests`。验证过程先拒绝原始凭据，错误不会回显 secret。

```python
from eval_framework.orchestration.specs import validate_runtime_config
config = validate_runtime_config({"model": "mockllm/model", "max_steps": 4})
# legacy 扩展不丢失；新严格入口可传 strict=True
```

## 原生实时日志与强制终止实验

新增接口复用 Inspect 原生 `recover_eval_log`，不自行解析其缓冲数据库：

```shell
.venvs/evaluator/bin/python -m eval_framework.inspect_recovery \
  /absolute/path/crashed.eval --output /absolute/path/new-recovered.eval
```

Python API 为 `recover_interrupted_log(log, *, output=None) -> dict`。返回源/恢复日志路径与 SHA256、Inspect 原生状态、sample 原生事件及原生错误。默认保留原日志和恢复缓冲（`cleanup=False`），禁止覆盖原路径/已有输出。所有投影样本与顶层都标记 `status=error`、`evidence_complete=False`，没有 PASS 或正式评分。恢复日志不意味着 Agent 已续跑；后续重新执行/评分需要经过正常执行与完整性边界。

本机 Inspect `0.3.280` 实验：独立 Python 进程只配置 `mockllm/model`，单个 solver 写入 `InfoEvent` 后阻塞；开启 `log_realtime=True`、`log_buffer=1`，由父进程 SIGKILL。原日志字节在恢复前后相同，恢复得到 **1 个中断 sample、6 个原生事件**，包含 `offline_marker=before-kill`，原生错误为 `CancelledError()`，原生日志状态为 `error`。测试同时断言恢复接口不能产生完整/PASS 证据。材料保存在 `tmp/eval-optimization-20261111/runtime-crash-experiment/`，可通过对应 pytest 重现；未发起任何模型请求。

## 新多轮 fixture 与正式/参考执行边界

新测试资产为 `packages/evaluator/tests/fixtures/runtime_multiturn_v1/scenarios.json`，版本 `runtime-multiturn-offline-v1`。它是独立离线测试 fixture，不是冻结 v4 的替换或正式能力覆盖结论。

通过公开 `execution.user_responses` 传入后续输入，`full_worker` 将其转交 `AgentReferenceExecutor`；继续复用 `MiniAgentProvider` / `MiniAgentAdapter.run_full` 的真实多轮逻辑。评测环境提供每轮独立 fixture 快照，不修改 MiniAgent。Full adapter 将 snapshot 按 turn 绑定；多轮缺快照/数量不符时拒绝完整证据，不再把最终状态复制给前序 turn。单轮旧行在没有逐轮快照时仍可使用唯一末态。

三项新场景覆盖澄清后继续查询、澄清后的受控工具异常、确认阶段无写入；均由本地脚本模型注入现有 Agent，断言 2 轮真实执行及独立状态读数。它们验证执行器与证据管道，**不证明真实模型成功率或确认能力已修复**。既有 SQLite 场景继续验证真实状态变化 `[0, 0, 1]` 与跨 trial 隔离；人工校准和真实多轮能力评测仍属于另外的显式评测资产。

## RED / GREEN 与检查

- 初始新测试复现两个 turn 均被赋最终状态；新增配置、缓存、身份 API 当时缺失，5 项失败。
- 新 worker 多轮场景在实现前 3 项均只执行一轮；接通公开响应与现有逐轮采样后 3 项通过。
- 强制终止实验先因恢复 API 缺失失败，补充原生恢复包装后通过（5.33 秒）。
- 相关环境/状态/多轮回归：31 passed（11.15 秒）。
- 首轮原有 Full/Inspect 环境回归：17 passed（76.48 秒）。
- 最终新测试：9 passed（8.42 秒）；追加配置字面值兼容检查后 runtime 测试再次通过。分层/原有执行边界回归：53 passed（168.16 秒），49 条 Inspect/tenacity 的既有 `initial` 参数弃用警告。日志见 `tmp/eval-optimization-20261111/runtime-optimization-tests.txt`、`runtime-regression.txt`。
- 本批所有涉及 Python 文件通过 Ruff 检查；没有暂存或提交其他代理的改动。
