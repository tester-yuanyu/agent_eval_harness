# 渐进收敛实施计划（2026-11-11）

> 执行方式：使用 superpowers:executing-plans 在当前工作树逐项实施；最终独立审查。用户已提供四步方案并授权改造。

**目标：** 保留 Inspect 执行与日志、DeepEval 正式评分、独立 Trace SDK，以兼容测试约束公共实现收敛，不新增评测能力。

**架构：** contracts 提供不依赖 Inspect 的事件身份与关联校验。SDK 和 Harness 分别保留采集策略、领域证据检查；工具 Schema 校验共享，异步 Inspect 循环为主，同步 callback 保留无法等价的错误与生命周期语义。

**技术：** Python、Inspect 0.3.280、DeepEval 4.2.9、JSON Schema、pytest。

**依据：** 本次用户四步方案、根及 Evaluator AGENTS.md。

## 全局约束

- 冻结数据、能力包、历史日志与结果保持原字节；参考身份不改写，新源码记录新运行身份。
- 不调用真实模型，不上传 Langfuse；验证使用固定响应与独立环境。
- SDK 独立；mini_agent 可选；Builder 通用校验不依赖 Evaluator。
- 不把 Oracle 传给 Agent，不用 Agent 返回值补救损坏日志。
- 仅在本仓库工作，已有 output/、tmp/ 未跟踪内容不改动。

## 重点审查

1. 重复事件与相同数量但错误关联的 route 不能被字典覆盖后误认完整。
2. SDK 历史容错与原生日志全量拒绝策略不得混用。
3. 同步抛错与异步可恢复错误、预算及清理不得被适配悄悄改变。
4. 按需导入仍保持公开名称、对象身份、旧 CLI 和外部 Provider 可用。
5. 抽出的公共源码须进入运行身份；全新克隆不得借用原开发环境。

## 第一步：职责与依赖

- [x] 审计入口和静态直接/间接调用；在 `docs/migration/convergence-2026-11-11.md` 记录主线、可选、兼容模块及保留/删除依据。
- [x] 更新 `docs/architecture.md`、`docs/benchmark/layered-framework.md`、`docs/benchmark/legacy.md`，新增 SDK README；仅文档，不改变行为。

## 第二步：公共证据校验

- [x] contracts `trace.py` 增加重复身份统计、同属关联检查；SDK `validation.py` 与 Evaluator `trace_analysis.py` 复用，保持旧 issue/status 语义。
- [x] Harness `trace/timeline_extractor.py` 使用公共校验，检查原生事件及 route/turn 的唯一性和关联；转换记录关联原生来源。文件状态和轮次检查留在转换侧。
- [x] 先写 contracts、SDK、原生 timeline 损坏回归并验证失败，再实现；验证缺失、重复、错误关联、未结束、写入失败、读回及正式 verdict。
- [x] SDK 声明 contracts 依赖；核对身份闭包。

## 第三步：循环与路由

- [x] 建立同步/异步 Schema 参数兼容测试及错误/预算/清理基线。
- [x] 抽出 `harness/tool_validation.py`，让同步和异步 Router 共用环境 Schema 校验；同步环境暴露 `tool_schemas()`，旧无 Schema 调用使用文件环境声明。
- [x] 保留同步 callback 的立即终止、返回值和 teardown 语义；异步循环不改预算/错误恢复，nanobot 原生循环不动。文档列明暂不桥接原因。

## 第四步：历史依赖与验收

- [x] 为 `eval_framework.__init__` 建立懒加载回归，迁移公开 API 到按需导入，保留 `__all__` 和对象身份。
- [x] 审计当前适配器复用的旧模块，保留必要实现，不把公共转发误作重复实现；本轮不删除 SDK 必需依赖。
- [x] 定向测试 → 每包回归 → 全新克隆安装与离线主/旧 Demo、无 mini_agent 外部 Provider、Builder 隔离验证。
- [x] 相同保存证据的正式评分改前/改后比对；冻结和历史资产 Hash、Ruff 与 diff 检查，记录实际结果与局限。
- [x] 独立审查并修复重要问题，留下可复现验收记录。

## 执行记录

- 第一步已完成入口文档和 SDK 定位；检查发现旧新路径共享 Provider 生命周期与断言，不迁走有实际用途的实现。
- 第二步定向测试先出现 8 项预期失败（缺失公共函数、重复/错误关联误判完整、turn 未显式引用原生事件），修复后含 SDK/历史读取/懒加载共 79 passed。
- 第三步 Schema 参数兼容与同步生命周期共 34 passed。保留同步循环是用户允许的非等价兼容例外；异步主循环与 nanobot 原生 AgentLoop 不改动。
- 第四步懒加载测试改前 1 failed / 1 passed，改后纳入上述 79 passed。
- 测试阻塞根因为 mockllm 默认 usage 会触发 tokenizer 下载；测试响应显式固定 usage 后不再依赖下载。
- Ruling: 当前 Provider 生命周期与 DeepEval 复用的旧断言保留原位置，通过顶层懒加载缩小依赖影响；避免为移动文件破坏历史身份/导入，代价是旧实现仍存在。

- 最终独立审查：1 项 Important（route 双端错指已有 turn）。`test_route_endpoints_cannot_agree_on_wrong_existing_turn` RED→GREEN，修复后原生测试 33 passed；无遗留其他发现。
- 新克隆：独立 Core/Builder 安装、pip check、无 mini_agent/Core、无 Evaluator/Builder 隔离通过；Core 99、Contracts 22、Builder 16 项定向回归通过；主线 5 PASS、历史 Demo 三态符合预期。
- 相同保存证据：4,181 条正式 assessment 一致；6 条非正式 ToolCorrectness reason 的集合顺序有差异，分数不变。6 组旧 Suite（18 case）经公开 API 回读、结论及 Hash 均不变。
- Final: Ruling: 审查未重复执行的全包/新克隆/评分和资产验证由协调者实际执行并记录；不把独立审查当成运行验收的替代。代价是这些运行证据没有第二次人工复核，但有保存日志和可复现命令。
- 全目录 Ruff 159 项全部为 HEAD 原有问题（基线 163 项），本轮修改文件零 lint。按仓库规则不跨目录批量修格式。

- 完成：最终 Evaluator 全包 1,524 passed / 9 skipped（291.64 秒）；其余包回归 756 passed / 6 skipped，合计 2,280 passed / 15 skipped。已完成独立审查修复、新克隆验收、文档与回退边界。
- 交付：用户在实现验收后授权提交、推送并合入默认分支；仅提交本轮收敛文件。验收记录作为四步的最终结果，计划保留以供逐项核对。
