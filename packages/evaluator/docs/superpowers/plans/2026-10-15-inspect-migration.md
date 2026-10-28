# Inspect AI 本地源码迁移实施计划

> 使用 superpowers:executing-plans 连续执行；用户已授权自行完善、自审并完成改造，无需再次确认。

**Goal:** 默认评测由本地 Inspect Task / Solver / Scorer / Epochs 实际执行，业务代码迁入其源码仓库的独立扩展包，保留已有领域结果和 DeepEval Judge。

**Architecture:** Inspect 管理 Sample 调度、重复执行、评分和原生日志。Provider 生命周期、冻结契约、独立证据和治理作为扩展；原生支持的通用匹配采用 Inspect Scorer。DeepEval 只作为可选质量评分组件，不再拥有第二套运行管理器。

**Tech Stack:** Python 3.11、Inspect AI 0.3.280 本地源码、现有 Pydantic/SQLite/pytest、DeepEval GEval。

**Spec:** 已确认的 Inspect 主框架决策，以及能力对照中的三条原则（重叠采用原生、独有保留扩展、额外能力保留支持）。原 DeepEval 主框架目录方案由本计划取代。

## Global Constraints

- 保留现有未提交工作；不推送、不调用付费模型，不把 Agent 本身改造成另一个实现。
- 运行时仅接收 ExecutionSpec；Inspect Sample 不存 Oracle，Scorer 通过评测侧映射获取。
- 保留 FAIL / INCONCLUSIVE / INVALID、关键项否决、独立证据失败不回退以及清理失败阻断。
- 本机无 Docker，真实 SQLite Provider 的隔离与清理必须验证；原生 Docker/K8s 接口保留，容器执行明确列为未验证。
- 本地 clone 固定发布标签和提交，以 editable 安装运行；内容指纹覆盖源码未提交变化。
- 保留包名、CLI、旧结果读取和根目录兼容路径；只有一份权威业务源码。
- 限定本次改造为迁移既有能力与原生执行接入；过去未接通的通用 Suite Profile 不伪称已支持。原生自定义 Task/Scorer 保持可用。

## Review Focus

- Inspect 的 Sample/TaskState 不得泄漏 Oracle；模型调用只发生于明确的 Provider/Judge。
- 原生 epochs 必须真实重跑并独立清理，每个 Case/Trial 一一对应日志。
- 清理失败和部分证据下的真实违规不能被成功输出/高分掩盖。
- 原生匹配默认忽略大小写/标点，不得破坏严格结构比较和字符串空白语义。
- 移动目录不能破坏数据集相对路径、原生文件复制、源码指纹或原生独立入口。

### Task 1: 本地源码和实施基线

- [x] 固定 Inspect 0.3.280，editable 安装并断言真实导入路径，记录提交。
- [x] 保存迁移前源码备份和测试证据；记录自审决定。
- [x] 验证 `pip check`，不引入无必要的核心修改。

### Task 2: 原生执行闭环

**Files:** 新增 `src/eval_framework/inspect_engine.py`、`tests/test_inspect_engine.py`；修改 `runner.py`、`reporting.py`。

**Interfaces:** `execute_cases(cases, config, provider, root, *, evaluator_run_id, judge_client, rubric)` 返回领域 CaseResult 列表、原生产物引用、模型元数据。Solver 调用现有 Provider 生命周期扩展，Scorer 调用领域策略，真实 epochs 由 Inspect 调度。

- [x] 先写测试证明 Task/Solver/Scorer 与 epochs 真实执行、无预评分、无 Oracle 暴露；运行看到缺少 Inspect 默认后端的失败。
- [x] 实现 `mockllm/model` 仅作为不调用模型的框架占位，业务 Agent/Judge 保留独立模型身份。
- [x] 使用 Inspect 原生日志；报告按产物相对路径复制；历史 DeepEval 日志仍可读取/复制。
- [x] 替换旧主引擎测试的默认路径，保留有效性/证据/清理等业务覆盖，删除旧主调度实现。
- [x] 运行聚焦测试和现有回归。

### Task 3: 原生评分和扩展边界

**Files:** 新增 `native_scoring.py`；修改 `assertions.py`、`turn_assertions.py`、`evaluation_policy.py`，补原生评分测试。

**Interfaces:** 严格值比较、包含关系由原生 `pattern` / `includes` Scorer 计算；适配只做值规范化和投影，结构 Schema、工具证据与业务时序保留扩展。

- [x] 先写原生调用与语义边界测试：标点/大小写/空白、缺失键、参数子集、多轮以及部分证据。
- [x] 原生评分使用实际值，禁止先在旧逻辑算 bool 再包装；结果保留原生指标身份。
- [x] DeepEval Judge 保留，配置更改限定于调用作用域，不能影响原生独立入口。
- [x] 运行确定性评分、Judge 和状态型回归。

### Task 4: 源码迁移与可追溯性

**Files:** `third_party/inspect_ai/extensions/agent_evaluator/` 为权威业务目录；根目录保留相对符号链接；新增安装脚本和源码身份记录。

- [x] 先写指纹内容变化测试与默认导入路径检查。
- [x] 将 src/packages/tests/datasets/suites/examples/docs/schemas/policies 及包配置迁入扩展目录；不移动凭据和虚拟环境。
- [x] 本地安装 Inspect、SDK 和扩展包；测试配置独立于上游，保留根目录命令。
- [x] 记录 upstream commit、运行源码/模板内容 Hash、扩展和 SDK Hash；比较条件含引擎身份。
- [x] 验证原生 `inspect` CLI、离线原生 Task、业务 CLI、旧结果和报告迁移。

### Task 5: 文档、回归和独立审查

- [x] 更新当前架构、能力和使用文档，旧方案标明被取代，不把沙箱或未实现 Profile 写成已实现。
- [x] 完整业务 pytest、Ruff、pip check、SQLite 8 Trial 示例、Inspect 原生独立示例。
- [x] 根据 executing-plans 要求进行一次独立审查；修复重要问题并补回归。
- [x] 写最终验收记录，列明支持范围、跳过测试和可复现命令。

## 自审决定

- 当前 Provider 为同步接口，作为生命周期扩展在 Solver 中执行；不宣称 Inspect 能强制取消任意同步代码。清理和证据快照在 Scorer 前完成，清理错误进入评分有效性。
- 原生 Sandbox 保持可用，但本项目 SQLite 环境不冒充容器沙箱；缺少 Docker 不妨碍已有业务能力迁移。
- 原生严格匹配采用 `pattern` 而非默认 `match`，避免默认标点规范化影响业务断言。
- 本次不将任意 JSON 配置解析为 Python 类；延续可信实现显式注册边界。
- 先完成默认原生执行，再搬迁权威源码；根目录符号链接只是兼容入口，不保留第二份实现。
