# 评测集构建流程

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

`response.json` 应按请求中的候选结构准备。导入不是自动审核：全部校验通过后，还需人工核对审核清单。完成真实审核后，可使用自己的审核标识显式冻结：

```bash
.venvs/evaluator/bin/eval-suite dataset freeze --suite mini_agent_query_user_intent_v2 --draft artifacts/query-user/draft.jsonl --reviewer YOUR_REVIEWER_ID --review-file artifacts/query-user/review.md --output data/datasets/query-user-v1.jsonl
```

未完成审核、输入绑定变化或输出已存在，冻结会失败。不要通过直接改写生命周期字段绕过 Builder 的冻结流程。`make demo` 自带的合成自检 Suite 不代表这一人工生产流程已执行。

## 接入新能力包

先使用根 `bundle publish` 校验并登记完整能力包，再在 Builder Suite 的 `capability_input` 中绑定不可变路径及 `bundle_hash`。现有 Suite 的 `projects_root` 锚点通过兼容解析映射到本仓库；新 Suite 可用 `suite_dir` 的相对路径引用已登记包。Bundle 不直接依赖被测 Agent 的源码、Prompt 或配置文件。

目前根 CLI 保留 Builder 的真实分阶段接口，未提供会自动改写 Suite、代替人工审核或选择 `latest` 的一键生成命令。这样生成产物、审核依据和参考身份保持可追溯。

修改 Suite 后要重新准备请求，不能复用原来的审核结论。能力变化可先通过 `bundle diff --old DIR --new DIR` 检查，再决定保留回归集、追加新能力 Case，还是建立新的数据集版本。
