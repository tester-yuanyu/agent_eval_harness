# Schema 与六工具 reference 执行计划

用户确认按既定顺序执行：先 233 条 JSON Schema，再六个工具的 35 条直接行为案例。保留 365 条历史 behavior_case 分母，另报 Schema 233 与工具行为 35；不声称完成模型路由、链路或生产后端验证。

## 设计与决策

延续现有 Builder prepare → Evaluator Inspect 执行 → Builder assess。新增 v2 reference 请求，绑定每个 target 的来源 Schema；旧 v1 runner 兼容保留。共享包提供不含 Oracle 的显式执行计划及严格断言；Evaluator 可选 MiniAgent adapter 执行真实参数模型与 fixture handler。只识别明确列出的 operation 和前置条件，未知输入保持 UNBOUND；文本 fixture 要求仅支持已有两个精确模板，使用输入参数构造隔离记录。Oracle 不传入执行函数、Inspect Sample 或模型。

Schema 由 Draft 2020-12 执行，禁止外部引用；选择模式由真实 Pydantic 参数模型执行且不调用 handler。工具在每例独立 FixtureEnvironment 执行；序列共享例内状态，记录每步调用、返回值、业务状态与授权状态。unchanged 原有语义是业务数据不变，授权 token 消耗另行记录验证。Inspect 负责实际 solver 执行与日志，此路径标记 deterministic_reference_not_agent；无正式 Agent 分数、无付费模型。

## 任务与验收

1. 扩展请求/来源绑定与 Schema executor：先测试 233 绑定、否定例拒绝、远程 $ref 拒绝、Oracle 隔离，再实现并验证。
2. 六工具 recipes、真实 executor 与断言：覆盖 26 invoke、7 模式校验、1 授权、1 幂等；校验 schema 一致性、隔离、前置调用、每步状态、错误结果与断言缺失 fail closed。
3. 接入 full readiness 与分类报告；运行完整 268 条，保留 97 未绑定、287 blocked，不可发布。
4. 相关测试、包回归、fresh clone 安装演示；最终独立 review 与必要修复；新输出目录保存结果和中文验收文档。

## 进度

- 设计依据：上一轮建议及用户本轮明确授权，继续当前 codex 分支，保留所有既有未提交修改；本轮不创建提交。
- Task 1 完成：233 条 Schema 在不创建 MiniAgent fixture 的条件下实跑，包含接受和拒绝输入；外部 $ref 拒绝，未知谓词和缺失值失败。
- Task 2 完成：六工具 35 条独立执行通过；选择模式不调 handler，授权与幂等序列每步记录，观察到的初始状态与绑定输入核对。未改 mini_agent 业务实现。
- Task 3 已接入：v2 请求绑定 13 个 intent/tool Schema，Inspect 268 samples 实际执行、target 为空，篡改 Oracle 不影响执行计划或输出；v1 两条最小 runner 继续测试。
- 已观察 RED→GREEN：新协议缺失、Inspect 只执行旧2条、初始状态篡改仍通过，均已由针对性回归修复。
- 决策：Inspect solver 直接调用独立 Schema/ToolRegistry adapter，明确记录 deterministic_reference_not_agent；不经 LLM 的 native agent loop，避免把静态参数校验伪装成 Agent 对话行为。正式 Agent 评分不在本轮范围。
- Final review 修复：完整状态和状态衔接校验、setup 状态记录；三个缺证据用例 RED→GREEN。
- Final review 修复：preconditions/steps 元素类型检查，未知结构 UNBOUND；12 个参数化异常结构测试，原 3 个失败点已修复。
- 新交付验收：v3 目录 268/365 reference verified；Schema 233/233、工具 35/35，97 unbound、287 blocked，release_ready=false；新旧三个交付的 capability 56 + dataset 254 文件 Hash 均通过。
- Task 4 完成：Builder 378 passed/5 skipped，Evaluator 1556 passed/9 skipped，contracts 35 passed，root 61 passed；新增27项回归全部通过；Ruff及diff检查通过。
- 独立 review 的两项发现均已修复，无延期问题；没有再派发重复 review。
- fresh clone 独立安装/pip check/27项测试/导出/生成/校验/268条验证/历史校验全部通过，日志与产物已保存，临时clone已清理。
- 最终 current identity 检查通过；所有用户授权任务完成。未提交、未调用付费模型、未上传或冻结。
