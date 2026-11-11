# v4 正式 benchmark 接入与真实评测计划

目标：仅使用 mini_agent_full_eval_20261111_v4 原始365条行为定义，Harness/Inspect在Docker environment运行，DeepEval规则评分与DeepSeek G-Eval，报告及Langfuse交付。用户已授权本轮真实模型与Langfuse请求。

架构：新增可选v4 Domain、Adapter和worker，复用原operation/Agent执行器、MiniAgentProvider、Inspect bridge、benchmark runner、G-Eval及Langfuse导出；不改MiniAgent业务、冻结定义或历史结果。76条真实模型，289条确定性，全部重新执行。LLM评分保留现有未校准诊断语义，不覆盖规则失败。

实施采用executing-plans内联方式，最后一次独立review。

- [ ] 接入与测试：验证365/76/289分类、来源Hash、Oracle隔离；新增Domain/worker/Adapter，扩展沙箱显式文件包和真实模型注入点。先观察失败测试再实现。
- [ ] 验证规则评分与G-Eval：保留原Oracle，测试真实模型输出不会被预设候选覆盖；确定性案例不调用LLM；工具故障仍由environment注入。
- [ ] 接入现有report/Langfuse数据加载；全链路离线小样本验证，不调用真实服务。
- [ ] 独立review、相关回归、全新安装验收；按新输出目录执行365条一次，G-Eval只评真实模型证据，禁自动重试。
- [ ] 生成报告、导出Langfuse并回读验收；记录模型用量、失败、不适用项、287 blocked和202静态契约检查，不混淆分母。

风险边界：冻结期望可能与真实模型结果不一致；如实FAIL。原reference中要求固定候选/固定JSON最终文本的检查仅适用于reference，不作为真实模型评分。正式规则使用原用例Oracle和独立证据完整性。G-Eval未经过人工校准，报告独立列出，不能用于掩盖规则失败。

## 已完成及验收记录

- Domain/Adapter/worker已接入；新CLI scripts/mini_agent_v4_benchmark.py；365条来源Hash及76/289分类验证通过。
- 无网络完整规则回归：365例复现362PASS/3FAIL；首批6项测试通过，新增审查反向测试3项通过。
- 独立review发现并修复：G-Eval同轮snapshot、事件按实际时间排序防止未来证据泄漏、取消保留已发生模型用量、正式规则源码Hash闭包。均以反向测试验证。
- Docker三类确定性小样本3PASS；真实模型bridge使用mockllm替身1PASS，含Pydantic输出、SDK轨迹和可评分G-Eval上下文。无付费调用。
- 三例确定性结果复用既有judge_run标注9项NOT_APPLICABLE，Judge调用0；报告生成与Langfuse payload构建通过，未上传演示数据。
- Docker本地包构建网络重试较慢，v4采用镜像已安装setuptools构建，--no-build-isolation仅影响v4显式入口；其他adapter默认不变。
- 正式执行已启动：artifacts/mini-agent/v4-deepseek-formal-20261111/execution；模型deepseek-v4.1-flash，OpenCode Go；每例一次，并发8，最多400次Agent模型请求，无自动重试。
- 全包回归日志tmp/v4-formal/evaluator-regression.log；fresh clone验收tmp/v4-formal/acceptance-logs/。Langfuse云端预检遇到系统代理握手超时，后续继续交付回读。

## 并行验收干扰与修正

- 首次正式尝试在280条已保存结果后中止，generation记录0。fresh-clone Docker验收重建同名镜像，使image_id从3ec7e0…变为bc38a1…；依赖环境Hash相同，仍正确触发不可变镜像身份保护。保留原目录并写INTERRUPTED.md，不算Agent失败或正式成绩。
- fresh clone安装、9项新增测试、真实bridge离线演示均通过，389份相关源码已核对。克隆和环境已移除，验收日志/产物保留在tmp/v4-formal/acceptance-*。
- 全包回归1584 passed、9 skipped、1 failed；唯一失败为执行途中源码变化触发runner身份保护。稳定后该项独立复测1 passed（13.46秒），没有修改测试或关闭身份保护。
- 正式运行改用artifacts/mini-agent/v4-deepseek-formal-20261111-r2，期间不再改源码或重建同名镜像。
- 用户确认Langfuse仍交付配置的云端，用户正在检查网络；不切换本地实例。

## 本轮实际结果与未完成项

v4-r2共365条全部形成执行记录：289条确定性PASS；76条真实模型为13PASS、15FAIL、48INVALID（模型连接错误）。规则合计302PASS/15FAIL/48INVALID。实际成功模型响应为deepseek-v4.1-flash；记录到36条成功generation及48条失败generation，已知token小计28284，失败请求成本未知。

OpenCode只读接口与Langfuse云端TLS仍超时，G-Eval未运行、Langfuse未上传。代码接入、离线贯通和本地规则报告已完成，不能宣称本轮正式评测交付完整。保存pipeline_status.json与剩余judge/report/export/verify命令；继续评分不重跑Agent，48条INVALID需在网络恢复后另行有来源关联的补测，不能由Judge补造成功。

最终目录artifacts/mini-agent/v4-deepseek-formal-20261111-r2包含README、execution/report.html、failure_details.json和完整Inspect证据。1448份文件及压缩日志未发现实际OpenCode/Langfuse密钥泄漏。
