# DeepEval 本地源码与业务代码迁移评估

> 历史方案：DeepEval 主引擎与源码迁移方向已被 [Inspect AI 方案](../../inspect_engine.md) 取代。下文记录迁移前状态，不代表当前运行架构。

评估日期：2026-10-15。

## 结论

采用本地 DeepEval 源码工作树作为开发底座，按已确定的三条原则迁移：**双方都有的能力按 DeepEval 原生方式改写；仅本项目有的能力保留为扩展或源码二次开发；仅 DeepEval 有的能力完整保留原生支持。** 扩展包依赖 DeepEval 核心，核心不反向依赖业务包。保留 `eval_framework` 的包名和兼容入口，但不保留重复的通用实现。

能力归属、21 个断言的替换条件、证据差异和新增能力见 [Evaluator 与 DeepEval 能力对照及迁移方案](../../deepeval_capability_mapping.md)。本篇主要处理源码、目录与打包问题；搬迁目录不代表已经完成原生能力替换。

这满足“clone 到本地，再迁移我们的代码做适配”的目标，同时保留同步上游的空间。[官方自定义 Metric 文档](https://deepeval.com/docs/metrics-custom)提供的扩展接口适用于现有业务指标；源码修改用于扩展接口无法解决的框架问题。

## 前期已完成的源码验证

- 从 [官方仓库](https://github.com/confident-ai/deepeval) clone 到 `third_party/deepeval`。
- 固定标签 `python-v4.2.9`，提交 `03ef3a25c2acbf09ef001080d2591704b9606931`，使用浅克隆。
- 核对 10 个关键运行文件，包括 evaluate、TestRun、本地存储、单轮/多轮 TestCase、BaseMetric、GEval 和设置；与当前安装包字节一致。
- 临时将本地源码加入 Python 模块搜索路径，在同一测试进程断言 `deepeval.__file__` 指向该 clone，再运行完整项目回归：**341 passed，2 skipped，52.84s**。两个跳过项是付费 API 冒烟测试。
- 项目 Ruff 检查通过；配置排除上游源码目录，由上游自己的工具配置管理其静态检查。

目前尚未移动业务代码，也没有将虚拟环境永久改为 editable 安装。正常启动的导入路径仍是 `.venv/lib/python3.11/site-packages/deepeval`。源码工作树保持上游标签的 detached HEAD，未创建远程 fork、推送或提交。它目前是独立嵌套 clone，不是已注册的 Git submodule。本次按三条原则更新方案，不代表已经实施以下改写。

## 推荐目录

下面是迁移目标，`extensions/agent_evaluator` 尚未创建：

```text
third_party/deepeval/                  # 后续的源码开发工作树
├── deepeval/                         # 上游核心及必要的通用改动
├── tests/                            # 上游测试
├── pyproject.toml                    # DeepEval 包的配置
└── extensions/
    └── agent_evaluator/
        ├── pyproject.toml            # 独立业务包配置
        ├── src/eval_framework/       # 业务评估、适配与现有公开接口
        ├── packages/agent_trace_sdk/ # 当前本地证据 SDK，仍独立打包
        ├── tests/                    # 项目业务回归
        ├── datasets/
        ├── suites/
        ├── examples/
        └── docs/
```

`mini_agent` 仍作为独立 Agent 项目依赖接入，不复制进 DeepEval。前期统计 Evaluator 有 57 个 Python 模块，约 10,455 行代码；业务测试有 39 个测试模块。目录搬迁可暂时保留结构，最终扩展包只承担原生缺口、对象适配和兼容接口，重叠实现必须在改写后删除。

## 迁移映射

| 当前实现 | 目标处理 | 理由 |
| --- | --- | --- |
| `deepeval_engine.py`、`runner.py` | 按原生执行接口改写，保留预检、生命周期挂接与结果映射 | DeepEval 承担通用调度；Provider 补充资源管理，避免两套执行循环 |
| `assertions.py`、`turn_assertions.py` | 精确匹配、工具和通用结构校验改用原生 Metric；业务时序、状态和证据规则迁为扩展 | 重叠计算删除，原断言 ID 只保留兼容映射；Schema 缺口通过扩展或二次开发支持 |
| `evaluation_policy.py`、`scoring.py` | 收敛为领域汇总策略，消费原生及业务 Metric 结果 | 单指标分数和阈值使用原生实现；扩展关键否决、权重、INCONCLUSIVE 和 INVALID |
| `judges/deepeval.py`、`judges/_deepeval_model.py`、Rubric | 使用原生指标与模型协议，保留业务模型传输和 Rubric 配置 | GEval 已接入；原生支持的其他指标继续可用，不限制为当前语义维度 |
| `provider.py`、`providers/mini_agent`、`runtime_factory.py` | 适配原生回调/迭代器；保留隔离、状态读取、清理和冻结多轮规则 | 仅扩展原生未提供的业务生命周期能力 |
| `contracts`、`plugins`、Loader、Validator | 通用数据读写和扩展协议改用原生；保留领域数据转换、冻结及业务预检 | 将 Suite 编译到原生对象与业务扩展，避免另建通用插件体系 |
| `reporting.py`、`comparison.py`、`gating.py`、`stability.py`、复核模块 | 通用记录、报告、单指标阈值使用原生；仅保留领域导出、严格回归比较、治理策略和统计 | Arena 比较等原生能力保留可用；本地审计与发布决策作为扩展 |
| DeepEval 全局运行状态与本地终结适配 | 验证扩展接口，必要时二次开发通用运行上下文；配置按运行模式隔离 | 减少 `_skip_reset` 等私有耦合，业务模式不得永久禁用其他原生能力 |
| 当前无对应模块的原生能力 | 保留原生 API/CLI、可选依赖及指标/模拟/生成/优化入口 | 标明原生可用、项目已接入、场景已验收三个状态，不重复开发 |

不建议将整个 `eval_framework` 直接混入 `deepeval/metrics` 或 `deepeval/evaluate`。当前业务 Metric 依赖断言、诊断、Provider、Schema 和 Trace；这样搬运会让上游框架依赖本项目的业务环境，增加升级合并的范围。

## 需要解决的适配问题

1. **安装入口。** DeepEval 使用 Poetry 构建，业务项目使用 setuptools。保留两个独立包，使用明确的本地可编辑安装入口；不要把业务依赖塞入上游的通用依赖列表。
2. **路径与资源。** 业务测试和示例会通过文件位置寻找 datasets、Suite 和能力包；迁移时保持这些资源与扩展包根目录的相对结构，核对命令和 SDK 安装路径。
3. **测试配置。** 上游与业务 pytest 配置不同。业务测试继续禁用自动接管运行的 DeepEval pytest 插件和自动重跑插件；显式选择配置与测试目录。
4. **源码指纹。** 现有报告只记录发行版版本和适配版本。本地二次开发后，增加上游基线提交、fork 提交及实际运行代码和模板的内容指纹，覆盖未提交修改；这些条件参与可比性检查。
5. **结果兼容。** 保留 `eval_framework` 包名、CLI 和 results.json 读取能力，验证原生 TestRun、报告复制和 Gate；已编译 Suite 的插件指纹需要重新校验。
6. **版本控制。** 当前嵌套 clone 不能作为主仓库自动携带完整源码和改动。正式迁移时在源码工作树建立本地开发分支，明确它为权威代码仓库；同步上游与维护扩展分别提交。远程 fork 或推送不属于本轮操作。

## 实施顺序与验收

以下步骤包含打包、原生改写与扩展，不能以目录迁移完成代替能力迁移完成。行为变化按原生通用口径与必须保持的业务约束分别验收。

1. 在固定提交的源码工作树建立开发分支，配置源码及扩展包安装脚本；验证默认导入来自本地源码，而非依赖临时 PYTHONPATH。
2. 迁移业务包、SDK、测试和配套资源，保持公开接口；修正安装、资源和示例路径。
3. 按能力对照逐项将重叠能力改为原生实现，删除重复计算、调度和通用展示。差异通过数据适配、指标配置、扩展或必要核心补丁处理。
4. 接入原生未覆盖的契约、证据、状态、时序和治理能力；补充源码身份及实际运行内容指纹，记录通用评分口径变化并重跑基线。
5. 验证原生 API/CLI 及代表性新增能力仍可使用；配置不得被业务扩展全局覆盖。记录可选依赖、数据要求及业务接入状态。
6. 从新工作树完整运行业务测试、Judge 离线测试和受影响的原生测试。SQLite 礼物示例应保留 8 个 Trial、4 PASS/4 FAIL、全部 VALID/CLEANED；核对原生和领域结果、旧报告读取及关键业务约束。
7. 将旧入口收敛为兼容入口，验收 A 类重复实现已删除、B 类扩展已接通、C 类原生能力未裁剪。通用核心 API 改动单独维护并补对应上游测试。

切换到同版本源码已由前期完整回归验证；新的原生改写、扩展和源码补丁需要另外验收。源码二次开发由明确缺口驱动，并保留同步上游的边界。Suite Metric/Judge Profile 的声明式装配纳入能力迁移工作，源码搬迁不会自动完成它。
