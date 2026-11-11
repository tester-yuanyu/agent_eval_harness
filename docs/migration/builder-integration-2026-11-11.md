# Builder 产物发布就绪与来源审计

本次按 P0 → P1 实施。P2（预算选例、参数分区与 pairwise）未实施。

## P0：接入现有 generate-full 交付

在仓库根目录运行（工作目录必须不存在）：

```bash
.venvs/evaluator/bin/python -m agent_eval_suite.cli readiness run \
  --delivery packages/dataset-builder/tests/fixtures/full_tools_fixture_v1_full_eval_20261020 \
  --workspace tmp/full-readiness
```

根入口通过两个独立解释器调度 Builder 与 Evaluator，`--builder-python`、`--evaluator-python` 可指定安装位置。`--mini-agent-root` 默认为仓库 `examples/mini_agent`，是显式可信 reference 实现路径；只在选择 `--delivery` 的 MiniAgent runner 时加载可选 MiniAgent 依赖。已有 `--dataset` 的 read_file 切片继续兼容。

工作目录产生 `dataset.json`（完整行为集合及来源绑定）、`evidence.json`、Inspect `logs/` 和 `report.json`。这些新增文件位于原始交付之外，不改历史产物。原始 manifest、所有文件 Hash、案例集合、运行器源码/依赖与断言版本均参与绑定。复验命令会重新读取源交付、获取当前运行身份，再计算报告：

```bash
.venvs/evaluator/bin/python -m agent_eval_suite.cli readiness check \
  --delivery packages/dataset-builder/tests/fixtures/full_tools_fixture_v1_full_eval_20261020 \
  --workspace tmp/full-readiness
```

当前首个执行适配支持 `query_user_info` 的 `invoke_tool`，且必须具备明确的 `fixture_setup.records`。用实际 MiniAgent `FixtureEnvironment` 和 ToolRegistry 执行，经原生 Inspect Harness 记录；fixture 只从 records 初始化，动作只从 arguments 读取，Oracle 与 result_branch 不进入任务、消息或 reference actor。只使用进程内 mockllm 记录确定性动作，无真实模型调用。该检查验证 reference 可执行性，不是 Agent 正式评分。

MiniAgent schema 的 `title` 为注释，可在适配时移除；整数 `exclusiveMinimum: n` 等价转换为 `minimum: n+1`，以满足 Inspect 的字段支持。其余约束保留，不改变通用 Harness 的严格检查。

基线交付的完整分母保持 **365 条行为案例**，其中 **2 条 reference 通过、363 条未绑定**；另有 **202 条静态契约检查、280 条阻塞义务**。两项比率均为 2/365≈0.55%，整包 `ready_for_review=false`、`release_ready=false`，CLI 返回 1 是预期门槛结果。缺少 fixture 的第三条 query_user_info 行为案例仍未绑定。不能把局部通过当作整个交付可发布。

`freeze` 还要求所有行为通过、无阻塞义务及绑定当前数据/证据 Hash 和完整案例集合的人工 review。输出为外层不可变封装，内部原交付字节原样复制，最后写入外层 FROZEN manifest。当前基线无法通过该门槛；本次未替用户审批或冻结正式数据。

当前范围是 generate-full 交付及这个工具切片；nanobot 与其他行为协议仍需各自执行适配。源码 Hash 是本地复验绑定，不是远端签名认证。

## P1：逐事实来源与差异审计

full_tool_fixture collector 按 agent、intent、tool、module、evidence 分别绑定声明及相关实现文件；模块另有明确映射。来源表示可追溯的声明/实现依据，不代表行为已验证。新增模块没有映射会报错，不再静默广播全部文件。

通用 ingestion export 新增 bundle 外 `source_audit.json`；Builder 使用的原 `examples.full_tool_fixture.export` 入口也新增 `collected_facts.json` 和 `source_audit.json`，均由外层 manifest 绑定 Hash。后者保留原业务 `capability_contract_gaps.json`，可直接交给 generate-full。v3 `agent.json`、FactDocument v1、原 reconcile 判定及硬错误行为均保持，旧 delivery 无新文件仍兼容。

两种导出的 gap 语义不同：通用 `gaps.json` 是采集声明差异，不能冒充 Builder 要求的业务 gap 报告。给 Builder 制作新 MiniAgent 交付应在 `examples/mini_agent` 目录运行：

```bash
../../.venvs/evaluator/bin/python -m examples.full_tool_fixture.export --output <新交付目录>
```

随后使用原有 `generate-full --bundle <交付>/bundle --delivery-root <交付> --expected-bundle-hash <Hash> --workspace <新目录>`，再将生成目录交给 `readiness --delivery`。

冲突输入可在导出前独立审计，避免 reconcile 报错后看不到差异：

```bash
.venvs/builder/bin/python -m capability_snapshot_kit.ingestion.cli audit \
  --runtime runtime-facts.json --candidate candidate-facts.json \
  --source-root examples/mini_agent --output audit.json
```

输入是现有 FactDocument JSON；CLI 校验来源 Hash，输出不可覆盖。`runtime_only` 表示 candidate 未声明该事实，`candidate_only` 表示 runtime 未提供该事实，`conflicts` 表示同 ID 内容不同，`missing_sources` 表示缺少事实来源绑定。未提供某一输入时，不把另一侧全部误报为缺失。`collection_completeness=unknown` 明确表示没有采集全量清单，不能判断是否漏采；所有报告 `execution_verified=false`。

P1 本次范围是来源与可见差异。未新增 RawFactDocument 替换、插件 subprocess connect 或第二个能力 resolver；未来需要跨 Agent 采集时再扩展新证据协议。

## 验证

- Builder 包回归：378 passed / 5 skipped（可选 DeepEval 生成依赖未安装）。
- Evaluator 包回归：1529 passed / 9 skipped；164 条已有依赖警告。跳过项为显式付费 API、Docker 或可选 Nanobot 路径。
- MiniAgent 包回归：326 passed / 1 skipped（真实模型 smoke 未启用）。
- contracts：23 passed；根入口 integration：61 passed。
- 未安装 MiniAgent 的 core 环境：导入正常，4 passed / 1 optional skipped。
- 独立代码审查及 Ruff、git diff --check 通过。
- 新 Git 克隆叠加本次工作树代码，分别全新安装 builder/evaluator，两个环境 pip check 均通过。历史交付和新采集→生成→readiness 均验证 2/365、整包不可发布；来源审计成功，bundle Hash 保持 `215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c`。
- 验收发现并修复 ingestion CLI 缺少 `python -m` 入口；subprocess 回归防止静默无操作。另确认通用采集 gaps 与业务 gaps 的区别，将来源记录接入既有 full_tool_fixture exporter。
- 已验证错误 Oracle 不进入消息/日志、缺失或过期证据拒绝、完整分母不缩减、局部通过不能冻结，以及 P1 导出 bundle 逐文件字节不变。

日志与离线产物保存在 `tmp/builder-integration/`，包回归日志在 `artifacts/verification/`。测试不调用真实模型 API 或托管服务；未审批/冻结正式数据集，未提交代码。
