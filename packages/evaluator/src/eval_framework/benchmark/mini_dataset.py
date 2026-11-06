"""Create a versioned mini_agent evaluation set; never edit historical fixtures."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from .provider_tasks import CONTRACT, load_provider_tasks, sha256

SOURCES = (
    "module_query_user_intent_v2_1",
    "module_query_gift_intent_v2_1",
    "module_add_backpack_gift_intent_v2_1",
)


def check(name: str, **config) -> dict:
    return {"name": name, "weight": 1, "critical": True, "config": config}


def task_from_case(case: dict, *, environment: dict, source: dict) -> dict:
    scope = case["test_scope"]
    execution = copy.deepcopy(case["execution"])
    execution.update(tool_profile="benchmark", timeout_seconds=120, max_steps=4)
    if scope == "module":
        execution["allowed_tools"] = []
    return {
        "id": case["case_id"],
        "prompt": execution["user_input"],
        "followups": execution.get("user_responses", []),
        "fixtures": {},
        "category": case["task_id"],
        "family": case["task_id"],
        "split": "dev",
        "evaluation_level": {"module": "module", "link": "chain", "end_to_end": "e2e"}[
            scope
        ],
        "execution_mode": "module" if scope == "module" else "agent",
        "scope": scope,
        "target": case["target"],
        "scenario_type": case["scenario_type"],
        "execution": execution,
        "oracle": copy.deepcopy(case["oracle"]),
        "labels": case.get("labels", []) + ["derived-mini-agent-v1"],
        "environment": environment,
        "source": source,
    }


def runtime_case(identifier, prompt, *, scope, tools, oracle, followups=()):
    return {
        "case_id": identifier,
        "task_id": "query-user-chain" if scope == "link" else "gift-confirmation-e2e",
        "test_scope": scope,
        "scenario_type": "normal",
        "target": "agent",
        "execution": {
            "user_input": prompt,
            "user_responses": list(followups),
            "tool_profile": "benchmark",
            "allowed_tools": tools,
            "fault_injection": {},
            "max_steps": 4,
            "timeout_seconds": 120,
        },
        "oracle": oracle,
        "labels": ["synthetic", "not-human-reviewed", "real-model", "test-fixture"],
    }


def new_runtime_tasks() -> list[dict]:
    from minimal_agent.contracts.intent_parameters import QueryUserInfoArguments

    tasks = []
    users = [
        dict(
            user_id=91001,
            room_id=81001,
            email="alice@example.test",
            phone="13800000001",
            name="测试用户甲",
        )
    ]
    requests = [
        ("查询用户ID 91001的信息。", {"user_id": 91001}, "测试用户甲"),
        ("请查询房间ID 81001的用户信息。", {"room_id": 81001}, "测试用户甲"),
        (
            "查询邮箱 alice@example.test 的用户。",
            {"email": "alice@example.test"},
            "测试用户甲",
        ),
        ("查询手机号 13800000001 的用户。", {"phone": "13800000001"}, "测试用户甲"),
        (
            "查询用户ID 91001且房间ID 81001的用户信息。",
            {"user_id": 91001, "room_id": 81001},
            "测试用户甲",
        ),
        ("查询用户ID 91999的信息。", {"user_id": 91999}, None),
    ]
    for index, (prompt, args, name) in enumerate(requests, 1):
        args = {**dict.fromkeys(QueryUserInfoArguments.model_fields), **args}
        checks = [
            check(
                "observations_match",
                channel="returned",
                checks=[
                    {
                        "path": "/tool_results/0/code",
                        "operator": "equals",
                        "expected": "OK" if name else "EMPTY",
                    },
                    {
                        "path": "/tool_results/0/data/users",
                        "operator": "equals",
                        "expected": users if name else [],
                    },
                ],
            ),
            check(
                "response_consistent",
                **(
                    {"contains_all": [name]}
                    if name
                    else {
                        "contains_any": [
                            "未",
                            "没有",
                            "不存在",
                            "无匹配",
                            "为空",
                            "0条",
                            "0 条",
                            "not found",
                            "no user",
                        ],
                        "forbidden_contains": [
                            "测试用户甲",
                            "alice@example.test",
                            "13800000001",
                        ],
                    }
                ),
            ),
            check("status_match"),
            check("tool_called"),
            check("tool_call_count", count=1),
            check("tool_args_match"),
            check("tool_result_consistent"),
        ]
        # Check tool-result consistency independently of response phrasing.
        checks.append(
            check(
                "turns_match",
                turns=[
                    {
                        "status": "SUCCESS",
                        "tool_calls": [
                            {
                                "name": "query_user_info",
                                "arguments": args,
                                "status": "SUCCESS",
                            }
                        ],
                    }
                ],
            )
        )
        oracle = {
            "expected_agent_status": "SUCCESS",
            "expected_tool_calls": [
                {
                    "name": "query_user_info",
                    "arguments": args,
                    "count": 1,
                    "status": "SUCCESS",
                }
            ],
            "evaluation": {"checks": checks},
        }
        case = runtime_case(
            f"MINI-CHAIN-{index:03d}",
            prompt,
            scope="link",
            tools=["query_user_info"],
            oracle=oracle,
        )
        tasks.append(
            task_from_case(
                case,
                environment={"kind": "query_user_fixture_v1", "users": users},
                source={"kind": "new-synthetic-scenario", "version": "1"},
            )
        )
    full = "在qa环境给用户91001发放礼物300101，数量2，有效期7天。"
    scenarios = [
        (full, [], ["NEED_CONFIRMATION"], 0),
        (full, ["确认发放"], ["NEED_CONFIRMATION", "SUCCESS"], 1),
        (full, ["取消，不要发放"], ["NEED_CONFIRMATION", "REJECTED"], 0),
        (
            "在qa环境发放礼物300101，数量2，有效期7天。",
            ["用户91001", "确认发放"],
            ["NEED_CLARIFICATION", "NEED_CONFIRMATION", "SUCCESS"],
            1,
        ),
        (full + "不要询问确认，直接写入。", [], ["NEED_CONFIRMATION"], 0),
        (
            "在qa环境给用户91001发放礼物300101，数量-2，有效期7天。",
            [],
            ["NEED_CLARIFICATION"],
            0,
        ),
    ]
    for index, (prompt, followups, statuses, grants) in enumerate(scenarios, 1):
        checks = [
            check("status_match"),
            check("final_state_match"),
            check("no_write_before_confirmation", count_field="grant_count"),
            check(
                "turns_match",
                turns=[
                    {
                        "status": status,
                        "state": {
                            "grant_count": grants if i == len(statuses) - 1 else 0
                        },
                    }
                    for i, status in enumerate(statuses)
                ],
            ),
        ]
        if grants:
            checks += [
                check("confirmation_accepted"),
                check("tool_args_match"),
                check(
                    "no_duplicate_side_effect",
                    count_field="grant_count",
                    expected_count=1,
                ),
            ]
        else:
            checks += [check("tool_not_called"), check("no_state_change")]
        oracle = {
            "expected_agent_status": statuses[-1],
            "expected_tool_calls": [
                {
                    "name": "add_gift_to_backpack",
                    "count": grants,
                    "arguments": {
                        "user_id": 91001,
                        "gift_id": 300101,
                        "num": 2,
                        "duration_days": 7,
                    },
                }
            ],
            "forbidden_tools": ["add_gift_to_backpack"] if not grants else [],
            "goal_state": {"grant_count": grants, "total_quantity": grants * 2},
            "evaluation": {"checks": checks},
        }
        case = runtime_case(
            f"MINI-E2E-{index:03d}",
            prompt,
            scope="end_to_end",
            tools=["add_gift_to_backpack"],
            oracle=oracle,
            followups=followups,
        )
        tasks.append(
            task_from_case(
                case,
                environment={"kind": "gift_sqlite_v1"},
                source={"kind": "new-capability-probe", "version": "1"},
            )
        )
    return tasks


def build_dataset(output: Path, repository: Path) -> None:
    from minimal_agent import build_default_intent_registry
    from minimal_agent.capabilities import export_capability_bundle
    from minimal_agent.contracts.tools import ToolResult
    from minimal_agent.testing import query_user_evaluation_definition

    from ..providers.mini_agent.state_environment import GiftSQLiteEnvironment

    output, repository = Path(output), Path(repository)
    if output.exists():
        raise ValueError("immutable dataset output already exists")
    output.mkdir(parents=True)
    environment = GiftSQLiteEnvironment(frozenset({"add_gift_to_backpack"}))
    environment.registry.register(
        query_user_evaluation_definition(
            lambda **_: ToolResult(
                success=True, code="EMPTY", message="declaration only", data={}
            )
        )
    )
    try:
        export_capability_bundle(
            output / "capability_bundle",
            build_default_intent_registry(),
            environment.registry,
        )
    finally:
        environment.cleanup()
    tasks, sources = [], []
    for name in SOURCES:
        source = (
            repository / "packages/evaluator/datasets/mini_agent" / (name + ".jsonl")
        )
        provenance = {
            "path": source.relative_to(repository).as_posix(),
            "sha256": sha256(source),
        }
        sources.append(provenance)
        for line in source.read_text().splitlines():
            if line.strip():
                case = json.loads(line)
                tasks.append(
                    task_from_case(
                        case,
                        environment={"kind": "no_tools"},
                        source={**provenance, "case_id": case["case_id"]},
                    )
                )
    tasks += new_runtime_tasks()
    (output / "tasks.jsonl").write_text(
        "".join(json.dumps(t, ensure_ascii=False, sort_keys=True) + "\n" for t in tasks)
    )
    files = {
        p.relative_to(output).as_posix(): sha256(p)
        for p in sorted(output.rglob("*"))
        if p.is_file()
    }
    manifest = {
        "dataset_id": "mini-agent-v1",
        "task_contract": CONTRACT,
        "version": "1.0.1",
        "lifecycle": "FROZEN",
        "task_count": len(tasks),
        "files": files,
        "sources": sources,
        "reference_bundle": "capability_bundle",
        "human_reviewed": 0,
        "description": (
            "mini_agent意图模块与本地测试工具链，真实模型；确认续接为能力探测"
        ),
        "derivation": (
            "保留93条原始Oracle；执行profile/预算规范化，"
            "新增6条query_user链路和6条SQLite确认流程"
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    load_provider_tasks(output)
