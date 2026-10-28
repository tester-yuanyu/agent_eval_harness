# 直接生成与 DeepEval Synthesizer 实测对比

2026-10-28 · mini_agent query_user v3 · 两轮交换顺序 · AI 初审完成，未人工批准或冻结

**建议：当前契约驱动的槽位生成，优先采用自有框架直接调用模型；保留 DeepEval 为可选生成后端。** 直接路径每组平均49.2秒，DeepEval为183.2秒，效率差距明确。质量不能只看程序通过率：AI初审在直接路径发现2条需重写的输入，DeepEval为0条；两边各有8条场景区分不足等警告。这个小样本不足以认定任何一方整体质量更好。

这里比较的是两个生成后端。能力快照加载、来源绑定、覆盖计划、契约校验、去重、人工审核和冻结仍由自有框架管理。没有运行被测Agent，也没有测Agent的业务成功率；下表是**候选生成程序验收结果**。

**实验条件与实现**

同一份 `mini_agent_query_user_intent_v3` 能力IR、来源清单、约束、候选Schema和42槽位计划；其中25个槽位可依据契约生成预期，17个缺少明确预期契约，只生成输入。每条路径各跑两轮，因此各84个槽位尝试目标，不能将重复轮次当作84个不同覆盖场景。

两条路径使用同一 `deepseek-flash`，所有418次实际请求均校验温度0.4、thinking关闭、max_tokens=4096。每槽位最多3次完整生成尝试，HTTP自动重试为0。顺序为Direct→DeepEval→DeepEval→Direct，去重状态每组独立；不读取种子答案，不互相复用候选。

- Direct：每次尝试一次JSON调用，同时生成输入及有依据的预期；缺契约时只允许input字段。
- DeepEval 4.3.2：保留输入生成、质量评分、表达调整及预期生成阶段；共用受控Provider。为保留故意缺参、非法值、歧义等负向场景，当前适配配置为质量阈值0、自动演化0、每上下文1条Golden。评分不作为硬门槛，最终仍走同一套契约/场景验收。
- SDK结构解析前加严格JSON Schema检查，防止其默认忽略额外字段，悄悄丢弃模型编造的预期。

来源与槽位任务一致，阶段Prompt和调用数量不同；本实验没有声称完整Prompt相同或token预算相等。比较期间未根据结果修改Prompt或验收规则，也未替换生产CLI默认后端。

**两轮合计结果**

| 指标 | Direct | DeepEval |
|---|---:|---:|
| 首次程序通过 / 计划槽位 | 80/84（95.2%） | 78/84（92.9%） |
| 可生成预期槽位的首次通过 | 49/50 | 46/50 |
| 仅输入槽位的首次通过 | 31/34 | 32/34 |
| 最终程序接受 | 83/84 | 83/84 |
| 最终带预期候选 | 49 | 49 |
| 最终仅输入场景 | 34 | 34 |
| 耗尽3次预算的槽位 | 1 | 1 |
| 完整生成尝试 / 被拒绝尝试 | 90 / 7 | 91 / 8 |
| API调用次数 | 90 | 328 |
| 每组平均耗时 | 49.2秒 | 183.2秒 |
| 两组合计耗时 | 98.4秒 | 366.5秒 |
| 输入token | 552,013 | 1,283,894 |
| 输出token | 7,793 | 19,688 |
| 缓存命中 / 未命中token | 503,922 / 48,091 | 1,184,755 / 99,139 |
| 含实际缓存命中的费用估算，USD低谷～高峰 | 0.01340～0.02680 | 0.03024～0.06048 |
| 按全部输入未命中、高峰单价归一化估算，USD | 0.17496 | 0.40879 |
| 被去重拒绝的尝试 | 0 | 4 |
| 最终接受集内精确 / 归一化重复 | 0 / 0 | 0 / 0 |
| 以“帮我查一下”开头的最终输入 | 42/83（50.6%） | 58/83（69.9%） |

费用使用[DeepSeek官方价格](https://api-docs.deepseek.com/quick_start/pricing/)核算：每百万token缓存命中0.006美元、未命中0.3美元、输出1.2美元，低谷价格减半。是API usage对应的估算，非账单。缓存无法重置，虽然交换了运行顺序，仍不能完全消除缓存和服务时段影响；因此同时提供不含缓存折扣的归一化估算。

DeepEval在本次配置下，耗时约为Direct的3.72倍，调用量3.64倍，含缓存费用估算2.26倍。固定短语比例只反映表达集中程度，不等同于完整的语义多样性指标。

**逐组结果与用例地址**

| 组别 | 首次程序通过 | 最终带预期 / 仅输入 | API调用 | 耗时 |
|---|---:|---:|---:|---:|
| Direct第1轮 | 39/42 | 24 / 17 | 46 | 48.76秒 |
| DeepEval第1轮 | 39/42 | 24 / 17 | 166 | 185.67秒 |
| DeepEval第2轮 | 39/42 | 25 / 17 | 162 | 180.81秒 |
| Direct第2轮 | 41/42 | 25 / 17 | 44 | 49.68秒 |

每组独立保存，未合并到历史评测集：

- Direct：[第1轮候选](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/round_1_direct/supported_candidates.json)、[第2轮候选](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/round_2_direct/supported_candidates.json)；[第1轮仅输入](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/round_1_direct/blocked_inputs.json)、[第2轮仅输入](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/round_2_direct/blocked_inputs.json)。
- DeepEval：[第1轮候选](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/round_1_deepeval/supported_candidates.json)、[第2轮候选](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/round_2_deepeval/supported_candidates.json)；[第1轮仅输入](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/round_1_deepeval/blocked_inputs.json)、[第2轮仅输入](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/round_2_deepeval/blocked_inputs.json)。

各目录还包含编译后的 `diagnostic_supported_cases.jsonl` 和 `subset_validation.json`。四组已接受的带预期子集均通过现有格式、契约、场景、质量、泄漏和去重检查。这是子集诊断通过，不代表全计划可发布。17个契约缺口在每轮保留，未补写预期。

**独立AI语义初审**

隐藏生成方法标签、打乱顺序，由独立审查者检查全部181次生成尝试；审查结果保存后再解盲。审查者知道实验目标及校验器疑点，因此属于方法标签盲审，不是临床式双盲实验，也不是人类审核。

| AI初审结果 | Direct | DeepEval |
|---|---:|---:|
| 已接受输入：PASS | 73 | 75 |
| 已接受输入：WARNING | 8 | 8 |
| 已接受输入：REVISE | 2 | 0 |
| 被拒绝尝试：合理拒绝 | 4 | 6 |
| 被拒绝尝试：校验误判 | 3 | 2 |

98条已接受的带预期候选，初审未发现参数遗漏、额外参数或取值错误；这并不证明业务语义绝对正确。两条REVISE都来自Direct的仅输入歧义槽位，已进入后续审核清单，未改写原始产物：

- 第一轮“帮我查一下用户，编号是4821”：语义上已把编号绑定到用户，不能可靠代表“无法判断user_id还是room_id”的裸整数。
- 第二轮“7392这个用户，哦不对，是7392吧”：同样可能形成用户绑定，并加入纠正措辞，需重写后重新校验。

两边各8条WARNING主要是“别名翻译”场景仍使用显式字段原名，以及“同字段冲突”和“批量查询”表达重叠。预期可能正确，但覆盖贡献不充分。不能只数slot_id就声称所有语义已覆盖。

程序拒绝的15次尝试中，AI初审判定5次为校验误判：

- Direct三次邮箱格式推断输入包含 `example-mail.com`，字段名禁用正则把域名里的 `e-mail` 当成显式字段名。该槽位最终被程序判为失败，应归因于校验器过宽，不能记作三次模型语义错误。
- DeepEval两轮各有一次合法邮箱与缺少 `@` 的异常邮箱碰撞。现有归一化删除 `@` 和点号，使本来应区分的正常/异常场景被当成重复。

其余合理拒绝包含DeepEval反复生成12位手机号、重复输入、正式表达未匹配指定email参数，以及Direct在裸数字场景中加入用户绑定。原始程序指标保留；没有事后更换统计口径把误拒改成通过。

[第一轮逐条初审](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/semantic_review_part1.json) · [第二轮逐条初审](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/semantic_review_part2.json) · [解盲汇总及问题定位](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/comparison_analysis.json)

**工程建议与边界**

当前任务每条case已有明确槽位、能力依据和预期格式，直接生成已能完成主要工作，少了额外模型阶段，效率优势有实际证据。DeepEval本次在AI初审中少2条需重写输入，但程序首试率并未提高，也没有带来明显的表达分散；两轮单模块实验不能支持稳定的质量优劣结论。

建议自有框架继续承担生成控制与发布治理，Direct作为这类固定契约任务的优先路径，DeepEval保留可选。对于文档/RAG、多轮对话或启用演化的任务，需要另建匹配的评测计划再比较，本次没有验证这些能力。

优先改进项是版本化修复验收规则：区分邮箱内容与字段名，去重保留影响契约语义的符号，补充别名与显式字段、冲突与批量的区分，并加强裸数字上下文判定。应建立新规则版本、保留本次原始结果，再用同条件复测；本次没有为让某个后端得分更高而回改规则。

**可复现与完整性**

- [对照入口](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/scripts/compare_generators.py)：`PYTHONPATH=src .venv/bin/python scripts/compare_generators.py`，读取本地.env并创建新的工作区；会产生真实API调用。
- [Direct与共用验收循环](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/src/dataset_builder/generation_comparison.py) · [受控Provider](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/src/dataset_builder/comparison_provider.py)。
- [实验协议](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/protocol.json) · [原始分组汇总](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/summary.json) · [分析重算脚本](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/analyze_results.py)。重算分析不调用模型。
- [测试记录](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/offline_tests.log)：332项通过；相关代码ruff检查通过。独立代码审查发现的SDK额外字段丢弃、完整性状态、重复统计问题均已修复并复核。
- [完整性报告](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105/integrity_report.json)：1801个历史文件哈希不变，实验产物未检出配置密钥；418次请求参数和正文哈希、四组来源绑定均经复核。

全部实验产物位于 [generator_comparison_20261028_184105](/Users/yuanyu/Documents/ChatGPT/agent_dataset_builder/workspaces/generator_comparison_20261028_184105)。原始输出保留，人工审核状态为PENDING，未冻结、未发布，未修改mini_agent或nanobot历史版本。
