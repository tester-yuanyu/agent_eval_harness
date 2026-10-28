# 完整工具评测能力包

Builder 入口为 `bundle/agent.json`，交付整个 `bundle/` 目录。

包含 7 Module、7 Intent、6 Tool、5 Scope、2 条关键链路、1 条端到端链路。
六个工具均为可执行的 `test_fixture`，不连接生产服务。
生成命令：
`python -m examples.full_tool_fixture.export --output <新目录>`。
普通导出／运行共用 factory：
`examples.full_tool_fixture:create_registry`。

validation_report.json 验证制品；
capability_inventory.json 列出能力和组合解析；
capability_contract_gaps.json 列出尚未实现的业务和评测交付。
生产接入、上下文、确认恢复、JSONL 数据集和人工审核未在本包中完成。
