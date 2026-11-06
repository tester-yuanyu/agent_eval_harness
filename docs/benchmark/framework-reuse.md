# 框架复用与当前职责

2026-11-01 的改造按 P0 执行与证据、P1 评分、P2 展示完成集成。冻结任务与历史成绩保持原样；工程回归数量不计入 Benchmark 样本量。

| 能力 | 负责方 | 本仓库保留的部分 |
| --- | --- | --- |
| 调度、重复、断点恢复 | Inspect `Task`、`Epochs`、`eval_set` | 运行前的版本、Hash、任务选择与配置一致性检查；旧 JSON 兼容投影 |
| 独立工作区与进程 | Inspect `Sample.files`、sandbox、`sandbox_agent_bridge` | nanobot 启动适配与只包含运行源码的 Docker 构建配置 |
| 工具与预算 | nanobot 原生 ToolRegistry / 文件工具；Inspect 时间、Token、消息预算 | 依据任务注册允许的工具；路径转换与任务 max_steps；不另造进程超时管理器 |
| 轨迹 | Inspect `ModelEvent`、`SandboxEvent`、`InfoEvent` | 工具前后文件快照、轮次状态及事件 ID 映射；Agent 内部工具不会自动变成 Inspect `ToolEvent` |
| 正式评分 | 自定义 DeepEval `BaseMetric` | 文件精确真值、目录约束、声明的检查点等业务规则 |
| 参考工具覆盖诊断 | DeepEval `ToolCorrectnessMetric` | 映射参考工具名；`formal=false`，不参与正式 verdict |
| 语义步骤、轮次与链路评分 | DeepEval `ArgumentCorrectnessMetric`、`TaskCompletionMetric`、`StepEfficiencyMetric` 与 GEval | 保存证据到公开 tracing API 的映射、业务 rubric、缺失值与调用预算 |
| 重复调用诊断 | 默认由 DeepEval `StepEfficiencyMetric` 评价效率 | `quality-audit` 显式保留同文件状态、错误重试等精确审计，不参与默认正式 verdict |
| 实验、对比、报告 | Inspect View；Langfuse Dataset / Experiment / Trace / Score | 四层分母、严格身份配对、来源 Hash；历史独立 HTML 兼容 |
| Langfuse 交付 | 官方 Langfuse API、OpenTelemetry、HTTPX transport | 保存结果的稳定 ID、原时间与分数映射；断点回执和完整读回验收 |

工具白名单必须作用在被测 Agent 的原生 registry；仅给 Inspect 配置工具不能限制一个自行执行工具的外部 Agent。文件快照也是业务证据，原生模型日志不能替代。以上两项属于必要适配。

## 执行与隔离

文件 benchmark 的执行选择已收进 `AgentAdapter`，复用既有 `ProviderRegistry`；nanobot 是默认注册实现。现有 Provider 可通过离线 worker 桥接，源码与逐模式身份均绑定到运行。Langfuse 仅在显式安装 `langfuse` extra 后启用。接入方式与限制见 [Agent 适配说明](agent-adapters.md)。

使用 [nanobot 配置示例](../../configs/benchmark/nanobot.example.json)。`sandbox` 可选 `docker` 或 `local`；省略时，真实 Agent / 模型决策使用 Docker，程序模块和离线 demo 使用 local。local 是本机进程与临时目录，不提供操作系统隔离。当前固定版本的跨进程 bridge 要求 Linux，因此 macOS 的模型执行使用 Docker。

Docker 模式把 Agent 源码和 worker 放入独立镜像，Evaluator 仍在自己的环境中；不复制 `.git`、`.venv`、本机凭据或整个项目目录。`docker_base_image` 可固定为镜像 digest。首次构建需要下载基础镜像与依赖。local 模式使用配置中的 `python`；Docker 模式使用镜像内 Python。模型凭据由 Inspect 读取，Agent worker 只收到本地代理 token。

运行目录的 `sandbox-environment.json` 绑定实际 image ID 与 Python/依赖环境指纹；恢复前和 worker 开始前检查。镜像丢失、重建或环境漂移时拒绝继续旧运行，保留原生日志且不输出伪完成结果。可变基础镜像与范围依赖仍不能承诺跨主机逐字复现，需另行固定镜像 digest。

`timeout_seconds`、`token_limit`、`message_limit` 使用 Inspect 原生限额。`max_steps` 仍约束 Agent 自身循环；`max_tokens` 是单次生成上限。`inspect_model` 可显式指定 Inspect Provider 标识；未设置时沿用 `model`，普通名称加 `openai/` 前缀。`extra_body` 经 bridge 转发。预算终止保留中断状态及已有证据，不自动算作成功。

每次 repeat 对应一个 Inspect epoch，有独立 fixture 工作区。恢复须通过业务身份检查，再由 `eval_set` 使用原生日志恢复；不得将修改后的配置混入旧目录。Agent 输入投影仍不包含 Oracle、参考操作、答案或评分条件。

## 评分

[Judge 示例](../../configs/benchmark/judge.example.json)列出六个 `dimensions`：

| dimension | DeepEval 实现 | 范围 |
| --- | --- | --- |
| `argument_correctness` | ArgumentCorrectnessMetric | 每轮工具参数的语义诊断 |
| `task_completion` | TaskCompletionMetric | 整个任务的完成度诊断 |
| `step_efficiency` | StepEfficiencyMetric | 整条轨迹的步骤效率诊断 |
| `action_appropriateness` | GEval | 可观察模型动作 |
| `recovery_appropriateness` | GEval | 错误及后续恢复片段 |
| `response_groundedness` | GEval | 每轮回复与证据的一致性 |

事后评分通过 `EvaluationDataset.evals_iterator`、`observe`、`update_current_span/trace` 回放保存证据，不重新执行 Agent，不使用 DeepEval 私有 `_trace_dict`。独立 worker 禁止 Confident 自动上传、隐式 dotenv 与 telemetry。局部动作只使用当时可见信息；缺失父事件、重复事件或不一致轮次不能冒充完整轨迹。

`max_evaluations` 保留旧配置名，现在表示每个 trial、每次 Judge repeat 的真实模型请求数上限。固定 DeepEval 4.2.9 的三项原生指标每项需要两次请求；不足两次不启动该项。每轮参数指标分别计费；错误请求也占预算。worker 异常退出后无法确认调用数量时，有限预算保守耗尽，不把调用数当 0 再发 GEval；用量保留未知总数和已知小计。新身份为评分 `file-tools-deepeval-v2.3`、Judge `trajectory-judge-v2`、原生指标 `trajectory-native-v1`，不可与旧分数直接做严格 A/B。

新语义分数均保持 `formal=false`，未通过独立人工校准；不用默认阈值覆盖确定性 verdict。任务真值、文件字节和约束继续作为自定义 DeepEval 规则。这次代码改造不等于新增真实模型评测或完成人工标注。

## 原生报告与对比

```bash
# 读取已有原生日志并打包 Inspect View；不执行、不重评分、不上传。
.venvs/evaluator/bin/python -m agent_eval_suite benchmark report \
  --run artifacts/my-run

# 原生日志的动态本地查看器。
.venvs/evaluator/bin/inspect view --log-dir artifacts/my-run/inspect

# 严格配对比较，并将两组日志放入同一个原生查看器。
.venvs/evaluator/bin/python -m agent_eval_suite benchmark compare \
  --baseline artifacts/baseline --candidate artifacts/candidate \
  --output artifacts/comparison.json --view-dir artifacts/comparison-view
```

`report --format auto` 有日志时生成 `inspect-view/index.html`、来源清单与 `report.md`；静态查看器需通过本地 HTTP 服务打开。日志身份须匹配保存运行，v3/v4 还核对 sample、score 和每条内嵌结果；被最终结果替代的旧尝试保留来源 Hash 并从默认查看器排除。有日志时也可显式选择 `--format domain` 生成历史 `report.html`。只有 `results.json` 的历史、复评或事后 Judge 目录继续使用 domain 报告；不伪造其原生执行日志。`--format inspect` 在缺少日志时明确报错。

Inspect 提供日志浏览、评分展示与多运行查看。`comparison.json` 仍保留同任务、同 repeat 配对及计划分母；重复或越界 trial、损坏身份、任务不完整、评分/Inspect 版本等控制项不一致时拒绝比较。模型和兼容的运行身份可作为实验变量，差异会记录。这里的差值是描述性比较，不声称统计显著性。

Langfuse 本身支持查询和导出。本仓库的 `export-langfuse` 是把本地保存结果送入 Langfuse 的兼容命令名，并非替代 Langfuse 数据导出功能。实验关联复用官方 OTel 属性，不再次运行 Agent。稳定 ID、证据原字节绑定和完整回读是本项目可复现要求；不能仅以 API 接收成功代替验证。

新建的无损元数据补证使用 `langfuse-exact-metadata-v2`：目标 ID 和来源 Hash 带类型前缀，避免看起来像数字的十六进制字符串被 API 解析为数字。已有 v1 回执继续按原格式重建和校验；原始轨迹、分数和保存结果不改写。

上游参考：[Inspect Agent Bridge](https://inspect.aisi.org.uk/agent-bridge.html)、[Inspect View](https://inspect.aisi.org.uk/log-viewer.html)、[DeepEval Step Efficiency](https://deepeval.com/docs/metrics-step-efficiency)、[Langfuse OTel 实验](https://langfuse.com/docs/evaluation/experiments/experiments-via-opentelemetry)。实现以锁定的 Inspect 0.3.280 / DeepEval 4.2.9 / Langfuse 5.0.2 公开 API 和离线回归为准，在线文档可能对应更新版本。
