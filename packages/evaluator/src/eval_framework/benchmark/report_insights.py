"""从已保存证据派生报告解释；不重评分，不依赖当前 Agent 实现。"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

LABELS = {
    "NEED_CONFIRMATION": "需要确认（写操作）",
    "NEED_CLARIFICATION": "要求补充参数",
    "ASK_CONFIRMATION": "请求用户确认",
    "ASK_USER": "向用户追问",
    "READY": "可以执行",
    "SUCCESS": "任务完成",
    "CALL_TOOL": "调用工具",
    "REJECTED": "拒绝执行",
    "REJECT": "拒绝请求",
    "status_match": "任务状态",
    "next_action_match": "后续动作",
    "missing_params_match": "待补充参数",
    "params_match": "参数",
    "grant_count": "发放记录数",
    "total_quantity": "发放总数量",
    "final_state_match": "最终业务状态",
    "turns_match": "逐轮结果",
    "confirmation_accepted": "已接受用户确认",
    "tool_args_match": "工具调用参数",
    "no_duplicate_side_effect": "实际写入次数",
    "num": "数量（num）",
    "duration_days": "有效期天数（duration_days）",
    "gift_id": "礼物 ID",
    "user_id": "用户 ID",
    "environment": "环境",
    "fixture_version": "测试初态版本",
    "grants": "发放记录",
}


def readable(value: object) -> str:
    if isinstance(value, str):
        translated = LABELS.get(value, value)
        return re.sub(
            r"turn (\d+): (status|state) differs",
            lambda m: (
                f"第 {int(m[1]) + 1} 轮"
                f"{'状态' if m[2] == 'status' else '业务终态'}与期望不一致"
            ),
            translated,
        )
    if isinstance(value, dict):
        return "；".join(f"{LABELS.get(k, k)}：{readable(v)}" for k, v in value.items())
    if isinstance(value, list):
        return "、".join(readable(item) for item in value) or "无"
    if value is None:
        return "未提供"
    return str(value)


def comparisons(row: dict) -> list[dict]:
    result = []
    for metric in row["assessment"].get("metrics", []):
        if metric.get("success") is not False or not metric.get("formal", True):
            continue
        reason = metric.get("reason", "")
        try:
            parsed = json.loads(reason)
        except (ValueError, TypeError):
            parsed = None
        result.append(
            {
                "metric": LABELS.get(metric.get("name"), metric.get("name", "评分")),
                "expected": readable(parsed["expected"])
                if isinstance(parsed, dict) and "expected" in parsed
                else "见评分规则",
                "actual": readable(parsed["actual"])
                if isinstance(parsed, dict) and "actual" in parsed
                else readable(str(reason)),
            }
        )
    return result


def load_contracts(run: dict) -> tuple[dict, list[str]]:
    """仅加载运行身份绑定的本地参考契约；缺失时不猜测字段定义。"""
    bundle = run.get("config", {}).get("capability_bundle")
    if not bundle or urlsplit(str(bundle)).scheme:
        return {}, []
    root = Path(bundle).resolve()
    contracts, warnings = {}, []
    for name, expected in (
        run.get("identity", {}).get("dataset", {}).get("files", {}).items()
    ):
        if not name.startswith("capability_bundle/intents/") or not name.endswith(
            ".json"
        ):
            continue
        path = (root / name.removeprefix("capability_bundle/")).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            warnings.append(f"参考契约不可用：{name}；相关归因降级为待核实。")
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            warnings.append(f"参考契约 Hash 不匹配：{name}；不用于归因。")
            continue
        contract = json.loads(raw)
        contract["report_source"] = {"path": name, "sha256": expected}
        contracts[contract["capability_id"]] = contract
    return contracts, warnings


def _candidate(event: dict) -> dict:
    try:
        value = json.loads(event.get("output", {}).get("content", ""))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError, AttributeError):
        return {}


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item.get("text", "") for item in content if isinstance(item, dict)
        )
    return ""


def schema_advice(mapping: dict, gap: bool) -> str:
    advice = (
        "第一步：补齐被测 Agent 意图请求中的具体参数 Schema，"
        "与执行校验使用同源契约；检查实际请求确实包含标准字段，再验证输出。"
        if gap
        else "先核对被测 Agent 实际收到的参数 Schema 与校验契约是否一致。"
    )
    if mapping:
        advice += (
            (
                "第二步：仅在需要兼容旧表达时考虑别名兜底；它不能替代 Schema 注入。"
                if gap
                else "确认 Schema 传递无缺口后，再考虑别名兼容。"
            )
            + "配置声明的候选别名为 "
            + "、".join(f"{a}→{b}" for a, b in sorted(mapping.items()))
            + "；如决定兼容，应在 Agent 校验前显式映射，冲突时拒绝并追问，"
            "继续校验类型和范围。"
        )
    else:
        advice += "没有可核验的别名配置，不推断未知字段与标准字段语义等价。"
    return (
        advice
        + "先用保存候选离线回归，再验证确认与成功写入；评测框架不改写输出或正式评分。"
    )


def diagnose(row: dict, contracts: dict, *, aliases: dict | None = None) -> list[dict]:
    """只陈述事件可证明的原因，不把模型候选状态当作业务正确性。"""
    if row["assessment"]["verdict"] == "PASS":
        return []
    events = row.get("observation", {}).get("events", [])
    generations = [e for e in events if e.get("type") == "generation"]
    findings = []
    for event in generations:
        request = event.get("input", {})
        if not isinstance(request, dict):
            # Saved Judge prompts are plain text, not Agent conversation evidence.
            continue
        candidate = _candidate(event)
        params = candidate.get("parameters", {})
        if not isinstance(params, dict):
            continue
        for invalid in events:
            payload = invalid.get("input", {})
            if (
                invalid.get("name") != "intent_parameter_validation_failed"
                or invalid.get("turn") != event.get("turn")
                or not event.get("turn")
                or payload.get("intent") != candidate.get("intent")
            ):
                continue
            fields = [field for field in payload.get("fields", []) if field in params]
            if not fields:
                continue
            values = "、".join(f"{field}={readable(params[field])}" for field in fields)
            contract = contracts.get(candidate.get("intent"), {})
            schema = contract.get("parameters_schema", {})
            unknown = [
                field for field in fields if field not in schema.get("properties", {})
            ]
            proven = (
                bool(contract)
                and schema.get("additionalProperties") is False
                and bool(unknown)
            )
            description = (
                f"第 {event['turn']} 轮模型已输出 {values}，随后执行校验拒绝这些字段。"
            )
            if proven:
                description += (
                    f"其中 {readable(unknown)} 是参考契约未声明的字段；契约可用字段为 "
                    f"{readable(sorted(schema['properties']))}。这是模型输出与契约不一致，不能表述为用户没有提供数值。"
                    "参考契约与当前运行契约的实现一致性仍需单独验证。"
                )
            else:
                description += (
                    "根因待核实：仅凭拒绝事件不能区分字段名、类型、"
                    "取值范围或校验实现问题。"
                )
            intent_aliases = (aliases or {}).get(candidate.get("intent"), {})
            mapping = (
                {
                    f: intent_aliases[f]
                    for f in unknown
                    if f in intent_aliases
                    and intent_aliases[f] in schema.get("properties", {})
                }
                if proven
                else {}
            )
            gap = _open_parameter_schema(event, list(mapping.values()))
            findings.append(
                {
                    "fields": {f: params[f] for f in fields},
                    "aliases": mapping,
                    "prompt_contract_gap": gap,
                    "short": f"第 {event['turn']} 轮："
                    + "、".join(
                        f"{f}={readable(params[f])}"
                        + (f"（标准字段 {mapping[f]}）" if f in mapping else "")
                        for f in fields
                    ),
                    "kind": "schema_mismatch" if proven else "validation_rejected",
                    "title": "模型输出与参数契约不一致"
                    if proven
                    else "模型已提供字段，但执行校验拒绝",
                    "description": description,
                    "evidence": [event.get("id"), invalid.get("id")],
                    "contract": contract.get("report_source") if proven else None,
                    "action": schema_advice(mapping, gap),
                }
            )
        messages = request.get("messages", [])
        non_system = [
            m for m in messages if m.get("role") not in {"system", "developer"}
        ]
        previous = [
            g
            for g in generations
            if isinstance(g.get("turn"), int)
            and isinstance(event.get("turn"), int)
            and g["turn"] < event["turn"]
        ]
        previous_params = [_candidate(g).get("parameters", {}) for g in previous]
        # A lone confirmation plus generic instructions proves the missing request
        # context only when no previous parameter value is present anywhere.
        instruction = " ".join(
            _text(m.get("content"))
            for m in messages
            if m.get("role") in {"system", "developer"}
        )
        values = [
            str(v)
            for p in previous_params
            if isinstance(p, dict)
            for v in p.values()
            if v is not None
        ]
        if (
            len(non_system) == 1
            and not request.get("tools")
            and non_system[0].get("role") == "user"
            and _text(non_system[0].get("content")).strip()
            in {"确认", "确认发放", "确认执行"}
            and candidate.get("status") == "NEED_CLARIFICATION"
            and params == {}
            and values
            and not any(v in instruction for v in values)
        ):
            findings.append(
                {
                    "kind": "missing_confirmation_context",
                    "title": "确认轮请求未携带前轮参数",
                    "description": (
                        f"第 {event['turn']} 轮可见请求只包含确认语句与通用指令，"
                        "没有前轮消息或参数；模型随后返回空参数并要求澄清。"
                        "证据指向会话上下文传递缺口，不能归为模型遗忘。"
                        "内部状态是否保存仍需检查。"
                    ),
                    "evidence": [previous[-1].get("id"), event.get("id")],
                    "action": (
                        "保存待确认操作及参数，将确认绑定到该操作；"
                        "验证确认前不写入、确认后只执行一次，并补充多轮回归。"
                    ),
                }
            )
    metrics = row["assessment"].get("metrics", [])
    failed = {
        m.get("name")
        for m in metrics
        if m.get("success") is False and m.get("formal", True)
    }
    turns = row.get("observation", {}).get("turns", [])
    contradictions = [
        t
        for t in turns
        if any(
            isinstance(c.get("output"), dict)
            and c["output"].get("success") is False
            and (c.get("status") == "SUCCESS" or t.get("status") == "SUCCESS")
            for c in t.get("tool_calls", [])
        )
    ]
    if contradictions and failed & {
        "tool_result_consistent",
        "status_match",
        "turns_match",
    }:
        findings.append(
            {
                "kind": "business_failure_status",
                "title": "业务失败状态传播不一致",
                "description": (
                    "工具返回 success=false，但工具记录或 Agent 终态仍为 SUCCESS；"
                    "业务失败没有一致地传播到状态层，不能归因于用户参数。"
                ),
                "evidence": [
                    e.get("id") for e in events if e.get("type") in {"tool", "turn"}
                ],
                "action": (
                    "在被测 Agent 中区分工具调用完成和业务成功；"
                    "将业务失败传播到工具记录及 Agent 终态，并验证回复与状态一致。"
                ),
            }
        )
    no_calls = bool(turns) and all(
        "tool_calls" in t and not t["tool_calls"] for t in turns
    )
    guarded = any(
        m.get("name") == "tool_not_called" and m.get("success") is True for m in metrics
    )
    if (
        guarded
        and no_calls
        and "response_consistent" in failed
        and any(
            "InvalidModelOutputError" in str(t.get("final_response", "")) for t in turns
        )
    ):
        findings.append(
            {
                "kind": "restricted_response",
                "title": "工具未调用，但错误回复不符合预期",
                "description": (
                    "没有观察到越权工具调用；最终回复暴露 InvalidModelOutputError，"
                    "未满足该任务的限制说明断言。问题是错误回复处理，不能把它写成越权执行。"
                ),
                "evidence": [
                    e.get("id")
                    for e in events
                    if e.get("type") in {"generation", "turn"}
                ],
                "action": (
                    "在被测 Agent 中将无可用工具和模型空响应"
                    "转为可理解的限制或失败说明，"
                    "保留内部错误证据，并验证不会调用禁用工具。"
                ),
            }
        )
    return findings


def load_report_tasks(run: dict) -> tuple[dict, list[str]]:
    """只在离线报告中读取 Hash 绑定的任务目标，绝不交付执行器。"""
    bundle = run.get("config", {}).get("capability_bundle")
    expected = (
        run.get("identity", {}).get("dataset", {}).get("files", {}).get("tasks.jsonl")
    )
    if not bundle or not expected or urlsplit(str(bundle)).scheme:
        return {}, []
    path = Path(bundle).resolve().parent / "tasks.jsonl"
    if not path.is_file():
        return {}, ["冻结任务文件不可用；分组仅能回退到观察到的意图，不代表任务目标。"]
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        return {}, ["任务文件 Hash 不匹配；不用于目标分类。"]
    tasks = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    if len({t["id"] for t in tasks}) != len(tasks):
        return {}, ["任务 ID 重复；不用于目标分类。"]
    return {t["id"]: t for t in tasks}, []


def task_mode(task: dict, contracts: dict) -> str:
    oracle = task.get("oracle", {})
    intent = (oracle.get("expected_module_output") or {}).get("intent")
    mode = contracts.get(intent, {}).get("decision_rules", {}).get("execution_mode")
    if mode in {"read", "write"}:
        return mode
    tools = {c.get("name") for c in oracle.get("expected_tool_calls", [])}
    tools.update(
        c.get("config", {}).get("tool")
        for c in oracle.get("evaluation", {}).get("checks", [])
    )
    if not tools - {None}:
        tools.update(task.get("execution", {}).get("allowed_tools", []))
    modes = {
        c.get("decision_rules", {}).get("execution_mode")
        for c in contracts.values()
        if c.get("required_tool_name") in tools - {None}
    }
    modes &= {"read", "write"}
    if len(modes) == 1:
        return next(iter(modes))
    if not modes:
        # Explicit frozen category, never infer intent from the model's answer.
        return {
            "read": "read",
            "write": "write",
            "read-tool-chain": "read",
            "write-tool-chain": "write",
        }.get(task.get("category"), "unknown")
    return "mixed"


def intent_mode(row: dict, contracts: dict) -> str:
    if "_report_operation" in row:
        return row["_report_operation"]
    if "_report_task" in row:
        return task_mode(row["_report_task"], contracts)
    modes = set()
    for event in row.get("observation", {}).get("events", []):
        if event.get("type") == "generation":
            intent = _candidate(event).get("intent")
            mode = (
                contracts.get(intent, {})
                .get("decision_rules", {})
                .get("execution_mode")
            )
            if mode:
                modes.add(mode)
    return next(iter(modes)) if len(modes) == 1 else "unknown"


def _open_parameter_schema(event: dict, fields: list[str]) -> bool:
    """只有实际请求含开放参数 Schema 且无标准字段时，才报告约束缺口。"""
    request = event.get("input", {})
    if not fields or request.get("tools"):
        return False
    text = " ".join(
        _text(m.get("content"))
        for m in request.get("messages", [])
        if m.get("role") in {"system", "developer"}
    )
    if any(re.search(r"\b" + re.escape(f) + r"\b", text) for f in fields):
        return False
    for match in re.finditer(r"\{", text):
        try:
            schema, _ = json.JSONDecoder().raw_decode(text[match.start() :])
        except ValueError:
            continue
        if not isinstance(schema, dict):
            continue
        parameters = schema.get("properties", {}).get("parameters", {})
        if parameters.get("additionalProperties") is True and not parameters.get(
            "properties"
        ):
            return True
    return False


def latency_details(rows: list[dict]) -> list[dict]:
    result = []
    for row in sorted(
        rows,
        key=lambda r: (
            r.get("latency_seconds")
            if isinstance(r.get("latency_seconds"), (int, float))
            else -1
        ),
        reverse=True,
    )[:3]:
        events = row.get("observation", {}).get("events", [])
        generations = [e for e in events if e.get("type") == "generation"]
        durations = []
        for event in generations:
            try:
                elapsed = (
                    datetime.fromisoformat(event["end_time"].replace("Z", "+00:00"))
                    - datetime.fromisoformat(event["start_time"].replace("Z", "+00:00"))
                ).total_seconds()
                durations.append(elapsed if elapsed >= 0 else None)
            except (KeyError, ValueError, TypeError, AttributeError):
                durations.append(None)
        result.append(
            {
                "case": row["case_id"],
                "trial": row["trial"],
                "latency": row.get("latency_seconds"),
                "turns": len(row.get("observation", {}).get("turns", [])),
                "calls": len(generations),
                "model_seconds": sum(durations)
                if durations and all(d is not None for d in durations)
                else None,
            }
        )
    return result


def report_usage(run_dir: Path, run: dict) -> tuple[list[dict], list[dict], list[str]]:
    """从匹配原始记录的 Inspect 日志补足缓存数据，仅返回报告视图。"""
    rows = run["trials"]
    usages = []
    for row in rows:
        usage = row.get("observation", {}).get("usage", {})
        usages.append(
            {
                "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
                "output_tokens": usage.get(
                    "output_tokens", usage.get("completion_tokens")
                ),
                "total_tokens": usage.get("total_tokens"),
                "cached_tokens": usage.get("cached_tokens"),
                "cache_write_tokens": usage.get("cache_write_tokens"),
            }
        )
    if not (run_dir / "inspect").is_dir():
        return usages, [], []
    from inspect_ai.log import read_eval_log

    from .native_reporting import _log_source, _validated_logs

    try:
        logs, _ = _validated_logs(run_dir, run)
        samples = {}
        for path in logs:
            for sample in read_eval_log(str(path)).samples or []:
                key = (str(sample.id), sample.epoch)
                if key in samples:
                    raise ValueError("duplicate native sample")
                samples[key] = sample
        for row, usage in zip(rows, usages, strict=True):
            sample = samples.get((row["case_id"], row["trial"]))
            if sample is None:
                raise ValueError("missing native sample")
            # Even legacy identity-only logs must match the final saved record.
            if not any(
                (s.metadata or {}).get("benchmark_record") == row
                for s in (sample.scores or {}).values()
            ):
                raise ValueError("native sample has no exact saved record")
            model_usage = list((sample.model_usage or {}).values())
            if not model_usage:
                continue
            for field in ("input_tokens", "output_tokens", "total_tokens"):
                if sum(getattr(u, field) for u in model_usage) != usage[field]:
                    raise ValueError("native usage differs from saved usage")
            cache = [u.input_tokens_cache_read for u in model_usage]
            usage["cached_tokens"] = (
                sum(cache) if all(v is not None for v in cache) else None
            )
            writes = [u.input_tokens_cache_write for u in model_usage]
            usage["cache_write_tokens"] = (
                sum(writes) if all(v is not None for v in writes) else None
            )
        return usages, [_log_source(p, run_dir) for p in logs], []
    except (ValueError, OSError, KeyError, TypeError) as exc:
        # Reject all enrichment on mismatch, including values recovered earlier.
        fallback = []
        for row in rows:
            u = row.get("observation", {}).get("usage", {})
            fallback.append(
                {
                    "input_tokens": u.get("input_tokens", u.get("prompt_tokens")),
                    "output_tokens": u.get("output_tokens", u.get("completion_tokens")),
                    "total_tokens": u.get("total_tokens"),
                    "cached_tokens": u.get("cached_tokens"),
                    "cache_write_tokens": u.get("cache_write_tokens"),
                }
            )
        return fallback, [], [f"原生用量未补入：{exc}。缓存或成本未知时保留未知。"]


def _nonnegative(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def token_parts(usage: dict) -> tuple[float, float, float] | None:
    values = [
        usage.get(k)
        for k in ("input_tokens", "output_tokens", "cached_tokens", "total_tokens")
    ]
    if not all(_nonnegative(v) for v in values):
        return None
    inp, out, cache, total = values
    if usage.get("cache_write_tokens") not in {None, 0}:
        return None
    if total == inp + out + cache:
        return inp, cache, out
    if total == inp + out and inp >= cache:
        return inp - cache, cache, out
    return None


def estimate_cost(run: dict, usages: list[dict], pricing: dict | None) -> dict | None:
    """价格必须显式提供；估算单列，绝不覆盖保存的 cost_usd。"""
    if not pricing or not usages or len(usages) != len(run["trials"]):
        return None
    config = run.get("config", {})
    if any(config.get(k) != pricing.get(k) for k in ("model", "base_url")):
        return None
    source = urlsplit(pricing.get("source", ""))
    if source.scheme != "https" or not source.netloc or not pricing.get("checked_at"):
        return None
    if pricing.get("kind") not in {"subscription_allowance", "api_list_price"}:
        return None
    if (
        any(u.get("cache_write_tokens") is None for u in usages)
        and pricing.get("cache_write_pricing") != "not_applicable"
    ):
        return None
    models = {
        e.get("response_model")
        for row in run["trials"]
        for e in row.get("observation", {}).get("events", [])
        if e.get("type") == "generation" and e.get("response_model")
    }
    if models and models != {pricing["model"]}:
        return None
    parts = [token_parts(u) for u in usages]
    if any(p is None for p in parts):
        return None
    totals = [sum(p[i] for p in parts) for i in range(3)]
    estimates = []
    rates = pricing.get("rates_per_million", [])
    for rate in rates:
        prices = [rate.get(k) for k in ("input", "cache_read", "output")]
        if not all(_nonnegative(v) for v in prices):
            return None
        estimates.append(
            sum(a * b for a, b in zip(totals, prices, strict=True)) / 1_000_000
        )
    if not estimates:
        return None
    return {
        "low": min(estimates),
        "high": max(estimates),
        "pricing": pricing,
        "noncached_input": totals[0],
        "cached_input": totals[1],
        "output": totals[2],
    }
