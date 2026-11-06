# 保存证据的本地分析（M2）

`benchmark analyze` 只读本地保存结果，输出新的 `analysis.json`、`analysis.md`、`analysis.html` 和 `provenance.json`。它不执行 Agent、Judge 或模型，不连接 Langfuse，不覆盖历史 `results.json`、summary 或旧报告。Inspect 仍负责执行与日志；正式判定沿用保存的 DeepEval 确定性评分结果。

## 使用

在已完成 core 安装的仓库根目录运行：

```sh
python -m agent_eval_suite benchmark analyze \
  --run "$RUN_DIR" \
  --dataset data/benchmarks/file-tools-v2 \
  --annotations data/benchmark-annotations/file-tools-v2/1.0.0 \
  --output "$NEW_OUTPUT_DIR" --k 1 3 5
```

数据集路径显式提供，支持现有 file-tools v1/v2、model-decisions、nanobot-core 与 provider-tasks 合同；每个入口仍调用原严格 loader。旧 `report`、`compare` 的接口与返回格式保持。

正式复评结果必须附完整来源链：重复提供 `--source-artifact "$SOURCE_RESULTS"`。工具校验原始字节 Hash、identity、source_trial_sha256、source_assessment、计划与 observation；复评只能改变评分身份与 assessment，不能改写执行配置、增删试次或变成新执行。不跟随来源记录中的绝对路径或 URL，循环/超过 64 层的链拒绝。

`--judge-source "$JUDGE_DIR"` 附加诊断。Judge 不能作为主 `--run`，其选择子集与 Judge repeat 不缩小 Agent 总体、不增加执行次数。Judge 自己的 planned/observed/missing/scored/error 覆盖单列，含部分 SCORED 与 ERROR 的试次可同时计入两种诊断状态，不能相加当试次数。

## 计划总体与 pass^k

四层 module、decision、chain、e2e 分开；没有跨层总体成功率。分母来自冻结任务选择和原始执行计划，未保存 trial 生成 MISSING 占位。planned、completed、valid、INVALID、INCONCLUSIVE、MISSING 分开保存。报告同时保留 PASS/计划、PASS/有效；有效 INCONCLUSIVE 是非成功。

每题计划 n 次、c 次正式 PASS，`pass_hat_k = comb(c,k)/comb(n,k)`，c<k 为 0。任务实例等权 micro 和任务族等权 macro 并列，不将同族变体当统计独立样本。

- k 为严格正整数，默认 1、3、5；k>n 为 `insufficient_trials`，主值 null。
- 某层计划总体含 MISSING 或 INVALID，该层主值为 `unavailable_incomplete_population`，不筛掉难以完成的任务。
- `all_trials_pass_rate` 保留所有计划 trial 均 PASS 的保守口径；缺失试次不能满足此条件。
- 未提供重复协议时标 `descriptive_not_verified_independent`。`--repeat-protocol "$PROTOCOL_JSON"` 需要 `independent_trials: true` 以及非空 `environment_reset`、`randomness` 文本；此时仅标 `declared_independent`，工具不宣称已核验独立性。报告只保存协议摘要，不公开原文。
- reference/offline 演示标 `framework_demo`，pass^k 主值不可用，不作为 Agent 能力成绩。

不自动拼接多个 run，不给未经设计的置信区间、因果结论或统计显著性结论。

## 用量、效率与输出长度

逐层逐角色报告 Agent、Judge、用户模拟器。角色来自显式事件标记；没有用户模拟器事件时不会虚构其费用。Judge 使用附加诊断资产的独立计划，缺失试次仍进入它的覆盖分母。

每字段分别披露 `known_trials/planned_trials` 和 `complete_tasks/planned_tasks`，后者要求该任务全部计划 trial 的字段完整。支持 input/output/total/cached token、cost_usd、generation_calls、tool_calls、latency_seconds、最终可见回复字符数。

| 字段 | 含义 |
| --- | --- |
| known_subtotal / mean_known | 已知字段小计 / 已知样本均值，不是总体总量 |
| valid_mean_known | 有效样本中已知字段的均值，属于条件总体 |
| successful_mean | 所有成功 trial 的字段均已知时，成功样本条件均值 |
| per_success | 全部计划尝试成本 / 正式 PASS 数，仅在完整计划与该字段全部已知时可用 |
| total | 字段覆盖全部计划 trial 时的总量；否则 null |

费用 10、20、30，前两次 PASS 时，成功样本平均费用为 15，而总尝试费用/成功数为 30。零成功、空总体、缺失用量不伪造 0。input/output 别名只计一次，冲突别名、布尔、负值和非有限数字拒绝；不从其他字段推导 total/cached/cost。完整事件证据证明零调用时才可计零；Judge 请求数未知的 ERROR 不能计零调用/零成本。费用来自保存值，不按当前价格估算。不同 latency scope 分栏，不混合求均值。

输出长度只作描述，不默认越短越好，也不与成功率、费用拼成任意加权总分。

## 失败与注释

失败规则 `failure-rules-v1` 读取结构化评分检查和错误代码，保留 domain、primary、secondary、rule_version 与证据 JSON Pointer。未知原因仍为 unknown；广义 task_success 失败不能推断具体根因。工具报错后正式 PASS 只记 recovered_error 诊断，Judge ERROR 不改变正式 verdict。报告通过执行 run/identity、case/trial、JSON Pointer 定位原始证据。

独立注释不改冻结任务。每个版本绑定 manifest 原始字节、任务/manifest 声明文件 Hash、原有 dataset identity、taxonomy 和注释文件 Hash。旧运行若只保存解析后的 manifest 身份，不能追认当年 manifest 字节；`historical_manifest_bytes_verified` 如实标 false。

首版 file-tools-v2 共 420 条 **proposed**。能力标签仅来自明确结构证据，不推断并行、schema 变换或拒绝能力。reference 操作不等于实际调用数/最小依赖图，缺少结构特征的难度为 **unknown**。仅 reviewed 注释进入正式桶，当前版本因此全部计入未审/未标注；多标签桶不可加总。

```sh
python -m agent_eval_suite benchmark annotations-validate \
  --dataset data/benchmarks/file-tools-v2 \
  --annotations data/benchmark-annotations/file-tools-v2/1.0.0
python -m agent_eval_suite benchmark annotations-build \
  --dataset data/benchmarks/file-tools-v2 \
  --output "$NEW_ANNOTATION_DIR" --version 1.1.0
```

build 只建议 proposed，不代替人工审核；已有目录拒绝覆盖。人工审核应发布新不可变版本，不原地编辑 1.0.0。报告不输出私有 basis_refs 或结构依据文本。

## 探索性与受控对比

`--compare-with "$BASELINE_RUN"` 将两次保存总体并列，默认 `exploratory/descriptive_only`；控制项差异用字段名和内容摘要展示，不复制模型地址、prompt、路径或配置原文。数据集不同时还需显式 `--comparison-dataset "$BASELINE_DATASET"`。两份来源链都必须显式提供，不合并分母。同一 execution 的重评分标 `scoring_only`，新增执行数为 0。

受控资格另需 `--experiment-spec "$SPEC_JSON"`。在实验前准备声明，工具只能检验字段一致性，不能证明登记时间。最小示例：

```json
{
  "control_fields": ["dataset", "scoring", "selection", "repeats", "repeat_protocol", "layers", "harness", "environment", "tools", "prompt", "generation_config", "other_identity"],
  "variable_fields": ["model"]
}
```

仅 model/runtime 可作为变量，所有其他字段必须固定且可验证。历史证据没有工具、prompt、环境或重复协议身份时，标 `unknown_controls`，保留描述性比较；不把缺失值相等当作受控。未列为变量的 model/runtime 同样按控制项检查。控制不满足时不会给受控差值。即便 compatible，也不自动推导因果或显著性。

HTML 为静态本地文件，无外部脚本/资源；Markdown/HTML 由同一 analysis JSON 渲染。复现命令只含环境变量占位符与摘要，不嵌入任意任务文本或凭据，不自动执行。新报告有独立源码/策略/来源/注释身份；改变分析代码不重写历史执行身份。

人工校准、鲁棒性新数据、Langfuse 新分析导出属 M3；真实重复实验、人工独立验证与托管交付属 M4，均不在本批完成声明内。
