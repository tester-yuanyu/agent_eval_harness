# 显式配置与身份绑定

当前 nanobot 基准的配置示例位于 [`benchmark/`](benchmark/)：文件与模型决策运行使用 `nanobot.example.json`，事后 GEval 使用 `judge.example.json`，独立 τ 领域试点使用 `tau.example.json`。复制为本地配置后填写源码、解释器和服务信息；密钥由 `api_key_env` 等字段指定的环境变量读取，不写入配置或 Git。具体命令见[分层评测指南](../docs/benchmark/v2-usage.md)与 [τ 适配说明](../docs/benchmark/tau.md)。

## 五份 Spec 与 RunRequest

`benchmark run` 和 `benchmark demo` 的原有 `--config` 参数同时接受旧平铺 JSON 和新的 [`RunRequest`](benchmark/layered/run.json)。新配置包含 `schema_version: "1.0"` 和五个必填部分；每部分可以内嵌 JSON 对象，也可以填写独立 JSON 文件的相对路径。

| 部分 | 职责与字段 |
| --- | --- |
| `model` | `model`、`inspect_model`、`base_url`、`api_key_env`、`temperature`、`max_tokens`、`extra_body` |
| `harness` | `max_steps`、`timeout_seconds`、`module_timeout_seconds`、`token_limit`、`message_limit`、`variant`、`instructions` |
| `environment` | `provider`、`nanobot_root`、`python`、`sandbox`、`docker_base_image`、`tokenizer_mode`、`tokenizer_cache_dir`；已有 mini_agent 适配器另可使用 `repository_root`、`capability_bundle` |
| `benchmark` | `dataset`、`level`、`split`、`limit` |
| `execution` | `repeats`、`concurrency` |

Python API 从 `eval_framework.orchestration` 导入 `ModelSpec`、`HarnessSpec`、`EnvironmentSpec`、`BenchmarkSpec`、`ExecutionSpec`、`RunRequest` 与 `load_run_request`。`runtime_config()` 只向现有 runner 投影显式配置的运行字段；任务筛选、重复次数与并发由 CLI 分别传入。默认值不会额外写入旧 config，从而保留原有配置身份语义。这里的 `ExecutionSpec` 是运行调度配置，与 Provider 的执行输入契约分属不同命名空间。

优先级为**显式 CLI flag > 对应 Spec 字段 > 历史 CLI 默认值**。即使 flag 值等于默认值，也会覆盖 Spec。可覆盖项为 `--dataset`、`--level`、`--split`、`--limit`、`--repeats`、`--concurrency`；`--output` 仍必须显式传入。配置内 `repeats` 为 1–5、`concurrency` 为 1–12，筛选上限必须为正整数。`demo` 保持离线参考烟测语义，`run` 保持原有实际执行语义。

独立 Spec 的引用相对于 `run.json` 所在目录；Spec 内本地路径相对于该 Spec 文件，内嵌部分的路径相对于 `run.json`。省略 dataset 时仍使用历史默认的当前工作目录相对路径。旧平铺配置中的相对路径继续相对于调用命令的当前工作目录；迁移时会将这些已有目标写成绝对路径，避免移动配置后改变含义。解释器路径保留符号链接，不会将虚拟环境的 Python 解析成系统 Python。

所有层级拒绝重复 JSON 键、未知字段、错误类型和跨部分错放字段。`extra_body` 是保留的模型供应商 JSON 扩展区，其内容原样传入，仍接受递归密钥检查；原始 `api_key`、`Authorization`、`password`、`token` 等字段（包括嵌套对象、列表及 URL 凭据）被拒绝，`*_env` 只能包含合法环境变量名。当前实际凭据入口是 `model.api_key_env`；不要向 `extra_body` 填入认证信息。配置不能引用远程 URL，也不能执行代码。

从仓库根目录执行离线示例：

```bash
.venvs/evaluator/bin/python -m eval_framework.benchmark.cli demo \
  --config configs/benchmark/layered/run.json --output /tmp/layered-demo
```

显式迁移旧 nanobot 平铺配置，不读取环境变量值、不运行 Agent、不调用模型，也不修改原配置；输出目录必须不存在：

```bash
.venvs/evaluator/bin/python scripts/migrate_benchmark_config.py \
  --input configs/benchmark/nanobot.example.json --output /tmp/nanobot-layered
```

迁移输出五份 Spec 和 `run.json`；源配置的全部已知选项保留，不认识的键会报错。迁移时请保持与旧命令相同的工作目录。`core-run`、`coverage`、`judge` 与独立 τ 命令仍使用各自旧格式，不适用本次 RunRequest 组合；前面三个入口会明确拒绝误传组合格式。

以下内容适用于保留的 `eval`、`bundle` 和 `agent` 兼容入口。

## 外部 Agent 绑定

根 CLI 不从数据集中解释可执行命令。[`agents/external-static.json`](agents/external-static.json) 是可信 Evaluator `RuntimeBinding`，使用已有静态外部适配器。它接受以下候选输入：

```bash
eval-suite eval validate --input CANDIDATE_DIR --binding configs/agents/external-static.json
eval-suite eval run --input CANDIDATE_DIR --binding configs/agents/external-static.json --output-dir RUN_DIR
```

候选必须使用匹配的 `mini_agent` 身份和适配器支持的静态操作。该绑定不运行参考 Agent，也不调用模型。

外部 stdio Agent 使用可信 JSON 绑定，沿用 Evaluator 的已有字段：`version: "1.0"`、`agent_id`、`adapter: "stdio"`、`argv`，以及可选的绝对路径 `python`、`agent_root` 和只保存变量名的 `env_names`。设置 `python` 时，`argv[0]` 必须是执行脚本的绝对路径。绑定由用户显式配置，不得从期望答案推导可执行命令。

`--binding` 只用于候选导入模式 `--input`，不适用于旧 `--dataset` 模式；可通过 `eval-suite eval run --help` 查看受支持的输入。这里不提供新的 HTTP 或远程传输协议。

## 固定外部源码

```bash
eval-suite agent sync --name NAME --repository REPOSITORY --ref REF
eval-suite agent resolve --name NAME --commit FULL_COMMIT
```

只有显式 `sync` 会获取源码，并返回完整 commit、tree 和 detached checkout 路径。`resolve` 不访问网络：它直接将已跟踪文件字节、文件类型、符号链接目标和可执行权限与固定 commit tree 比对，不依赖 Git 索引标记或缓存元数据，同时拒绝已暂存或未跟踪的变更。源码检查禁用 Git replacement objects。

子模块不会自动获取；已填充的子模块需要另外固定和验证源码。Git 过滤器或换行转换后的文件也必须符合记录的 blob 字节。源码绑定须显式指向解析后的路径；运行评测不会拉取代码。来源索引只记录 Git 溯源，不覆盖忽略文件、依赖环境或远端端点的实际部署版本。

## 不可变能力包登记

登记索引为 [`data/bundle-index.json`](../data/bundle-index.json)，位于各 v3 bundle 之外。`bundle list` 只发现发布项；正式使用前必须通过 `resolve` 校验固定版本：

```bash
eval-suite bundle publish --input BUNDLE_DIR --agent mini_agent --version 0.1.0
eval-suite bundle list
eval-suite bundle resolve --agent mini_agent --version 0.1.0
eval-suite bundle validate --input data/bundles/mini_agent/0.1.0
eval-suite bundle diff --old OLD_BUNDLE_DIR --new NEW_BUNDLE_DIR
```

发布版本必须以数字开头，不支持 `latest`、`current` 或隐式最新版本。已发布版本即使内容相同也不能覆盖。发布前拒绝符号链接和路径穿越，执行规范校验并核对 Agent 身份；登记使用独占写锁和原子替换。若进程在目录落盘后、索引更新前中断，可能留下未登记目录，后续发布不会静默覆盖。

`resolve` 核对规定路径、文件字节摘要、两个协议 Hash 和 Agent 身份，再运行规范校验。索引的 `files_sha256` 补充检查文件树，不替代历史协议 Hash。发布版本与 Agent 内部声明的 `agent_version` 分开记录；v3 bundle 内不增加 JSON 清单。

## 比较时固定什么

参考数据集、参考能力契约和控制配置必须保持一致；当前运行能力可以在已有兼容规则允许的范围内变化。旧模式的 `--capability-bundle` 提供参考能力包，仍须匹配冻结数据集的 Hash；运行身份由已安装 Provider 或可信绑定选择。

```bash
eval-suite eval compare --baseline-run BASELINE_RUN_DIR --candidate CANDIDATE_RUN_DIR --output-dir COMPARISON_DIR
```

`--baseline-run` 只是在根 `compare` 命令中将参数转为 Evaluator 的 `--baseline`，不是 `run` 选项，也不会自动查找基线。比较使用保存的运行目录，不使用 Agent 版本号替代运行身份。
