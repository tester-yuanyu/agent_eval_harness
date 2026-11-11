# 评测优化交付与使用

本轮完成批准的 P0 / P1 / P2 工程切片，复用 Inspect、DeepEval 和现有 Provider，没有重跑历史正式评测、重评有效分数或上传托管服务。新视图位于 `artifacts/mini-agent/v4-deepseek-optimized-view-20261111/report.html`。原 v4、首次正式执行及恢复交付共 5284 个文件逐一 SHA256 校验，全部保持原字节。

## 已交付

| 优先级 | 改造 | 验收边界 |
|---|---|---|
| P0 | 报告分离模型案例、确定性检查、Judge 请求/Token/评分；单独说明预期失败 | 新视图为模型 54/76、确定性 289/289；107 次 Agent、201 次 Judge 请求；13 条注入故障的期望 FAILED 不解释为恢复成功率 |
| P0 | 执行预检、配置错误停止、明确的补测入口 | 首条模型案例作为实际 canary，成功结果直接保留；错误根据顶层异常和 Inspect 原生 ModelEvent 分类，不把业务 FAIL 当连接故障 |
| P0 | 执行恢复与 Judge 补评 | 仅已知临时错误自动列入补测；按 case/trial 保存有效 PASS/FAIL；原生证据检查 Hash 后复制；Judge 绑定执行、配置、重复轮次及源码，只补失败项 |
| P1 | 评分项检查点、受限并发和有界重试 | case 并发×metric 并发≤16；支持案例未结束时跨目录复用已完成评分；独立 repeat 不共用结果；429 遵循 Retry-After，超出等待上限交给显式续跑 |
| P1 | 阶段计时与环境复用 | 保存环境准备、Inspect、规则、Judge、报告、上传/索引等待/验证时段；未单独采集的 queue 时间为未知；固定镜像 ID、缓存静态环境信息，逐 sample 可变状态隔离 |
| P1 | Langfuse 显式 local/cloud profile、独立同步状态、续传与完整实验入口 | 写入不确定先读回；缺 ID 或索引未齐不盲目重发；沿用原云端，不自动切换或启动本地服务 |
| P2 | Builder 预算选例与快照审计 | quick/full、保留全部义务分母、受约束候选 2-way、实测 top-up；采集范围/遗漏原因和逐事实来源失效审计，旧 bundle 不变 |
| P2 | Harness 依赖/身份、Inspect 原生崩溃恢复、多轮与人工校准入口 | 中立模型工厂、共享 Spec 只校验不改原配置字面值、分层身份保留旧算法；SIGKILL 后恢复证据仍标不完整；新多轮 fixture 不修改 v4；生成空白独立人工标注表 |

## 正式入口

继续使用根目录 `scripts/mini_agent_v4_benchmark.py`，由 evaluator 环境启动。`validate`、`report-view` 离线；`run/resume/retry/judge` 是显式真实评测入口，`sync/export/verify` 是显式远端交付入口。下面命令是操作说明，本次没有执行真实请求。

```shell
# 首次正式执行：实际首案例预检，开放原生实时日志便于崩溃取证
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py run \
  --output artifacts/mini-agent/new-run --log-realtime

# 同一身份的中断续跑；已保存 trial 不重新执行、不重新规则评分
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py resume \
  --output artifacts/mini-agent/new-run

# 已完成运行中仅补临时传输错误，派生新目录，原结果不改
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py retry \
  --source artifacts/mini-agent/new-run/execution \
  --output artifacts/mini-agent/new-retry

# 复用旧评分：source 是原始执行，reuse-judge 是此前的评分目录
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py judge \
  --source artifacts/mini-agent/new-run/execution \
  --reuse-judge artifacts/mini-agent/new-run/judged \
  --output artifacts/mini-agent/new-judge-recovery \
  --concurrency 4 --metric-concurrency 2 --request-retries 1

# 评分成功后只交付云端，失败可用同一命令续传
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py sync \
  --output artifacts/mini-agent/new-judge-recovery \
  --profile configs/benchmark/langfuse-cloud-profile.example.json

# 历史结果生成独立新视图和空白人工校准表，不执行、不重评、不上传
.venvs/evaluator/bin/python scripts/mini_agent_v4_benchmark.py report-view \
  --source artifacts/mini-agent/v4-deepseek-recovery-20261111/judged \
  --output artifacts/mini-agent/another-report-view
```

Python API `judge_run(..., options=...)` 默认保持旧路径；只有显式启用检查点或 `reuse_from` 才采用新恢复路径。新控制项要求显式 GEval-only dimensions，不会静默删掉旧默认 native 维度。显式关闭检查点保持旧评分行为。恢复不是独立重复实验，必须在同一原始执行、配置、模型和 rubric 下进行；控制实现变化时同目录继续会拒绝。不同代码/数据集/评分契约应作为新实验，不能借“补测”混合结果。

执行预检失败后的 `resume` 保留旧 INVALID，检查后续新 canary；不会把旧配置错误反复用于熔断新批次。修改凭据后成功继续，也不能把原失败记录改成 PASS。修订代码导致运行身份变化时仍须新实验。实际 batch 的日志目录绑定 case IDs 和缺失 epoch 集合，防止 Inspect 错误重用另一个 canary。

## 验证结果

- Evaluator 包回归：1634 passed、9 skipped。跳过项为可选 nanobot 与未授权真实模型 smoke；164 条警告主要为已有 Inspect/tenacity 弃用提示。
- Builder 包回归：385 passed、5 skipped；Contracts：41 passed；根集成：61 passed。
- 审查补修另运行评分、恢复与 runner 定向测试；最终 61 passed，见 `tmp/eval-optimization-20261111/review-fix-tests.log`。独立审查发现的部分检查点复用、默认维度、错误分类、扩展源码身份和 canary 日志误复用问题均已复现并修复。
- 实际 v4 离线复用验收：在禁止 HTTP 的测试中，365 条原执行、196 项有效评分保持一致，0 次新增 Agent 执行、0 次 Judge 请求。日志 `v4-reuse-audit.log`；派生审计结果仅在 tmp。
- 干净 Git 克隆叠加本次工作树后，分别安装 core / builder 环境且 `pip check` 通过；core 不装 mini_agent，离线外部 Provider demo 输出 PASS / FAIL / INCONCLUSIVE 三种预期结果。
- 本轮涉及文件通过各包 Ruff；全 Evaluator Ruff 仍有本轮未改文件的 158 项既有格式告警，未批量修改无关代码。
- 新报告的完整实验 URL、365 条记录映射、统计分母和人工表均离线核验；原云端历史交付状态沿用已验证回执，本次未重新联系云端。

## 不扩大结论

本轮没有测真实模型端到端加速比例，也没有验证 Docker 实机性能。Builder 2-way 范围是现有候选元数据因素，不是新生成的任意参数笛卡尔积；未提供执行观测时实测覆盖为 0。人工校准仍需真实独立人工标签，不能用模型填空后宣称已校准。新多轮 fixture 验证执行器和证据绑定，不代表真实模型能力已有改善。所有可复用历史结果均保留，后续真实评测应另建实验。

子系统详情：[Builder/快照](eval-optimization-builder-snapshot-2026-11-11.md)、[Runtime/Harness](eval-optimization-runtime-2026-11-11.md)、[Langfuse](eval-optimization-langfuse-2026-11-11.md)。
