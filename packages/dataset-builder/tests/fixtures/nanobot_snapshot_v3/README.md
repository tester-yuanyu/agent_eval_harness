# Nanobot 完整能力快照（执行契约修订版）

全量导入入口是本目录的 manifest.json；能力入口是 delivery/bundle/agent.json。
请保持整个目录结构。全部快照与协议 Schema 在 delivery/bundle/。

先读 EXECUTION_CONTRACT.md。execution_contract.json 为静态源码契约，不是执行轨迹；其内容已写入快照。
capability_contract_gaps.json 与 validation_report.json 是 Kit 原报告的同内容副本。
原始 facts、inputs、provenance 在 delivery/，来源文件在 sources/；核验来源时以 sources/ 为 source_root。这是证据文件子集，不是完整运行仓库。
evaluation_specs/ 保留本次 Nanobot SDK 细化规范，沿用 conversation 评测意图，没有新增评分器。异常采集格式仍需消费方实现，不能将 final_response 要求套用到抛异常的分支。
manifest.json 覆盖全包文件摘要（不含自身），最后写入。所有执行/业务能力仍未验证，execution_verified=false。
