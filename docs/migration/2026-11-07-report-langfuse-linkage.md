# 报告与 Langfuse 联动验收

用户批准执行：从证据自动归纳问题和建议、保持领域配置可选、HTML 与 Langfuse 联动，并维持框架与 Agent 解耦。本次没有调用模型、执行 Agent 或重新正式评分。

## 交付范围

- 新增独立 `report_diagnostics.py`、`report_links.py` 与可选 `langfuse_presentation.py`。HTML 和远端展示共用版本化诊断 JSON，旧解释按内容 Hash 归档。
- mini_agent 参数别名配置移至 `configs/benchmark/mini-agent-diagnostics-v1.json`；意图作用域、版本及 Hash 受校验。配置缺失时仍能生成通用报告，不推断字段等价，不修改输出。
- 新增显式 CLI `scripts/benchmark_presentation.py`。默认离线；只有 `--sync-langfuse` 才读取凭据并访问远端。报告逐条链接经源 Hash、目的地与导出收据核对。
- Langfuse v4 历史观测不可变，因此历史 Trace 不重新入库：主集 30 条补充 44 项分类注释，两次独立补跑各 3 项，共 32 条 / 50 项。均带 `formal=false` 与源诊断身份，并完整回读核验。未来首次导出才增加名称、标签和诊断 metadata；原始 ID、输入输出、时序及正式分数不变。
- 主集 Dashboard 展示正式 verdict、读写场景分组和失败类别；源结果 Hash 限定运行，诊断名限定解释版本。日期写入分享链接，避免浏览器保留的旧时间范围导致空图。补跑与主集不合并。

## 实际数据与浏览器验收

Dashboard URL：

[主集评测与诊断](https://cloud.langfuse.com/project/cmvgd40xe02ecad0en362z7wd/dashboards/cmw6jzyoc001oad0dt4pm8dc8?dateRange=1794060775104-1794061363151)

Metrics API 与实际浏览器均确认：19 PASS / 11 FAIL；read PASS 18、FAIL 2，write PASS 1、FAIL 9；schema_mismatch 9、missing_confirmation_context 3、business_failure_status 1、restricted_response 1。类别可重叠。写场景唯一 PASS 属于非法参数保护，不能当作成功发放。

HTML 浏览器检查包含 30 条 trial、30 个远端链接、问题编号跳转以及桌面/窄屏排版。原始 Trace 和分数在同步诊断后再次完整回读，三个运行均 VERIFIED，无新增观测节点或正式指标。

## 兼容性与检查

- 离线测试覆盖配置可选、Hash/作用域、条件建议、链接绑定、确定性分类注释、不确定提交不重发、Dashboard 复用及 SDK 请求序列化。首次全包检查发现两个历史测试替身未接受新增可选参数；调整替身接口后重测，保留首次失败日志。
- 实际接入发现当前 SDK 的 Score 字段组为 subject/details，批量接受响应没有 errors 属性；Dashboard 不接受 traceId 筛选，改用保存的源结果 Hash。SDK 的 placement 使用 widget_id 字段，经过模型和服务端验证。未将这些失败当作交付成功。
- 既有全新克隆的 core 环境同步本次纯离线报告模块，无 minimal_agent 或 Langfuse SDK，核心导入成功，离线 demo 5 PASS。此次依赖未变，未重复安装依赖。
- 相关最终检查 63 passed；Ruff、差异空白检查通过。完整包回归 1,448 passed / 9 skipped，316.96 秒；最终结果记录在交付目录 `presentation-verification.json` 和 `presentation-regression-final.log`。
- 逐一核对先前交付记录中的 73 个原始 results、run、trial、Inspect 日志和 Trace Hash。累计模型请求仍为 53/60，本次新增 0。

本地交付位于 `artifacts/mini-agent/coverage-20261107/`；ZIP 包含 HTML、离线证据、版本化诊断及链接/远端核验收据。凭据扫描在打包前执行，不包含 `.env`、运行环境或 sandbox 构建目录。本次未提交或推送 Git。

## 推送前复查

用户随后授权提交并推送当前功能分支。对待提交的 142 个文件执行实际本地凭据值扫描，未发现凭据；`.env` 与 artifacts 维持忽略。Evaluator 文件按包内配置进行 Ruff 检查，根脚本按根配置检查；整理两个新增入口脚本的执行权限和一处导入顺序，CLI `--help` 均通过。

重新运行包回归时，既有 `test_provider_cleans_nested_processes_on_inspect_termination[False]` 在 `started.exists()` 失败，单独复测同样失败（5.24 秒）。测试要求在 2 秒运行预算内完成 Provider 启动并到达嵌套进程；本次 `started`、`completed`、`cleaned` 均未出现。与先前全新安装环境中已记录的启动时限限制一致，并非观察到后代进程逃逸，但也不能据此证明该次清理链路通过。该测试及对应 Provider 执行代码本次未修改，未通过放宽断言或修改冻结数据绕过。本次推送前检查不宣称全绿；前文 1,448 passed 是此前交付检查的真实结果，予以保留。完整新日志位于本地交付目录的 `pre-push-regression.log` 与 `pre-push-termination-retest.log`。

推送前完整回归结果：`1 failed, 1447 passed, 9 skipped, 142 warnings in 342.75s (0:05:42)`。唯一失败项为上述已记录的启动时限检查。

## 2026-11-08 审查跟进

- 问题 #1 明确两层证据和修复优先级：实际意图请求仅含通用 Schema，未列出标准参数；模型随后输出非契约字段。第一步补齐 Schema 注入并检查实际请求，第二步才按需添加别名兜底。没有新对照评测，不宣称修复足以解决所有失败。
- 总览标题明示 19 PASS / 11 FAIL / 0 INVALID。第四类 `restricted_response=1` 原已存在，补充 InvalidModelOutputError 的对应说明，不重复添加失败计数。四类为 9/3/1/1，存在交叠，覆盖 11 个失败 trial。
- 新增纯离线 `report_trends.py` 和可选 `langfuse_trends.py`。比较组固定数据、契约、选集、评分、Harness 与执行控制；允许模型/运行源码变化并保存身份。INVALID 保留在分母，不完整、重复和不可比运行被拒绝。
- 通过 experiment 级、formal=false 的 2 项汇总展示读 90%、写 10%。仅主集进入比较组，两次不同配置补跑排除。Langfuse 时间桶可能合并多个 run，桶内为比率等权平均；空桶 n/a/0 是无数据。逐 run 分子、分母和身份另存 JSON/CSV，不伪造改善趋势。
- 复用现有 Dashboard ID 和前三个 Widget ID，新增第四个趋势面板；显式刷新时归档旧收据。API 回读与实际浏览器确认 19/11、读写 18/20 与 1/10、四类诊断及趋势 90/10。API 会忽略 PIE/LINE_TIME_SERIES 的 show_value_labels，移除不支持的配置并添加回归覆盖；数值置于总览标题。
- 85 项相关离线测试通过（1 项依赖弃用警告），Ruff 与 git diff --check 通过。独立 core 环境未安装 mini_agent/Langfuse SDK，当前报告与趋势模块仍可导入并生成趋势。本轮未重复全包回归；前节已记录的子进程启动时限失败仍保留，不改执行层掩盖失败。
- 3 个运行的新解释注释共 50 项回读 VERIFIED，原解释版本保留；原始 Trace 和正式分数不重发、不重新评分。冻结原始文件逐字 Hash 核验、HTML 的 30 条用例及 30 个 Trace 链接检查随交付验收记录保存。本次新增模型请求 0，累计仍为 53/60。
