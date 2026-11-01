# 显式配置与身份绑定

当前 nanobot 基准的配置示例位于 [`benchmark/`](benchmark/)：文件与模型决策运行使用 `nanobot.example.json`，事后 GEval 使用 `judge.example.json`，独立 τ 领域试点使用 `tau.example.json`。复制为本地配置后填写源码、解释器和服务信息；密钥由 `api_key_env` 等字段指定的环境变量读取，不写入配置或 Git。具体命令见[分层评测指南](../docs/benchmark/v2-usage.md)与 [τ 适配说明](../docs/benchmark/tau.md)。

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
