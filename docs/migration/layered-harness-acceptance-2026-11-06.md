# 四层 Harness 改造验收（2026-11-06）

## 来源与实施范围

来源为用户本轮提供的四层架构图及《agent_eval_harness 框架改造方案》，起点是 `4c99f206c1d50433478833b80ca23ff2217eefee` 的干净工作树。附件中的阶段和数字用于参考，验收数量按实际代码与证据记录。只在当前 monorepo 工作，没有改被测 Agent、冻结数据、参考答案、历史结果或父目录原项目。

采用渐进抽取，详见[分层说明](../benchmark/layered-framework.md)。新增共享 TaskSpec、四个 Protocol、可选 Suite 引用、Environment、Harness、Scorer、Aggregator 和五份配置；旧 CLI 与 Python API 保留兼容转发。Inspect 继续执行与记录日志，DeepEval 继续正式评分，Langfuse 没有自动上传。

本轮不扩展能力桶、新任务或新领域，不统一被测 AgentLoop。Suite 插件引用目前完成类型、配置和身份编译，历史 Provider 执行桥会明确拒绝不能执行的新槽位；新 Harness 使用可信 Python 对象组合。τ 官方环境与模拟器没有被重写。以上边界不应表述成“所有插件已支持配置驱动执行”。

## 兼容与安全边界

- `TaskSpec.execution_input()` 明确排除 oracle、expected_delta、reference_answer 和 checkpoints；所有冻结 file-tools v1/v2 与 model-decisions 的旧执行投影保持字段、值与 JSON 序列化顺序。
- 旧默认 Suite 编译 fixture 的 hash 保持 `82de01a86acb3d44e987e760007637c991e6c7463108665c101349aa53e82b01`；新增可选引用未配置时不生成 null 字段。
- 新运行指纹纳入抽出模块和共享 TaskSpec，旧结果的身份不回写。worker 仍可独立解释器运行，Docker 复制内容没有新增依赖。
- 配置拒绝未知字段、重复键、嵌套凭据与非本地路径；密钥只保存环境变量名。普通 dict、JSON 和嵌套序列化保留“省略”和“显式设置默认值”的区别。
- 同步 Environment 负责独立 workspace 和清理；Inspect 环境尊重原 sandbox 生命周期。它们不把本地模式称作 OS 隔离。

## 独立审查与修复

审查覆盖实际数据流与边界，三项问题均以失败测试复现后修复：

1. 合法工具操作遇到 ENOSPC/EIO/EROFS 被误记为 Agent 错误：现在归为 environment，并由正式评分得到 INVALID；缺文件、越界等操作错误保留 Agent 归属。失败事件保留错误、时间和可取得的部分状态；Router/UserSimulator 故障归 harness。
2. 公共 ExecutableScorer 曾绕过证据 gate：现在缺证据为 INCONCLUSIVE、环境/Provider/Harness 错误为 INVALID。旧 `score_observation()` / `evaluate_oracle()` 保留原始检查结构，正式 DeepEval 路径仍使用原 gate。
3. RunRequest 普通序列化会把省略的 sandbox 变成显式 Docker：已用保留显式字段的序列化修复，默认 dict/JSON/嵌套往返均有回归。

全包回归还发现生成的 Suite schema 未同步，已更新 `packages/evaluator/schemas/suite_definition.schema.json`。这是代码契约快照，不是冻结数据集。干净 core 环境的一项旧测试无条件要求可选 mini_agent 注册；已改为分别验证有/无依赖的真实行为，不用跳过测试掩盖核心导入问题。

## 历史评分等价性

仅读取保存证据并离线重算评分，没有重新执行历史 Agent、调用模型或修改历史结果。

| 来源 | trial 数 |
| --- | ---: |
| File Tools v1 baseline300x3 | 900 |
| File Tools v1 tool-aware300x3 | 900 |
| File Tools v2 modules60 | 60 |
| Model Decisions 24 × 3 | 72 |
| File Tools v2 chains60 × 3 | 180 |
| File Tools v2 e2e300 | 300 |
| 合计 | **2,412** |

使用 Git 起点原始评分代码与新代码在同一进程交替评分，2,412 条评分对象逐字段相同，包含理由文本；六套运行/报告汇总、v2 重复诊断和 3,859 条保存 Judge 记录的汇总也相同。私有证据在 `artifacts/layered-harness-scoring/`，最终同进程报告为 `legacy-parity-9223372036572069244.json`。

跨进程原始对比曾出现 ToolCorrectness 的 `missing tools` 显示顺序差异。以未修改的旧代码启动八个独立进程、固定 `PYTHONHASHSEED=0` 也复现两种排序：DeepEval 4.2.9 使用 set 生成理由，ToolCall hash 又包含跨进程不稳定的 None hash。原始差异和旧版复现保存于 `parity-final.log`、`legacy-reason-probe.json`。仅工具集合显示顺序波动，分值、verdict 和其他字段不变；不据此承诺历史诊断文本跨进程逐字节稳定。

## 回归与安装

所有测试命令清除了模型/托管服务凭据和付费 smoke 开关，设置 `DEEPEVAL_TELEMETRY_OPT_OUT=YES`、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。

| 检查 | 验收结果 |
| --- | --- |
| Contracts | 3 passed |
| Builder | 353 passed / 5 skipped（未装可选 DeepEval） |
| 参考 Agent 包 | 323 passed / 1 skipped（付费 smoke） |
| SDK | 无独立测试，由消费者回归覆盖 |
| Evaluator 最终回归 | **1,239 passed / 4 skipped**（Docker 集成与付费 smoke 未启用）；101 条既有上游/兼容弃用 warning |
| 根集成 | 58 passed |
| 60 个冻结 module 任务 | 全部走 `execute_module_task → Inspect → 原 nanobot module_worker/ToolRegistry` 通过；不是用新 mock 工具替代被测对象 |
| Lint / 编译 / diff | 包目录 Ruff、compileall、`git diff --check` 通过 |
| 冻结资产 | 1,172 个导入参考资产与 fixture 校验通过；`data/`、`reports/`、冻结 datasets/fixtures 与 Git 起点无差异 |
| 全新克隆安装 | 本地新克隆叠加本轮源码，独立 `.venvs/core`；`setup.py --only core` 与 `pip check` 通过 |
| 干净 core 演示 | 不安装 minimal_agent/Langfuse，核心导入、根 CLI 校验、旧配置 demo、五份配置 demo、报告和 ExternalProvider 演示通过 |
| 干净 core 定向回归 | **112 passed**，覆盖新分层、配置、Suite 与可选依赖分支，无 skip |

包级日志位于 `artifacts/verification/`。全新安装和验收日志位于 `.migration/layered-clean-install.log`、`.migration/layered-clean-acceptance.log`、`.migration/layered-clean-final-tests.log`。新克隆在 `.migration/layered-harness-clean/`，使用自身环境，没有借用原 Evaluator site-packages。离线 reference/demo 不是 Agent 的真实性能成绩。
