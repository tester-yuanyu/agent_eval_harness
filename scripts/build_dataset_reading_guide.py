"""为冻结任务生成中文阅读对照；不修改任务、不进入执行、不调用模型。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "benchmarks"
SOURCES = {
    "file-tools-v1": {
        "tasks.jsonl": "5b3a4feb3f82ba9a6b2c2eeebc9904f0fbb19069cdf46087bfbaa4fb35fe666f",
        "manifest.json": "9393674a3ad6136d1a3a615672f21c8b4fd661ce9273a3939763185cc2b0ccef",
        "quality_report.json": "9fd92e7a02fa43df85174e0957b5142339b559ae4d83f2aaa90bce0a2871060c",
    },
    "file-tools-v2": {
        "tasks.jsonl": "fbaa09dbfc4d820dc1fea379f24bca6d50e518213c109ef3721777d3ad5d4edb",
        "manifest.json": "b96aa678fae622195f89d4ea0e3fddaef67d6a2a4833345d8726dcae788125d6",
        "quality_report.json": "aa60e55e9d29cb40b258982093840dd62f82c906777e0d9e06b2aed18457d5cb",
    },
    "model-decisions-v1": {
        "tasks.jsonl": "54850e53fdc9600b4e4e86650f5ec216d72994c2cd96d6955c67fbf9922382f3",
        "manifest.json": "00ed30285c2c7949423a9401ae5ca582c16cc6889870b095bfb2eecda0e3a8e5",
    },
}
DATASET_NOTES = {
    "file-tools-v1": [
        "300 个实例、80 个任务族；240 个开发集实例、60 个留出集实例。每类任务族的最后五分之一作为留出集，同族参数变体相互关联。",
        "300 条任务指令和 40 条后续指令为中文；300 条英文任务说明提供旁路中文对照。",
        "来源为 AI 辅助编写的合成文件与任务；未完成独立人工审核。确定性参考执行不代表真实 Agent 成绩。",
        "只覆盖本地 UTF-8 文件工具，不覆盖 shell、浏览器、数据库、消息发送或生产写入。",
        "显式要求的格式按精确终态检查；多轮任务检查终态及轮次数，不证明动态用户模拟能力。",
        "质量报告中的参考验证不调用真实模型或 Langfuse，也不收集模型私有思维链。",
    ],
    "file-tools-v2": [
        "420 个实例、104 个任务族；340 个开发集实例、80 个留出集实例。新层各有 12 个任务族，最后 2 族留出；端到端层继承 v1 切分。",
        "360 条 Agent 指令与 75 条后续指令为中文；60 条英文程序模块指令不调用模型，阅读页按实际工具参数解释。",
        "300 个端到端实例沿用 v1 的 80 个任务族；3 条 Markdown 标题指令在 v2 澄清空格要求，预期答案不变。",
        "60 个程序模块实例与 60 个关键链路实例各覆盖 12 个任务族，每族 5 个参数变体。模块测试不衡量 LLM 决策。",
        "来源为 AI 辅助编写的合成文件与私有检查点；未完成独立人工审核。链路使用固定后续指令，只覆盖文件系统。",
        "检查点定义、参考验证与实际运行结果分别记录；本页不提供已完成运行的成绩。",
        "编写校验记录：冲突任务用 WAITING 标记与首轮源文件读取检查提前处理；整数类型负例使用不可转换的 offset。nanobot 会主动把 path 转为字符串。",
    ],
    "model-decisions-v1": [
        "24 个实例、8 个任务族，每族 3 个参数变体；18 个开发集实例来自 6 个操作族，6 个留出集实例来自 2 个放弃调用族。",
        "24 条任务指令与 24 条公开上下文均为中文；任务说明和参考说明提供中文对照。",
        "每例使用真实 nanobot Provider 与文件工具 Schema 请求一次决策，但不执行返回的工具调用；传输层可能重试。",
        "公开上下文是用户提供的固定内容，不冒充之前的工具观测；任务显式区分整文件写入、局部替换和出现位置。",
        "衡量局部工具选择、参数生成与放弃调用，不代表完整规划、记忆、会话管理或执行恢复能力。",
        "来源为 AI 辅助编写；未完成独立人工审核。阅读对照不代表新增模型执行或重新评分。",
    ],
}
MODULE_NAMES = {
    "edit_exact": "精确文本替换",
    "edit_occurrence": "替换指定出现位置",
    "edit_replacement_guard": "替换次数保护",
    "list_nested": "递归列出嵌套目录",
    "read_missing": "读取缺失文件",
    "read_slice": "读取指定行范围",
    "read_text": "读取完整文本",
    "reject_missing_parameter": "拒绝缺少必填参数的调用",
    "reject_parameter_type": "拒绝整数参数类型错误的调用",
    "write_create": "新建文件",
    "write_nested": "写入嵌套目录中的文件",
    "write_overwrite": "覆盖已有文件",
}
REFERENCE_TRANSLATIONS = {
    "Validate by real isolated module execution; no reference Agent result.": "通过真实、隔离的程序模块执行验证；此处没有参考 Agent 运行结果。",
    "No deterministic reference is an observed model decision.": "确定性参考步骤不能视为实际观测到的模型决策。",
}
ERRATA_TRANSLATIONS = {
    "v1 ambiguous whitespace instruction clarified; expected answer unchanged.": "在 v2 中澄清 v1 对空格处理的歧义：去除开头的 Markdown 标记和分隔空格，保留标题内部空格；预期答案不变。",
}


def literal(value: Any) -> str:
    """保留文件名、内容、参数及换行的精确字面量。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def module_steps(task: dict[str, Any]) -> list[str]:
    result = []
    for call in task["module_calls"]:
        name, args = call["name"], call["arguments"]
        path = literal(args["path"])
        if name == "read_file":
            if isinstance(args.get("offset"), dict):
                text = f"调用 read_file 读取 {path}，故意将整数参数 offset 设为 {literal(args['offset'])}，检查参数类型校验。"
            elif "offset" in args:
                text = f"调用 read_file 读取 {path}，从第 {args['offset']} 行开始读取 {args['limit']} 行（从 1 开始编号）。"
            else:
                text = f"调用 read_file 读取 {path} 的完整文本。"
        elif name == "write_file":
            if "content" not in args:
                text = f"调用 write_file，目标为 {path}，故意不提供必填 content 参数，检查缺参处理。"
            else:
                text = f"调用 write_file 向 {path} 写入完整文本 {literal(args['content'])}；保留原始字符与换行。"
        elif name == "edit_file":
            text = f"调用 edit_file，在 {path} 中将 {literal(args['old_text'])} 替换为 {literal(args['new_text'])}。"
            if "occurrence" in args:
                text += f"仅选择第 {args['occurrence']} 次出现。"
            if "expected_replacements" in args:
                text += f"设置 expected_replacements={args['expected_replacements']}，核验替换次数保护。"
        elif name == "list_dir":
            text = f"调用 list_dir 列出 {path}，recursive={literal(args.get('recursive', False))}，包含子目录。"
        else:
            raise ValueError(f"尚未提供工具调用的中文解释：{name}")
        result.append(text)
    return result


def reading(task: dict[str, Any], dataset: str, sha: str) -> dict[str, Any]:
    original = task["description"]
    mode = task.get("execution_mode", "agent")
    steps: list[str] = []
    prompt = task["prompt"]
    if mode == "module":
        family = task["family"].split("/")[-1]
        variant = int(task["id"].split("/")[-1])
        prompt = f"执行 nanobot ToolRegistry 的「{MODULE_NAMES[family]}」固定边界测试，参数变体 {variant}。"
        steps = module_steps(task)
        prompt += "\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
        assert (
            original
            == "Real deterministic nanobot module boundary; no LLM decision is measured."
        )
        description = (
            "通过真实、确定性的 nanobot 程序模块边界进行测试；不衡量 LLM 决策。"
        )
    elif original.startswith("Synthetic "):
        match = re.fullmatch(
            r"Synthetic ([a-z_]+); independently variable fixture (\d+)/(\d+)\.",
            original,
        )
        if not match:
            raise ValueError(f"未识别的冻结说明：{original}")
        assert task["family"].endswith("/" + match[1])
        description = f"合成文件任务；本任务族第 {match[2]}/{match[3]} 个参数变体，使用分别设置的输入文件。变体不等同于独立业务能力。"
    elif (
        original
        == "Fixed critical-chain checkpoints; equivalent edit/write paths allowed unless explicitly requested."
    ):
        description = "使用固定关键链路检查点；除非任务明确要求，否则允许等价的编辑或整文件写入路径。"
    elif (
        original
        == "One model next-action decision from public context and real tool schemas; no tool execution."
    ):
        description = "基于公开上下文和真实工具 Schema，观测模型的一次下一步行动决策；不执行工具调用。"
    else:
        raise ValueError(f"未识别的冻结说明：{original}")
    summary = prompt
    for i, followup in enumerate(task["followups"], 2):
        summary += f"\n第 {i} 轮：{followup}"
    return {
        "schema_version": "dataset-reading-zh-CN-v1",
        "reading_only": True,
        "dataset_id": dataset,
        "case_id": task["id"],
        "source_tasks_sha256": sha,
        "family": task["family"],
        "execution_mode": mode,
        "description_zh": description,
        "task_summary_zh": summary,
        "prompt_zh": prompt,
        "prompt_is_translation": mode == "module",
        "followups_zh": task["followups"],
        "decision_context_zh": task.get("decision_context"),
        "module_steps_zh": steps,
        "reference_descriptions_zh": [
            {
                "reference_index": i,
                "description_zh": REFERENCE_TRANSLATIONS[r["description"]],
            }
            for i, r in enumerate(task["reference"])
            if "description" in r
        ],
        "errata_zh": ERRATA_TRANSLATIONS[task["errata"]]
        if task.get("errata")
        else None,
    }


HTML = r"""<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>冻结评测集 · 中文逐条阅读</title>
<style>
:root{color-scheme:light;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:#172b36;background:#f4f6f4}*{box-sizing:border-box}body{margin:0}header{background:#153e39;color:#f3faf5;padding:42px max(6vw,20px) 30px}header p{max-width:950px;line-height:1.8;color:#d9e9e2}h1{font-size:clamp(25px,4vw,38px);font-weight:650;margin:8px 0 15px}.tag{letter-spacing:.12em;font-size:12px;color:#c2d9ce}.stats{display:flex;gap:36px;flex-wrap:wrap;margin-top:24px}.stats strong{font-size:28px;display:block}.stats span{font-size:13px;color:#d3e6da}main{max-width:1250px;margin:auto;padding:26px 22px 60px}.notice{border-left:4px solid #a67738;background:#fff9ec;padding:14px 18px;line-height:1.75}.notice a{color:#705020}.filters{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}.filters label{font-size:13px;font-weight:600;display:grid;gap:7px}.filters label:last-child{flex:1;min-width:230px}input,select,button{font:inherit;border:1px solid #b7c9c2;border-radius:6px;padding:11px;background:white;color:#183d35}button{cursor:pointer}button:hover{background:#e8f2eb}input:focus,select:focus,button:focus{outline:2px solid #2a7965;outline-offset:2px}.metadata{background:#e7eee8;padding:17px 22px;border-radius:8px;margin-bottom:20px;line-height:1.8}.metadata ul{padding-left:20px}.metadata h2{font-size:17px;margin:0}.count{color:#53695e;font-size:14px;margin-bottom:13px}.card{background:white;border:1px solid #d7e1da;border-radius:10px;margin:12px 0;padding:20px}.card h2{font-size:16px;line-height:1.7;margin:10px 0}.pill{font-size:12px;background:#e8f0e9;border-radius:30px;padding:5px 10px;margin-right:7px;display:inline-block}.case-id{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;color:#577566;overflow-wrap:anywhere;margin-top:12px}.description{font-size:14px;line-height:1.75;color:#4e6257}.label{font-size:13px;font-weight:650;margin:18px 0 8px}.text{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;background:#f5f8f4;border-radius:5px;padding:14px;font-size:14px}details{border-top:1px solid #e3eae4;margin-top:16px;padding-top:13px}summary{cursor:pointer;font-size:13px;color:#315c4c}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f2;padding:13px;font-size:12px;line-height:1.65}.sha{font-size:11px;color:#718177;overflow-wrap:anywhere;line-height:1.6}.more{display:block;margin:25px auto;min-width:200px}.empty{text-align:center;padding:50px;color:#53695e}a{color:#235b47}footer{font-size:12px;line-height:1.8;color:#61736a;margin-top:30px}@media(max-width:600px){header{padding-top:28px}.stats{gap:22px}.stats strong{font-size:24px}main{padding:18px 12px 40px}.card{padding:15px}.filters label{flex:1;min-width:130px}}
</style>
<header><div class="tag">AGENT EVAL SUITE / 阅读材料</div><h1>冻结评测集 · 中文逐条阅读</h1><p>把任务意图、执行边界和来源说明放在一起阅读。中文说明与历史任务分开保存，源任务、文件内容、评分契约及成绩均保持原样。</p><div class="stats"><div><strong>744</strong><span>跨 3 个版本的任务记录</span></div><div><strong>684</strong><span>中文模型／Agent 任务指令</span></div><div><strong>60</strong><span>程序模块指令中文对照</span></div></div></header>
<main><div class="notice">本页仅供阅读，不是可执行数据集或成绩报告。v2 包含继承自 v1 的 300 条记录，744 不能理解为独立问题数。英文代码、参数名、路径、文件内容及匹配标记是精确字面量，保留原文。<a href="dataset-language.md">查看语言审计与冻结规则</a></div>
<div class="filters"><label>数据集<select id="dataset"><option value="">全部 3 个数据集</option></select></label><label>执行类型<select id="mode"><option value="">全部执行类型</option><option value="agent">Agent 任务</option><option value="module">程序模块（无模型）</option><option value="decision">独立模型决策</option></select></label><label>按任务或文件搜索<input id="search" type="search" placeholder="例如：替换、input.txt、read_range" autocomplete="off"></label></div>
<section id="metadata" class="metadata" aria-label="数据集来源与限制"></section><p class="count" id="count" aria-live="polite"></p><section id="cards" aria-label="逐条任务"></section><button class="more" id="more">再显示 30 条</button><footer>通过原始任务 ID 和 tasks.jsonl 的 SHA-256 关联冻结证据。中文对照不是新增语言版本的执行成绩；本页不请求任何网络服务。</footer></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent);
const names={agent:'Agent 任务',module:'程序模块 · 不调用模型',decision:'独立模型决策'};
const levels={e2e:'端到端',chain:'关键链路',module:'模块'};
const splits={dev:'开发集',holdout:'留出集'};
const el=id=>document.getElementById(id);
const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
for(const d of data.datasets)el('dataset').appendChild(Object.assign(document.createElement('option'),{value:d.id,textContent:d.id}));
let limit=30;
function block(parent,label,text){if(!text)return;parent.appendChild(node('div','label',label));parent.appendChild(node('div','text',text))}
function details(parent,title,text){const d=node('details');d.appendChild(node('summary','',title));d.appendChild(node('pre','',text));parent.appendChild(d)}
function render(){const dataset=el('dataset').value,mode=el('mode').value,q=el('search').value.trim().toLowerCase();
const rows=data.rows.filter(r=>(!dataset||r.dataset_id===dataset)&&(!mode||r.execution_mode===mode)&&(!q||r.search.includes(q)));
el('metadata').replaceChildren();const ds=data.datasets.filter(d=>!dataset||d.id===dataset);
for(const d of ds){el('metadata').appendChild(node('h2','',d.id));const list=node('ul');for(const s of d.notes)list.appendChild(node('li','',s));el('metadata').appendChild(list);if(dataset){const a=node('a','','打开数据集说明');a.href='../data/benchmarks/'+d.id+'/README.md';el('metadata').appendChild(a)}}
el('count').textContent=`找到 ${rows.length} 条记录，已显示 ${Math.min(limit,rows.length)} 条。按源文件顺序呈现，不表示运行先后或分数排名。`;
el('cards').replaceChildren();
for(const r of rows.slice(0,limit)){const c=node('article','card');c.appendChild(node('span','pill',r.dataset_id));c.appendChild(node('span','pill',names[r.execution_mode]));c.appendChild(node('span','pill',levels[r.level]+' / '+splits[r.split]));c.appendChild(node('div','case-id',r.case_id));c.appendChild(node('h2','',r.description_zh));
block(c,r.prompt_is_translation?'程序模块指令与实际参数的中文解释':'原始中文任务指令',r.prompt_zh);if(r.decision_context_zh)block(c,'公开上下文（原始中文）',r.decision_context_zh);for(let i=0;i<r.followups_zh.length;i++)block(c,`第 ${i+2} 轮指令（原始中文）`,r.followups_zh[i]);if(r.errata_zh)block(c,'勘误说明',r.errata_zh);
if(r.reference_descriptions_zh.length)block(c,'参考说明（不是 Agent 运行成绩）',r.reference_descriptions_zh.map(x=>x.description_zh).join('\n'));
details(c,'初始文件原始内容（精确字面量，不作翻译）',JSON.stringify(r.fixtures,null,2));if(r.module_calls)details(c,'固定程序模块调用（代码参数）',JSON.stringify(r.module_calls,null,2));details(c,'冻结英文说明原文（中文对照的来源）',JSON.stringify(r.original_text,null,2));c.appendChild(node('p','sha','源 tasks.jsonl SHA-256：'+r.source_tasks_sha256));el('cards').appendChild(c)}
if(!rows.length)el('cards').appendChild(node('p','empty','没有匹配记录，请调整数据集、执行类型或关键词。'));el('more').hidden=rows.length<=limit;
}
for(const id of ['dataset','mode','search'])el(id).addEventListener(id==='search'?'input':'change',()=>{limit=30;render()});el('more').addEventListener('click',()=>{limit+=30;render()});render();
</script></html>
"""


def outputs() -> dict[Path, bytes]:
    result: dict[Path, bytes] = {}
    payload: dict[str, Any] = {"datasets": [], "rows": []}
    for dataset, sources in SOURCES.items():
        directory = DATA / dataset
        for filename, expected in sources.items():
            actual = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
            if actual != expected:
                raise ValueError(
                    f"冻结来源发生变化，停止生成中文对照：{dataset}/{filename}"
                )
        manifest = json.loads((directory / "manifest.json").read_text())
        sha = sources["tasks.jsonl"]
        assert manifest["tasks_sha256"] == sha
        tasks = [
            json.loads(line)
            for line in (directory / "tasks.jsonl").read_text().splitlines()
        ]
        assert len(tasks) == manifest["case_count"]
        assert len({t["id"] for t in tasks}) == len(tasks)
        translated = [reading(task, dataset, sha) for task in tasks]
        result[directory / "reading.zh-CN.jsonl"] = "".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in translated
        ).encode()
        payload["datasets"].append({"id": dataset, "notes": DATASET_NOTES[dataset]})
        for task, row in zip(tasks, translated, strict=True):
            payload["rows"].append(
                {
                    **row,
                    "level": task.get("evaluation_level", "e2e"),
                    "split": task["split"],
                    "fixtures": task["fixtures"],
                    "module_calls": task.get("module_calls"),
                    "original_text": {
                        "description": task["description"],
                        **(
                            {"prompt": task["prompt"]}
                            if row["prompt_is_translation"]
                            else {}
                        ),
                        "reference_descriptions": [
                            r["description"]
                            for r in task["reference"]
                            if "description" in r
                        ],
                        **({"errata": task["errata"]} if task.get("errata") else {}),
                    },
                    "search": " ".join(
                        [
                            task["id"],
                            task["family"],
                            row["task_summary_zh"],
                            task.get("decision_context", ""),
                        ]
                    ).lower(),
                }
            )
    assert len(payload["rows"]) == 744
    # JSON 数据内的尖括号转义，避免文件内容被 HTML 当成标签执行。
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    result[ROOT / "docs" / "dataset-reading.html"] = HTML.replace(
        "__DATA__", serialized
    ).encode()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="只核验旁路阅读资产与冻结来源，不写文件"
    )
    args = parser.parse_args()
    expected = outputs()
    for path, content in expected.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise SystemExit(
                    f"中文阅读资产缺失或需要更新：{path.relative_to(ROOT)}"
                )
        else:
            path.write_bytes(content)
    action = "核验通过" if args.check else "已生成"
    print(
        f"{action}：744 条中文阅读对照、3 份 JSONL、1 个离线 HTML；8 个冻结源文件 SHA-256 一致。"
    )


if __name__ == "__main__":
    main()
