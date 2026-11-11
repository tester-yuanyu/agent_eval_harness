# 改造后 MiniAgent 全量评测集重建

用户授权使用改造后的能力快照和 Builder 重新构建完整评测集。使用独立输出目录，未更改框架实现或旧产物。

交付入口：[新版全量评测集](../../output/mini_agent_full_eval_20261111_v2/README.md)。

- export、generate-full、validate-full 均返回 0；readiness 返回 1，与未满足整包发布门槛一致。
- 854 项定义：365 行为、202 静态契约、287 阻塞；23 个目标，854 个覆盖槽。
- 相比旧版新增 7 项 execution_semantics 待适配义务，详见交付 comparison.json。
- 新 bundle SHA256：`2da8731dd0df1a93a03b7b7be2f4252d87fb3d9be4a485800ea4383c37f54dbe`。
- P0 reference 实测 2/365，通过 OK、EMPTY 两条 query_user_info 路径；363 条行为未绑定。release_ready=false，approval=PENDING。
- 新交付 56 个能力文件及 254 个数据集文件逐项通过 manifest Hash 校验；旧交付同样复核且未改动。
- 使用当前未提交工作树，Git HEAD 与执行命令记录在 build_summary.json、build_steps.json。
- 无真实模型 API、无托管服务；未审批或冻结正式数据。
