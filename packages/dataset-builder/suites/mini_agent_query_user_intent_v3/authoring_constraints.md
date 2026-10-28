# 候选生成约束 v3

能力事实只来自 Capability IR。coverage_plan 的 acceptance 是逐槽位的输入选择和验收条件，不增加 Agent 能力。
先生成满足槽位条件的输入，再依据当前输入和契约独立推导预期。若输入与目标槽位冲突，拒绝并重新生成，不得为了匹配标签强行给错误预期。

policies/validation.json 是生成与校验共用策略：parameters 不写 null；READY 至少一个有效参数且 missing_parameters 为空；NEED_CLARIFICATION 的 missing_parameters 必须非空，且只使用契约声明的枚举。非法值不写入期望参数。
批量、OR、未解决同字段多值必须清空参数；明确纠正和否定重述取最终唯一值。
未定义的缺参分支映射不能根据种子或常识补造；此类预期需记录契约缺口，保持待审核。

不要把输入统一写成“帮我查一下”。按槽位要求保持自然语言风格与语序差异，值应为合成数据。严禁复制 seed_catalog 的输入或预期。
确定性谓词只证明有限条件；通过机器校验仍需独立语义初审与人工审核，不能自动冻结。

本版 17 个 NEED_CLARIFICATION 槽位显式声明 oracle_gaps.missing_parameters。对这些槽位只生成用户输入，不请求或猜测任何预期输出。保留输入和契约缺口清单；其余25个槽位继续生成候选。整个计划有缺口时不能创建完整draft或冻结。补齐来源契约后使用新版本重新生成。
