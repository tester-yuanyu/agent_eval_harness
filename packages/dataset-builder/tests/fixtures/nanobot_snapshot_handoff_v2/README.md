# Nanobot 完整能力快照交付包

能力入口：`bundle/agent.json`。请将整个目录交给消费方，保持相对路径。

包含全部 35 个快照（含入口）、9 份协议 Schema、manifest.json、
capability_contract_gaps.json、validation_report.json、原始事实与来源记录、
47 份证据源文件、原有 conversation 评测规范和覆盖报告。

先读 `docs/FORMAT_AND_CONTRACT_GAPS.md` 了解格式及未明确声明的业务契约。
沿用原有评测规范；execution_verified=false，不能把结构校验通过解释为业务通过。

如果消费方要求选择单个入口，请选择 `bundle/agent.json`；
如果要求全量生成目录，请选择本目录（包含 manifest.json 和 capability_contract_gaps.json）。
