# File Tools v1：已执行实验的发布用证据

- `sources.json`：原始完整结果的路径、字节数、SHA256 和 run ID。
- `*-summary.json`：运行身份、任务计划和汇总。顶层 config 中两个本机路径改为占位符，publication_note 明确记录此展示变换；原始结果没有修改。
- `*-trials.jsonl`：全部 900 条 trial 的正式/诊断评分、理由、时间及状态；省略体积较大的 observation 原文。
- `comparison.html`：独立离线对比页，链接本目录评分 JSONL；不包含完整原始轨迹。
- `comparison.json`：同一冻结任务、评分、Harness 和重复次数的描述性对比。
- `analysis.json`：从保存的文件证据和事件进行失败分类，不修改成绩。
- `clean-install.json`：独立空环境实际安装、pip check 与离线 Demo 验证。

完整原始结果与逐事件证据在仓库本地 artifacts/benchmark/，并导出到受权限控制的 Langfuse 项目。它们未塞入 Git；作品集链接、截图、数据歧义与验收结果见 ../../docs/benchmark/portfolio.md。
