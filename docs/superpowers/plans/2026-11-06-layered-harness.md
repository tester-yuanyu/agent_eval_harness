# Harness 分层改造 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Independent owned files may run in parallel; coordinator integrates and verifies.

**Goal:** 在保留现有任务、评分和入口兼容性的前提下完成自身框架分层。

**Architecture:** 现有 Inspect 执行路径接入 Environment；DeepEval 通过 Scorer 调用既有确定性断言。通用 contracts、显式插件引用、五份 Spec 和独立 aggregator 提供扩展边界。

**Tech Stack:** Python 3.11+、Pydantic 2、Inspect、DeepEval、pytest、ruff。

**Spec:** `docs/superpowers/specs/2026-11-06-layered-harness-design.md`

## Global Constraints

- 只在当前仓库修改；子代理不暂存、不提交、不改其他代理拥有的文件。
- 被测 Agent 暂不改，冻结数据/参考答案/历史结果不改；不调用真实模型或托管服务。
- 保留旧 CLI、Python 导入和历史默认 hash 语义；新增有效配置进入身份。
- 文档中文；运行使用各包独立环境。

## Review Focus

- 未指定新引用时 Suite 序列化不能加入 null 字段而改变历史 hash。
- Oracle、expected_delta、参考答案不能进入执行消息或工具输入。
- worker 独立解释器和 Docker 文件复制列表必须覆盖迁移后的依赖。
- 异常、重复 reset、超时后环境清理与快照不能串 task。
- 配置迁移不能丢未知键、暴露嵌套 secret 或忽略用户配置。

### Task 1: 协议、共享任务契约与 Suite 接线（协调者）

**Files:** `plugins/{protocols,models}.py`、`contracts/{models,compiler}.py`、`packages/contracts/src/eval_contracts/benchmark.py`、`benchmark/schema.py`、对应测试。

**Interfaces:** 四个 Protocol 使用建议中的 reset/step/snapshot/final_state/teardown、parse/validate_args/dispatch、next_message/should_terminate、score(trace, final_state, task)。旧任务经显式构造映射成公共 execution 与私有 expectations，冻结 JSON 不重写。

- [x] 添加失败测试：可选引用缺省时旧序列化一致；显式引用拒绝类型/版本错误；私有答案不进入 execution。
- [x] 实现协议、schema 和 Suite 编译；运行对应测试。

### Task 2: Environment 与 Harness（执行代理）

**Files:** 新 `environments/`、`harness/`，`benchmark/inspect_runtime.py`、必要的安全路径兼容入口和复制依赖清单，专属测试。

**Interfaces:** FileToolsEnvironment 管独立 workspace；可信 host 读取 final_state；固定 UserSimulator 保持 followups 顺序；旧 execute_boundary 入口签名保持。

- [x] 添加并运行失败测试：reset/snapshot 深复制、路径隔离、teardown、固定多轮终止。
- [x] 抽取实现并接入 Inspect 路径；验证既有 Harness 集成测试和 60 个 module 任务相关覆盖。

### Task 3: Scorer 与 Aggregator（评分代理）

**Files:** `benchmark/scorers/`、`aggregator/`、`benchmark/{oracle,judging,metrics,runner}.py`，专属测试。

**Interfaces:** scorer.score(trace, final_state, task) 返回既有 checks、verdict/evidence；保留 evaluate_oracle 和 summarize 的兼容 API。

- [x] 先固定既有离线评分、汇总输出并添加新接口失败测试。
- [x] 迁移实现并使 DeepEval 走新 scorer；已有汇总完整迁入 aggregator。
- [x] 对可读取历史证据逐项对比旧版结果，记录样本数和差异。

### Task 4: 五份配置（配置代理）

**Files:** 新 `orchestration/`、`benchmark/cli.py`、`configs/` 新示例、迁移脚本和专属测试。

**Interfaces:** RunRequest 读取五份 Spec 并组装旧运行 config、dataset 选择、repeats/concurrency；兼容旧 --config；不修改 runner。

- [x] 添加并运行失败测试：旧配置与拆分配置等价、相对路径、非法/重复/未知字段、secret 拒绝。
- [x] 实现迁移和 CLI 接线；验证现有 CLI 测试。

### Task 5: 集成与验收（协调者）

**Files:** 来源清单、架构文档、`docs/migration/` 验收记录、必要集成修复。

- [x] 检查实际依赖边界和迁移后源代码身份，运行相关包回归与 ruff。
- [x] 独立代码审查；修复重要问题并跑对应回归。
- [x] 校验冻结资产和新克隆安装/demo；记录真实结果及剩余边界。

## 接口预检与裁决

- Task 1 的协议供 Task 2/3 使用：dict 边界保持兼容，插件实现不依赖具体 Agent。
- Task 3 拥有 runner.py，Task 4 通过 CLI 组装调用，避免并发修改。
- Task 2 不迁移 trajectory.py：代码证据表明它负责私有 checkpoint 评分，应留在 Benchmark。
- 用户已提供架构与改造建议并直接要求实施，本计划细化实施边界，继续授权范围内工作。

## 最终验收与范围裁决

- Contracts 3、Builder 353、参考 Agent 323、Evaluator 1,239、根集成 58 项通过；跳过均为既有可选依赖、Docker或付费 smoke，详见验收记录。
- 全60个module任务通过原生 worker验证；2,412条历史 trial 同进程旧/新评分对象完全相同，冻结资产1,172项通过。
- 全新克隆独立core安装、两种配置demo、旧ExternalProvider演示和112项定向回归通过。
- Runtime source closure现绑定新目录及共享schema，历史记录不重写；Suite默认hash不变。
- 维持Provider执行桥与新Harness的边界：Suite新槽位仅编译校验与身份记录，显式使用时旧桥报错，当前通过可信Python对象组合新Harness；不宣称通用插件自动装配已交付。
- Trial层级按既有保存记录语义建模，不把历史单case重复执行重写为图中的整套任务trial；新增指标/能力桶不在本轮范围。
- 新Scorer公共入口加证据gate，旧原始Oracle输出不变；既有DeepEval跨进程工具集合理由排序波动另有原始证据，不修改历史理由以制造字节一致性。
- 独立审查的环境错误分类、公共Scorer缺证据、配置序列化往返问题均经红绿回归修复，无未处理的重要代码审查问题。
