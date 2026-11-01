# Judge 人工校准诊断报告

状态：awaiting_independent_human_labels。阈值状态：requires_independent_validation。
此报告仅描述一致性；阈值未验证，人工来源与独立性仍需审核。

候选阈值：0.8；版本：exploratory-example-not-validated。
未标注与 Judge 缺分不计为一致或不一致；有标签但无可配对分数时，一致性仍为未知。

## 分母、覆盖与分维度统计

总体及每个维度独立计算分母。误放率 = 误放 / 配对人工负例；误杀率 = 误杀 / 配对人工正例。

| 维度 | 总数 | 已标注 | 配对 | 标注覆盖 | 配对覆盖 | 一致率 | MAE | 误放 / 负例 | 误杀 / 正例 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 总体 | 36 | 0 | 0 | 0 | 0 | 未知（无可用分母） | 未知（无可用分母） | 0 / 0（未知（无可用分母）） | 0 / 0（未知（无可用分母）） |
| action_appropriateness | 12 | 0 | 0 | 0 | 0 | 未知（无可用分母） | 未知（无可用分母） | 0 / 0（未知（无可用分母）） | 0 / 0（未知（无可用分母）） |
| recovery_appropriateness | 12 | 0 | 0 | 0 | 0 | 未知（无可用分母） | 未知（无可用分母） | 0 / 0（未知（无可用分母）） | 0 / 0（未知（无可用分母）） |
| response_groundedness | 12 | 0 | 0 | 0 | 0 | 未知（无可用分母） | 未知（无可用分母） | 0 / 0（未知（无可用分母）） | 0 / 0（未知（无可用分母）） |

## 混淆矩阵

行是人工判断，列是 Judge 判断；下表列出四格计数。

| 维度 | 人工通过 / Judge通过 | 人工拒绝 / Judge通过（误放） | 人工拒绝 / Judge拒绝 | 人工通过 / Judge拒绝（误杀） |
| --- | ---: | ---: | ---: | ---: |
| 总体 | 0 | 0 | 0 | 0 |
| action_appropriateness | 0 | 0 | 0 | 0 |
| recovery_appropriateness | 0 | 0 | 0 | 0 |
| response_groundedness | 0 | 0 | 0 | 0 |

## 缺失与分歧引用

未标注 record_id：\[   "0047e7eff2c68004799cab124cdff49d",   "00638a72587bdbfcd04d626f3e9897df",   "0098960a4dcdc87e044fcfba0c454e7f",   "00d56c15e572151831a97a69215a6fbe",   "00d761a8f2b7b2f7d6d346b27dac0b58",   "00facb46689ac882e5d94b3792caa6d5",   "015043ddad7e367054f9b65837f9d236",   "0174444cc89ba7a6a92265213e04e8bd",   "01c8c34ed086d7a40dfdfdea853afe7c",   "030a554814ff2b8e944fe1a500b8b076",   "030b99f06dc0a3de112c57764af88de8",   "03171e0da60a8d80faf9d2b217bf82fc",   "032266c62e9bfd562ae15edc410dfadd",   "033e85ce9b00043224ad05326a318724",   "036680a8a6bb4340d0810740107419d7",   "03a36a0a13e3ee97b200ad80c5117ea2",   "03a4cf9976b6be21b322d3cf61a71c9e",   "03d6a073cab63b151653106482e5ad35",   "04e5cd269b2443bddf278c15d7ce32d0",   "08e4183ed058996d10f6a717dfa508b7",   "09024d680bb1baccba029516ac8c12bf",   "0a7a29138eb6ff0e7bac98a54ccb0aa4",   "0a9f34340ee72df07fc21b2516e89bc7",   "0b1db530f7dfce83ff948b6ea0868d4e",   "0b2547d6bfaf53bb8ca8f92fb4d73fe6",   "0bca3876540e46d68020005d4141f88c",   "0c9d590fa3e3b6a9204ed492699f7b52",   "1852d5aa83184c7723971d8ab7a0a494",   "35565b96bf20d2a4f2588d7958be918a",   "4237498b74906b34eb22c36aefc41bd4",   "53f4e299f4e9ff7d07f9a65ede828e18",   "5d65f089285c6c161c7ebab93d35ec34",   "5efa302fca7c09c2fb5d26e1e04d1844",   "60bb143f0bfa6ca5daad54e4a4404b2a",   "7e869abb792b7c7672ad7f3de83387e7",   "7ed7ba92386ae2d27b1e63c8977f3dbe" \]

已标注但 Judge 缺分 record_id：\[\]

无已配对的阈值判断分歧；未标注或未配对不代表一致。

## 可复核输入摘要

source_summary：{   "sha256": "da4f62e058b14f9f893146434ed17d2581f8290984f534796c262ce4856112ef",   "hash_encoding": "utf-8 Python JSON; ensure_ascii=false; sort_keys=true; compact; allow_nan=true",   "population_count": 36,   "record_ids": \[     "0047e7eff2c68004799cab124cdff49d",     "00638a72587bdbfcd04d626f3e9897df",     "0098960a4dcdc87e044fcfba0c454e7f",     "00d56c15e572151831a97a69215a6fbe",     "00d761a8f2b7b2f7d6d346b27dac0b58",     "00facb46689ac882e5d94b3792caa6d5",     "015043ddad7e367054f9b65837f9d236",     "0174444cc89ba7a6a92265213e04e8bd",     "01c8c34ed086d7a40dfdfdea853afe7c",     "030a554814ff2b8e944fe1a500b8b076",     "030b99f06dc0a3de112c57764af88de8",     "03171e0da60a8d80faf9d2b217bf82fc",     "032266c62e9bfd562ae15edc410dfadd",     "033e85ce9b00043224ad05326a318724",     "036680a8a6bb4340d0810740107419d7",     "03a36a0a13e3ee97b200ad80c5117ea2",     "03a4cf9976b6be21b322d3cf61a71c9e",     "03d6a073cab63b151653106482e5ad35",     "04e5cd269b2443bddf278c15d7ce32d0",     "08e4183ed058996d10f6a717dfa508b7",     "09024d680bb1baccba029516ac8c12bf",     "0a7a29138eb6ff0e7bac98a54ccb0aa4",     "0a9f34340ee72df07fc21b2516e89bc7",     "0b1db530f7dfce83ff948b6ea0868d4e",     "0b2547d6bfaf53bb8ca8f92fb4d73fe6",     "0bca3876540e46d68020005d4141f88c",     "0c9d590fa3e3b6a9204ed492699f7b52",     "1852d5aa83184c7723971d8ab7a0a494",     "35565b96bf20d2a4f2588d7958be918a",     "4237498b74906b34eb22c36aefc41bd4",     "53f4e299f4e9ff7d07f9a65ede828e18",     "5d65f089285c6c161c7ebab93d35ec34",     "5efa302fca7c09c2fb5d26e1e04d1844",     "60bb143f0bfa6ca5daad54e4a4404b2a",     "7e869abb792b7c7672ad7f3de83387e7",     "7ed7ba92386ae2d27b1e63c8977f3dbe"   \],   "run_id": null }

labels_summary：{   "sha256": "be6980794492c1b29152772b4fe0c4e93e33552faa105b55d6bc93836415cf49",   "hash_encoding": "utf-8 Python JSON; ensure_ascii=false; sort_keys=true; compact; allow_nan=true",   "submitted_count": 36,   "completed_count": 0,   "completed_record_ids": \[\],   "annotators": \[\],   "provenance_status": "self_declared_requires_review" }

- 人工标注来源由填写者声明，仍需审核标注者身份与独立性。
- 这些标签用于描述一致性；阈值验证还需另设独立留出的人工标注样本。
- 缺失的 Judge 分数或人工标签均不计为一致或不一致。
