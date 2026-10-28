# DeepEval 语义 Judge 接入与迁移

> 历史记录：2026-10-20 已迁移至 Inspect Model Grading，本文的生产路径、依赖和命令已删除，不作为当前安装说明。见 [当前职责与接入](langfuse.md)。

2026-10-15：当前语义评分实现切换为 DeepEval 4.2.9 的 G-Eval。DeepSeek 仍是模型服务，DeepEval 负责指标提示和维度评分，Evaluator 的业务扩展负责契约、执行、取证、权重、阈值、质量结论与发布门禁；默认调度由 [Inspect 主框架](inspect_engine.md) 承担；DeepEval 为可选依赖，通过调用作用域隔离本地设置。

## 替换范围

```text
脱敏后的 JudgeRequest
  → 每个声明维度创建一个 GEval（固定 evaluation_steps）
  → DeepSeekEvaluationModel 调用独立的 Judge 模型
  → DeepEval 得到 0–1 分数和理由
  → DeepEvalJudgeClient 转成现有 0–100 维度结果
  → judge.py 校验维度、应用权重和阈值、生成 JudgeResult
```

旧的手写维度评分提示和客户端解析实现已移除。`DeepSeekJudgeClient` 是 `DeepEvalJudgeClient` 的导入别名，不保留第二套评分后端。历史 JSON 结果继续读取，结果协议不因本次替换改变。

工具断言、状态核验、Trace 与判定策略已接入主引擎的自定义 Metric；Provider、稳定性及 Gate 保留为业务扩展。DeepEval 运行期 Dataset 和测试运行器已经启用，托管平台未启用。Suite 的 Judge Profile 迁移仍未完成，现阶段继续使用兼容 CLI 或显式注入客户端的 Python API。

## 安装与配置

在已具备本地 agent-trace-sdk 和 minimal-agent 依赖的项目环境中更新安装：

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

项目固定 `deepeval==4.2.9`，避免指标提示或计算算法随无约束升级改变。Judge 使用原有独立环境变量：

```bash
export DEEPSEEK_JUDGE_API_KEY=...
export DEEPSEEK_JUDGE_MODEL=deepseek-flash
export DEEPSEEK_JUDGE_BASE_URL=https://api.deepseek.com
```

不会回退到 Agent 的 DEEPSEEK_* 或 OPENAI_* 凭据，也无需 Confident AI 账号。模型传输沿用已有的 OpenAI SDK Responses API 路径，SDK 自动重试关闭，重试由 Evaluator 管理。

兼容 CLI 的调用模板如下，DATASET 必须替换为与当前 Agent 匹配且明确声明 Judge 维度的冻结数据集：

```bash
.venv/bin/python -m eval_framework.cli run \
  --provider mini_agent --dataset DATASET.jsonl --output-dir artifacts \
  --judge-config src/eval_framework/judge_rubrics/semantic_response_v1.json
```

仅配置 Rubric 不会给所有 Case 自动增加评分；Case 的 oracle.judge 仍需声明 rubric_id、rubric_version、dimensions、reference_facts 和 required。文件形式的 Suite 目前拒绝启用 Judge Profile；不要把上述参数与 `--suite` 混用。

Python 接入时创建 `DeepEvalJudgeClient.from_env(timeout_seconds=...)`，传给 `run_provider_evaluation(..., judge_client=client)` 或当前编译执行桥的 `legacy_judge_client` 参数，同时配置 `RunConfig.judge`。客户端和 JudgeRunConfig 的 timeout_seconds 应保持一致，客户端负责实际传输预算，运行配置负责重试和记录。

## 判定与错误语义

- 输入映射：user_input → input，final_response → actual_output，reference_facts → expected_output，工具结果摘要 → context。评分前沿用现有脱敏处理。
- 每个维度使用 Rubric 中的 instruction 和固定边界说明构建 evaluation_steps，避免每次动态生成新的评价步骤；温度为 0，但不承诺真实模型评分完全确定。
- 自定义模型采用结构化分数路径，不使用 token log-probability 加权。G-Eval 原始 0–10 分经 DeepEval 归一化后转换为项目的 0–100 分。
- 正常情况下，每个声明维度调用一次评分模型；相比旧后端一次返回所有维度，调用次数可能增加。实际延迟与费用需要结合维度数量评估。
- timeout_seconds 是一次 Judge 尝试内所有维度共享的传输预算。每次请求使用剩余时间，返回后再次检查；同步调用依赖 SDK 超时，不宣称硬实时取消。
- 网络错误、限流及暂时性服务错误可以按 max_retries 重试；鉴权等永久错误不重试。输出结构、分数范围或理由不合法属于 MODEL_OUTPUT_ERROR，不作为低分处理。
- 缺少可评价的最终回复时不调用模型，按输出错误处理；required Judge 因此无法判定，而不是给空回复生成一个成功分数。纯模块输出不会自动变成自然语言回复。
- 重试重新评价整组维度，不沿用部分维度结果。token_usage 与原协议一致，记录最终成功尝试的调用用量，不是所有失败尝试的账单总计。
- 确定性 FAIL 和关键项失败仍不能被 Judge 高分抵消；required Judge 超时或错误保持 INCONCLUSIVE。证据无效与 Gate 规则继续由原框架处理。

## 可追溯性与旧基线

run 级 judge_metadata 在原 Rubric Hash、模型和运行设置之外，新增 backend、backend_version、adapter_version、metric、temperature、score_mode 及 endpoint_sha256。端点只保存哈希，凭据不写入结果。

现有比较器严格比较整个 Judge 元数据，因此旧手写 Judge 与 DeepEval、不同 DeepEval 版本或不同适配语义版本的结果会产生 JUDGE_FINGERPRINT_MISMATCH。即使 Rubric 文件相同，也必须用新后端重新运行基线和候选；不要重写历史元数据以绕过检查。适配层的输入映射、固定步骤或分数转换改变时，应升级 ADAPTER_VERSION。

## 本地运行与验证

客户端延迟导入 DeepEval，关闭其遥测、自动 dotenv 加载及文件写入，并直接调用 metric.measure，不调用平台上传或全局评测运行器。只读模式提示写入 stderr，CLI stdout 保留 JSON。初始化会设置进程级 DeepEval 环境与 Settings；同一进程的其他 DeepEval 用户也会受到遥测关闭和只读设置影响。

pytest 配置关闭随依赖安装的 deepeval 和 rerunfailures 插件，避免自动接管测试或开启重试服务器。离线验收使用真实 G-Eval 和脚本化模型传输：

```bash
.venv/bin/python -m pytest -q \
  tests/test_deepeval_judge.py tests/test_deepseek_judge.py \
  tests/test_judge.py tests/test_comparison.py tests/test_phase2_end_to_end.py
```

测试覆盖分数边界、上下文、非法输出、临时与永久错误、超时预算、Trial 隔离、权重与关键失败、保存重载、后端指纹及无额外网络/文件写入。付费模型冒烟仍通过 RUN_DEEPSEEK_JUDGE_SMOKE=1 显式启用；默认不执行。离线测试验证集成正确性，不证明新旧真实评分一致或新 Judge 更准确，正式采用阈值前仍需人工校准正确、错误和模糊样本。

## 接口依据

- [DeepEval G-Eval：固定评价步骤与独立 measure 调用](https://deepeval.com/docs/metrics-llm-evals)
- [DeepEval 自定义模型：DeepEvalBaseLLM 与结构化 Schema 接口](https://deepeval.com/guides/guides-using-custom-llms)
- [项目适配器](../src/eval_framework/judges/deepeval.py)、[模型传输](../src/eval_framework/judges/_deepeval_model.py)、[离线测试](../tests/test_deepeval_judge.py)
