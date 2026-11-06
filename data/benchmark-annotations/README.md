# 独立 Benchmark 注释资产

注释不改写冻结任务或 manifest。每个版本包含 manifest.json、annotations.jsonl、taxonomy.json；绑定源合同、原 loader 身份、任务/引用文件和 manifest 原始字节 Hash。

`file-tools-v2/1.0.0` 为 420 条确定性建议，全部是 **proposed**，没有人工 reviewed 标签。正式分桶默认全部计入未审/未标注；不能用建议桶宣称模型能力覆盖。

当前独立 reference 操作不等于实际工具调用，也不能证明最短依赖深度或恢复分支数。缺少任何必要结构特征时 difficulty=unknown；不以同一模型的失败率倒推标签。完整特征可通过 structural-complexity-v1 规则计算 easy/medium/hard，人工核查需另发不可覆盖的新版本。

```sh
python -m agent_eval_suite benchmark annotations-validate --dataset data/benchmarks/file-tools-v2 --annotations data/benchmark-annotations/file-tools-v2/1.0.0
python -m agent_eval_suite benchmark annotations-build --dataset data/benchmarks/file-tools-v2 --output artifacts/annotations-proposed --version dev-1
```

构建永远输出 proposed；人工审定不得就地修改已发布版本。新版本须更新记录、review_status、record_count 和文件 Hash，通过校验后再用于分析。basis_refs 属于可信端依据，公开报告只投影能力/难度及审查状态。多个能力桶有重叠，不能加总。

版本登记由 Evaluator 的 annotation_versions.json 固定内置发布的 dataset/content Hash。新 proposed 版本构建后状态为 unregistered；正式使用前需追加受信版本登记，analyze/validate 通过 --annotation-registry 显式消费，详见 [本地分析指南](../../docs/benchmark/local-analysis.md)。
