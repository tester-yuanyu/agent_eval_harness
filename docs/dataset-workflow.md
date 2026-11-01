# 评测集构建流程

## 当前固定任务数据集

当前文件与模型决策基准分别使用 `data/benchmarks/file-tools-v2/build_dataset.py` 和 `data/benchmarks/model-decisions-v1/build_dataset.py`，确定性构建任务与清单。数据集卡说明实例数、任务族、公开输入、私有预期、生成来源及审核边界：

- [File Tools v2](../data/benchmarks/file-tools-v2/README.md)：程序模块、关键链路与端到端任务。
- [Model Decisions v1](../data/benchmarks/model-decisions-v1/README.md)：独立模型决策任务。
- [中文逐条阅读页](dataset-reading.html)：并列查看原始任务与中文说明，跨版本的继承任务仍分别保留。
- [语言与冻结边界](dataset-language.md)：说明文档中文化与任务原文、协议资源、历史证据的区别。

现有生成器能重建相同冻结字节，不允许用不同内容覆盖已冻结版本。运行 `benchmark validate` 检查结构、Hash 及相应参考条件；它不调用模型，也不能替代真实模块或 Agent 执行。命令见[分层评测指南](benchmark/v2-usage.md)。当前任务为 AI 辅助编写，仍需真实人工审核，不能把静态校验写成人工验收。

## 通用 Builder 的兼容流程

以下是保留的能力快照驱动流程，不是当前固定 benchmark 的必经步骤。Builder 与 Evaluator 使用独立环境，根 CLI 负责子进程转发。

在仓库根目录运行命令。以下示例准备内置理解层 Suite，不会调用模型：

```bash
.venvs/evaluator/bin/eval-suite dataset prepare --suite mini_agent_query_user_intent_v2 --workspace artifacts/query-user
```

工作区生成 `generation_request.json` 等构建材料。候选可通过显式 `dataset generate` 在线生成，也可使用外部响应离线导入：

```bash
.venvs/evaluator/bin/eval-suite dataset ingest --request artifacts/query-user/generation_request.json --response response.json --workspace artifacts/query-user
.venvs/evaluator/bin/eval-suite dataset validate --suite mini_agent_query_user_intent_v2 --draft artifacts/query-user/draft.jsonl
.venvs/evaluator/bin/eval-suite dataset review --suite mini_agent_query_user_intent_v2 --draft artifacts/query-user/draft.jsonl --output artifacts/query-user/review.md
```

`response.json` 应按请求中的候选结构准备。导入不是自动审核：全部校验通过后，还需人工核对审核清单。完成真实审核后，可使用真实审核人的标识显式冻结：

```bash
.venvs/evaluator/bin/eval-suite dataset freeze --suite mini_agent_query_user_intent_v2 --draft artifacts/query-user/draft.jsonl --reviewer YOUR_REVIEWER_ID --review-file artifacts/query-user/review.md --output data/datasets/query-user-v1.jsonl
```

未完成审核、输入绑定变化或输出已存在，冻结会失败。不要通过直接改写生命周期字段绕过 Builder 的冻结流程。`make legacy-demo` 的静态自检 Suite 与 `make demo` 的离线参考任务都不代表该人工生产流程已执行。

## 接入新能力包

先使用根 `bundle publish` 校验并登记完整能力包，再在 Builder Suite 的 `capability_input` 中绑定不可变路径及 `bundle_hash`。现有 Suite 的 `projects_root` 锚点通过兼容解析映射到本仓库；新 Suite 可用 `suite_dir` 的相对路径引用已登记包。Bundle 不直接依赖被测 Agent 的源码、Prompt 或配置文件。

目前根 CLI 保留 Builder 的真实分阶段接口，未提供会自动改写 Suite、代替人工审核或选择 `latest` 的一键生成命令。这样生成产物、审核依据和参考身份保持可追溯。

修改 Suite 后要重新准备请求，不能复用原来的审核结论。能力变化可先通过 `bundle diff --old DIR --new DIR` 检查，再决定保留回归集、追加新能力 Case，还是建立新的数据集版本。
