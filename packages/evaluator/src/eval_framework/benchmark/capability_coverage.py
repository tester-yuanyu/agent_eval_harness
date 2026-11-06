"""固定 nanobot 实际源码与有效 profile，按证据层级报告能力覆盖。

目录路径只用于本机取证，不进入公开返回值。快照不读取用户全局配置，不
构造 Agent/Provider。能力清单是显式维护的有限边界，不推断整体覆盖率。
旧执行保留旧身份；新运行必须同时绑定数据、快照、profile、适配与评分代码。
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .inspect_docker import source_digest, source_files

SNAPSHOT_VERSION = "nanobot-capability-snapshot-v1"
COVERAGE_VERSION = "nanobot-capability-coverage-v1"
_REPO_ROOT = Path(__file__).resolve().parents[5]
_BASE = "packages/evaluator/src/eval_framework/benchmark/"
_PROFILE_FILES = {
    "file_tools": {
        "adapter": [
            "nanobot_worker.py",
            "nanobot_runtime.py",
            "inspect_runtime.py",
            "inspect_docker.py",
            "runner.py",
            "capability_coverage.py",
        ],
        "scoring": [
            "metrics.py",
            "oracle.py",
            "trajectory.py",
            "recovery_scoring.py",
            "module_oracle.py",
            "tasks.py",
            "repetition.py",
            "agentic_metrics.py",
            "agentic_metrics_worker.py",
        ],
    },
    "core_modules": {
        "adapter": [
            "core_runner.py",
            "core_worker.py",
            "core_tasks.py",
            "inspect_runtime.py",
            "nanobot_runtime.py",
            "runner.py",
            "inspect_docker.py",
            "capability_coverage.py",
        ],
        "scoring": ["core_scoring.py", "core_tasks.py"],
    },
}
_PROFILE_EFFECTIVE = {
    "file_tools": {
        "execution_kind": "real_agent",
        "description": "当前文件工具适配器；不是历史 nanobot-file-sdk-v1 的运行身份",
        "enabled_domains": ["file_tools", "session", "memory", "context"],
        "tool_allowlist": ["read_file", "write_file", "edit_file", "list_dir"],
        "skills": "all_builtin_disabled; private empty workspace",
        "mcp": False,
        "channels": False,
        "cron": False,
        "subagent_tool": False,
        "session": "isolated per trial; persistent within followups",
        "idle_compaction": False,
        "context_window_tokens": 100000,
        "max_tool_result_chars": 64000,
        "scope_note": (
            "Memory/context 实例参与运行不等于其全部行为已测；"
            "模型与沙箱参数由运行身份另行固定"
        ),
    },
    "core_modules": {
        "execution_kind": "real_core_module",
        "description": "真实 Session/Memory/Context/Skills 组件的离线确定性测试",
        "enabled_domains": ["session", "memory", "context", "skills"],
        "model_provider": False,
        "network": False,
        "mcp": False,
        "channels": False,
        "cron": False,
        "subagent_tool": False,
        "scope_note": (
            "组件操作结果，不是 LLM 或完整 Agent 成绩；"
            "skills 使用任务专属 fixture；可信固定模块实验，非恶意代码安全沙箱"
        ),
    },
}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _profiles() -> dict:
    from .layer_sources import layer_source_paths

    profiles = {}
    for name, groups in _PROFILE_FILES.items():
        hashes = {}
        group_hashes = {}
        missing = []
        for group, files in groups.items():
            selected = {}
            for filename in files:
                relative = _BASE + filename
                path = _REPO_ROOT / relative
                if not path.is_file():
                    missing.append(relative)
                    continue
                selected[relative] = _sha(path.read_bytes())
            # The compatibility modules no longer contain the implementations.
            # Bind the extracted closure as well as the historical entry files.
            for label in layer_source_paths():
                package = (
                    "contracts" if label.startswith("eval_contracts/") else "evaluator"
                )
                relative = f"packages/{package}/src/{label}"
                path = _REPO_ROOT / relative
                if not path.is_file():
                    missing.append(relative)
                    continue
                selected[relative] = _sha(path.read_bytes())
            hashes.update(selected)
            group_hashes[group + "_sha256"] = _digest(selected)
        profile = {
            "available": not missing,
            "missing_code": sorted(set(missing)),
            "code_hashes": hashes,
            "effective": _PROFILE_EFFECTIVE[name],
            **group_hashes,
        }
        profile["profile_hash"] = _digest(profile)
        profiles[name] = profile
    return profiles


def _validate_import_sources(root: Path, files: dict[str, bytes]) -> None:
    """Reject executable imports outside the manifest, not unknown assets.

    Linked directory contents are inspected for filenames only, never source
    bytes. Cycle detection applies inside that scan, so a link back to an
    ancestor package with Python children is still rejected. Cache directories
    are excluded explicitly, matching the supported source-import boundary.
    """
    suffixes = (
        ".py",
        *importlib.machinery.EXTENSION_SUFFIXES,
        *importlib.machinery.BYTECODE_SUFFIXES,
    )

    def has_imports(directory: Path, seen: set[Path]) -> bool:
        resolved = directory.resolve()
        if resolved in seen:
            return False
        seen.add(resolved)
        for path in directory.iterdir():
            if path.name == "__pycache__":
                continue
            if path.is_dir():
                if has_imports(path, seen):
                    return True
            elif path.name.endswith(suffixes):
                return True
        return False

    def walk(directory: Path) -> None:
        if directory.is_symlink():
            if has_imports(directory, set()):
                raise ValueError("unsupported import source: linked Python directory")
            return
        for path in directory.iterdir():
            if path.name == "__pycache__":
                continue
            if path.is_dir():
                walk(path)
            elif path.name.endswith(suffixes):
                relative = path.relative_to(root).as_posix()
                if path.is_symlink() or relative not in files:
                    raise ValueError(
                        "unsupported import source: symlink or unbound " + relative
                    )

    try:
        walk(root / "nanobot")
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            "unsupported import source: directory cannot be inspected"
        ) from exc


def snapshot_nanobot(config: dict) -> dict:
    """只接收源码根目录与 Python 路径，返回不含绝对路径的机器身份。"""
    if not isinstance(config, dict) or set(config) != {"nanobot_root", "python"}:
        raise ValueError("snapshot config accepts only nanobot_root and python")
    if any(not isinstance(value, str) or not value for value in config.values()):
        raise ValueError("snapshot config paths must be nonempty strings")
    root = Path(config["nanobot_root"]).expanduser().resolve(strict=True)
    python = Path(config["python"]).expanduser().absolute()
    if not root.is_dir() or not python.is_file():
        raise ValueError(
            "snapshot config must identify a source directory and interpreter"
        )
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "-C", str(root), "status", "--porcelain"], text=True
        ).strip()
    )
    files = source_files(root)
    if not files:
        raise ValueError("nanobot source manifest is empty")
    _validate_import_sources(root, files)
    # No imports of the target project, no user config, no inherited credentials.
    probe = """import json,platform,importlib.metadata,importlib.util,sys,hashlib
from pathlib import Path
root=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(root))
spec=importlib.util.find_spec('nanobot')
origin=Path(spec.origin).resolve()
if origin != root/'nanobot'/'__init__.py':
    raise RuntimeError('nanobot import does not resolve to selected source')
rows=sorted(
    [{"name":d.metadata["Name"],"version":d.version}
     for d in importlib.metadata.distributions()],
    key=lambda x:(x["name"].lower(),x["version"]))
print(json.dumps({
    "python_version":platform.python_version(),
    "implementation":platform.python_implementation(),
    "dependencies":rows,
    "source_import_identity":{
        "relative_path":origin.relative_to(root).as_posix(),
        "sha256":hashlib.sha256(origin.read_bytes()).hexdigest(),
        "resolution":"isolated bootstrap; explicit source root; verified find_spec"
    }}))"""
    environment = json.loads(
        subprocess.check_output(
            [str(python), "-I", "-c", probe, str(root)],
            text=True,
            timeout=30,
            env={
                "PATH": os.defpath,
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
    )
    for item in environment["dependencies"]:
        if not all(
            isinstance(item.get(key), str)
            and re.fullmatch(r"[A-Za-z0-9_.+!~-]+", item[key])
            for key in ("name", "version")
        ):
            raise ValueError("interpreter dependency metadata is not portable")
    environment["dependencies_sha256"] = _digest(environment["dependencies"])
    environment["dependency_identity_scope"] = (
        "installed distribution names and versions; "
        "editable dependency contents not hashed"
    )
    imported = environment["source_import_identity"]
    if imported["relative_path"] not in files or imported["sha256"] != _sha(
        files[imported["relative_path"]]
    ):
        raise ValueError("source import identity is outside the source manifest")
    environment["python_binary_sha256"] = _sha(python.resolve(strict=True).read_bytes())
    harness_probe = """import json,platform,importlib.metadata
rows=sorted(
    [{"name":d.metadata["Name"],"version":d.version}
     for d in importlib.metadata.distributions()],
    key=lambda x:(x["name"].lower(),x["version"]))
print(json.dumps({"python_version":platform.python_version(),
    "implementation":platform.python_implementation(),"dependencies":rows}))"""
    harness_environment = json.loads(
        subprocess.check_output(
            [sys.executable, "-I", "-c", harness_probe],
            text=True,
            timeout=30,
            env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
        )
    )
    for item in harness_environment["dependencies"]:
        if not all(
            isinstance(item.get(key), str)
            and re.fullmatch(r"[A-Za-z0-9_.+!~-]+", item[key])
            for key in ("name", "version")
        ):
            raise ValueError("harness dependency metadata is not portable")
    harness_environment["dependencies_sha256"] = _digest(
        harness_environment["dependencies"]
    )
    harness_environment["dependency_identity_scope"] = environment[
        "dependency_identity_scope"
    ]
    harness_environment["python_binary_sha256"] = _sha(
        Path(sys.executable).resolve(strict=True).read_bytes()
    )
    result = {
        "version": SNAPSHOT_VERSION,
        "source": {
            "commit": commit,
            "dirty": dirty,
            "working_tree_sha256": source_digest(files),
            "digest_algorithm": (
                "inspect-source-v1: sorted(path + NUL + raw_bytes + NUL)"
            ),
            "manifest_scope": (
                "git cached + unignored others; nanobot/ and pyproject.toml/uv.lock; "
                "inspect_docker.source_files filters; not a full repository hash"
            ),
            "import_source_policy": (
                "nanobot/ Python, direct bytecode and native extensions "
                "must be nonsymlink manifest "
                "members; __pycache__ excluded; other resource types not checked"
            ),
            "manifest_implementation_sha256": _sha(
                Path(__file__).with_name("inspect_docker.py").read_bytes()
            ),
            "files": {name: _sha(raw) for name, raw in sorted(files.items())},
        },
        "environment": environment,
        "harness_environment": harness_environment,
        "profiles": _profiles(),
    }
    result["snapshot_hash"] = _digest(result)
    return result


def _validate_snapshot(snapshot: dict) -> None:
    if snapshot.get("version") != SNAPSHOT_VERSION or snapshot.get(
        "snapshot_hash"
    ) != _digest({k: v for k, v in snapshot.items() if k != "snapshot_hash"}):
        raise ValueError("snapshot identity hash mismatch")
    for profile in snapshot.get("profiles", {}).values():
        if profile.get("profile_hash") != _digest(
            {k: v for k, v in profile.items() if k != "profile_hash"}
        ):
            raise ValueError("profile identity hash mismatch")
    environment = snapshot.get("environment", {})
    if environment.get("dependencies_sha256") != _digest(
        environment.get("dependencies")
    ):
        raise ValueError("environment dependency hash mismatch")


def _catalog(catalog: dict, snapshot: dict) -> list[dict]:
    rows = catalog.get("capabilities")
    if not isinstance(rows, list) or not rows or not catalog.get("version"):
        raise ValueError("coverage catalog requires a version and capabilities")
    seen = set()
    for row in rows:
        identifier = row.get("id")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]*", identifier)
            or identifier in seen
        ):
            raise ValueError("duplicate or invalid capability id")
        seen.add(identifier)
        for field in (
            "source_paths",
            "scenarios",
            "success_conditions",
            "evidence_requirements",
        ):
            if (
                not isinstance(row.get(field), list)
                or not row[field]
                or any(not isinstance(value, str) or not value for value in row[field])
            ):
                raise ValueError(
                    "catalog evidence/scenario fields must be nonempty lists"
                )
        for path in row["source_paths"]:
            parsed = PurePosixPath(path)
            if parsed.is_absolute() or ".." in parsed.parts or "\\" in path:
                raise ValueError("catalog source paths must be portable relative paths")
        if row.get("priority") not in {"P0", "P1", "P2"}:
            raise ValueError("catalog requires an explicit priority")
        for profile, enabled in row.get("profiles", {}).items():
            if profile not in snapshot["profiles"] or type(enabled) is not bool:
                raise ValueError("unknown profile or invalid enabled claim")
            actual = (
                identifier
                in snapshot["profiles"][profile]["effective"]["enabled_domains"]
            )
            if enabled != actual:
                raise ValueError(
                    "catalog enabled state conflicts with effective profile"
                )
    return rows


def _load_dataset(descriptor: dict) -> tuple[dict, list[dict]]:
    path = Path(descriptor["path"])
    if descriptor.get("kind") == "core":
        from .core_tasks import core_dataset_identity, load_core_tasks

        path = path / "tasks.jsonl" if path.is_dir() else path
        identity, tasks = core_dataset_identity(path), load_core_tasks(path)
    elif descriptor.get("kind") == "file_tools":
        from .tasks import dataset_identity, load_tasks

        identity, tasks = dataset_identity(path), load_tasks(path)
    else:
        raise ValueError("unsupported coverage dataset kind")
    if descriptor.get("identity") != identity or descriptor.get(
        "identity_hash"
    ) != _digest(identity):
        raise ValueError("dataset source identity mismatch")
    return identity, tasks


def _capability(task: dict, kind: str, capabilities: list[dict]) -> str:
    known = {row["id"] for row in capabilities}
    explicit = task.get("capability", task.get("component"))
    if explicit is not None:
        if explicit not in known:
            raise ValueError("task declares unknown capability")
        return explicit
    matches = [
        row["id"]
        for row in capabilities
        if any(
            str(task.get("family", "")).startswith(prefix)
            for prefix in row.get("family_prefixes", [])
        )
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches and kind == "file_tools" and "file_tools" in known:
        return "file_tools"
    raise ValueError("task family has ambiguous or missing capability mapping")


def _complete(observation: dict, kind: str) -> bool:
    if (
        observation.get("evidence_complete") is not True
        or observation.get("status") != "completed"
    ):
        return False
    events = observation.get("events")
    if not isinstance(events, list) or not events:
        return False
    ids = []
    executed = False
    for event in events:
        if (
            not isinstance(event, dict)
            or not isinstance(event.get("id"), str)
            or not event["id"]
            or event.get("incomplete")
        ):
            return False
        ids.append(event["id"])
        if event.get("type") not in {"tool", "module"}:
            continue
        if kind == "core":
            # core_worker emits Unix seconds via time.time(), not ISO strings.
            start, end = event.get("start_time"), event.get("end_time")
            if any(type(value) not in (int, float) for value in (start, end)):
                return False
            if (
                any(
                    type(value) is float and not math.isfinite(value)
                    for value in (start, end)
                )
                or end < start
            ):
                return False
        else:
            try:
                start = datetime.fromisoformat(
                    event["start_time"].replace("Z", "+00:00")
                )
                end = datetime.fromisoformat(event["end_time"].replace("Z", "+00:00"))
                if start.tzinfo is None or end.tzinfo is None or end < start:
                    return False
            except (KeyError, ValueError, TypeError, AttributeError):
                return False
        if "output" not in event and not event.get("error"):
            return False
        if kind == "core":
            executed |= event.get("type") == "module" and isinstance(
                event.get("operation"), str
            )
        else:
            executed |= event.get("execution_started") is True
    if len(set(ids)) != len(ids):
        return False
    for key in ("before_files", "final_files"):
        if not isinstance(observation.get(key), dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in observation[key].items()
        ):
            return False
    return executed


def _assessed(task: dict, observation: dict, assessment: dict, kind: str) -> bool:
    if kind == "core":
        from .core_scoring import score_core_task

        actual = score_core_task(task, observation)
    else:
        from .metrics import score_task

        actual = score_task(task, observation)
    for field in ("verdict", "validity"):
        if assessment.get(field) != actual.get(field):
            raise ValueError(
                "saved assessment conflicts with independent scoring evidence"
            )
    if assessment.get("verdict") != "PASS":
        return False
    formal = [
        item for item in assessment.get("metrics", []) if item.get("formal") is True
    ]
    if not formal or any(
        item.get("success") is not True or type(item.get("score")) not in (int, float)
        for item in formal
    ):
        raise ValueError("PASS requires successful formal evidence metrics")
    return actual.get("verdict") == "PASS" and actual.get("validity") == "VALID"


def build_coverage_report(
    snapshot: dict, catalog: dict, datasets: list[dict], runs: list[dict]
) -> dict:
    """验证声明来源，输出 profile×能力×split；历史执行不升级当前覆盖。"""
    _validate_snapshot(snapshot)
    capabilities = _catalog(catalog, snapshot)
    loaded, sources = {}, []
    matrix = {}
    for profile in snapshot["profiles"]:
        for cap in capabilities:
            present = all(
                path in snapshot["source"]["files"] for path in cap["source_paths"]
            )
            enabled = (
                cap["id"]
                in snapshot["profiles"][profile]["effective"]["enabled_domains"]
            )
            matrix[(profile, cap["id"])] = {
                "profile": profile,
                "capability": cap["id"],
                "title": cap.get("title", cap["id"]),
                "source_present": present,
                "enabled_in_profile": enabled,
                "dataset_defined": False,
                "executed": False,
                "passed": False,
                "human_reviewed": False,
                "human_review_status": "pending_independent_review",
                "priority": cap["priority"],
                "scenarios": cap["scenarios"],
                "success_conditions": cap["success_conditions"],
                "evidence_requirements": cap["evidence_requirements"],
                "source_evidence": [
                    {"path": p, "sha256": snapshot["source"]["files"].get(p)}
                    for p in cap["source_paths"]
                ],
                "splits": {},
                "execution_evidence": [],
                "gaps": [],
            }
    for descriptor in datasets:
        identity, tasks = _load_dataset(descriptor)
        key = _digest(identity)
        profile = descriptor.get("profile")
        if key in loaded or profile not in snapshot["profiles"]:
            raise ValueError("duplicate dataset identity or unknown profile")
        mapped = {
            task["id"]: _capability(task, descriptor["kind"], capabilities)
            for task in tasks
        }
        loaded[key] = {
            "identity": identity,
            "tasks": {task["id"]: task for task in tasks},
            "mapped": mapped,
            **{k: descriptor[k] for k in ("kind", "profile")},
        }
        sources.append(
            {
                "kind": "dataset",
                "dataset_id": identity.get("dataset_id"),
                "identity_hash": key,
            }
        )
        for task in tasks:
            item = matrix[(profile, mapped[task["id"]])]
            item["dataset_defined"] = True
            split = item["splits"].setdefault(
                task["split"],
                {
                    "defined_cases": 0,
                    "planned_trials": 0,
                    "observed_trials": 0,
                    "executed_trials": 0,
                    "passed_trials": 0,
                    "families": [],
                    "executed_case_ids": [],
                },
            )
            split["defined_cases"] += 1
            if task["family"] not in split["families"]:
                split["families"].append(task["family"])
    legacy_runs, current_runs, seen = [], [], set()
    for descriptor in runs:
        path = Path(descriptor["path"])
        path = path / "results.json" if path.is_dir() else path
        raw = path.read_bytes()
        sha = _sha(raw)
        if sha != descriptor.get("sha256"):
            raise ValueError("run source hash mismatch")
        run = json.loads(raw)
        run_id = run.get("run_id")
        if not isinstance(run_id, str) or not run_id or run_id.startswith("/"):
            raise ValueError("run requires a portable run_id")
        if ("run", run_id) in seen or ("sha", sha) in seen:
            raise ValueError("duplicate run source")
        seen.update({("run", run_id), ("sha", sha)})
        identity = run.get("identity")
        if not isinstance(identity, dict) or run.get("identity_hash") != _digest(
            identity
        ):
            raise ValueError("run identity hash mismatch")
        data = loaded.get(_digest(identity.get("dataset")))
        if data is None:
            raise ValueError("run dataset identity has no verified source")
        legacy = descriptor.get("kind") == "legacy"
        if descriptor.get("kind") not in {"legacy", "current"}:
            raise ValueError("run kind must explicitly be current or legacy")
        profile = data["profile"]
        expected = snapshot["profiles"][profile]
        if legacy:
            if not identity.get("runtime") or not identity.get("scoring_version"):
                raise ValueError("legacy run requires its own runtime/scoring identity")
        else:
            required = {
                "snapshot": snapshot["snapshot_hash"],
                "profile": profile,
                **{
                    k: expected[k]
                    for k in ("profile_hash", "adapter_sha256", "scoring_sha256")
                },
            }
            if not expected["available"] or any(
                identity.get(k) != v for k, v in required.items()
            ):
                raise ValueError("run snapshot/profile/code identity mismatch")
        planned, repeats, trials = (
            run.get("planned_case_ids"),
            run.get("trials_per_case"),
            run.get("trials"),
        )
        if (
            not isinstance(planned, list)
            or any(not isinstance(case, str) for case in planned)
            or len(set(planned)) != len(planned)
            or not set(planned) <= data["tasks"].keys()
        ):
            raise ValueError("run planned cases are duplicate or outside its dataset")
        if type(repeats) is not int or repeats < 1 or not isinstance(trials, list):
            raise ValueError("run requires positive integer trials_per_case and trials")
        if not legacy:
            for case in planned:
                task = data["tasks"][case]
                matrix[(profile, data["mapped"][case])]["splits"][task["split"]][
                    "planned_trials"
                ] += repeats
        trial_seen, verdicts = set(), Counter()
        for trial in trials:
            case, number = trial.get("case_id"), trial.get("trial")
            if (
                not isinstance(case, str)
                or case not in planned
                or type(number) is not int
                or not 1 <= number <= repeats
                or (case, number) in trial_seen
            ):
                raise ValueError("duplicate, unplanned or invalid trial")
            trial_seen.add((case, number))
            if trial.get("identity_hash") != run["identity_hash"]:
                raise ValueError("trial identity differs from run identity")
            observation, assessment = trial.get("observation"), trial.get("assessment")
            if not isinstance(observation, dict) or not isinstance(assessment, dict):
                raise ValueError("trial requires saved observation and assessment")
            allowed = (
                {"real_core_module"}
                if data["kind"] == "core"
                else {"real_agent", "real_module", "real_model_decision"}
                if legacy
                else {"real_agent"}
            )
            if observation.get("execution_kind") not in allowed:
                raise ValueError(
                    "reference or unknown execution kind "
                    "cannot claim execution coverage"
                )
            verdicts[assessment.get("verdict", "UNKNOWN")] += 1
            if legacy:
                continue
            runtime = observation.get("runtime_identity")
            expected_runtime = {
                "snapshot": snapshot["snapshot_hash"],
                "profile": profile,
                **{
                    key: expected[key]
                    for key in ("profile_hash", "adapter_sha256", "scoring_sha256")
                },
                "source_sha256": snapshot["source"]["working_tree_sha256"],
                "dependencies_sha256": snapshot["environment"]["dependencies_sha256"],
            }
            if not isinstance(runtime, dict) or any(
                runtime.get(key) != value for key, value in expected_runtime.items()
            ):
                raise ValueError("observation runtime identity differs from snapshot")
            task = data["tasks"][case]
            item = matrix[(profile, data["mapped"][case])]
            if not item["enabled_in_profile"] or not item["source_present"]:
                raise ValueError(
                    "execution claims a capability absent from "
                    "source or effective profile"
                )
            split = item["splits"][task["split"]]
            split["observed_trials"] += 1
            complete = _complete(observation, data["kind"])
            passed = _assessed(task, observation, assessment, data["kind"])
            if passed and not complete:
                raise ValueError(
                    "PASS cannot claim execution without complete executed evidence"
                )
            if complete:
                split["executed_trials"] += 1
                if case not in split["executed_case_ids"]:
                    split["executed_case_ids"].append(case)
                split["passed_trials"] += int(passed)
            item["execution_evidence"].append(
                {
                    "run_id": run_id,
                    "source_sha256": sha,
                    "case_id": case,
                    "trial": number,
                    "split": task["split"],
                    "complete_execution": complete,
                    "verdict": assessment.get("verdict"),
                    "event_ids": [
                        event.get("id")
                        for event in observation.get("events", [])
                        if isinstance(event, dict)
                    ],
                }
            )
        summary = {
            "run_id": run_id,
            "source_sha256": sha,
            "identity_hash": run["identity_hash"],
            "dataset_identity_hash": _digest(identity["dataset"]),
            "planned_trials": len(planned) * repeats,
            "observed_trials": len(trials),
            "saved_verdicts": dict(verdicts),
        }
        if legacy:
            legacy_runs.append(
                {
                    **summary,
                    "not_bound_to_current_profile": True,
                    "scoring_version": identity["scoring_version"],
                    "runtime_identity_hash": _digest(identity["runtime"]),
                }
            )
        else:
            current_runs.append({**summary, "profile": profile})
        sources.append(
            {
                "kind": "legacy_run" if legacy else "current_run",
                "run_id": run_id,
                "sha256": sha,
            }
        )
    for item in matrix.values():
        all_splits = list(item["splits"].values())
        total = sum(s["executed_trials"] for s in all_splits)
        passed = sum(s["passed_trials"] for s in all_splits)
        item["executed"] = total > 0
        item["passed"] = total > 0 and passed == total
        item["passed_scope"] = (
            "observed_complete_trials_only; not all scenarios or all defined cases"
        )
        for split in all_splits:
            split["status"] = (
                "not_executed"
                if not split["executed_trials"]
                else "partially_executed"
                if len(split["executed_case_ids"]) < split["defined_cases"]
                or split["executed_trials"] < split["planned_trials"]
                else "planned_execution_complete"
            )
            split["families"].sort()
            split["executed_case_ids"].sort()
        for flag, message in [
            ("source_present", "源码证据不足"),
            ("enabled_in_profile", "当前 profile 未启用"),
            ("dataset_defined", "尚无绑定数据集场景"),
            ("executed", "当前 profile 尚无完整执行证据"),
        ]:
            if not item[flag]:
                item["gaps"].append(message)
        if any(
            name == "holdout" and split["status"] == "not_executed"
            for name, split in item["splits"].items()
        ):
            item["gaps"].append("holdout 尚未执行，不能称独立验收")
        item["gaps"].append("独立人工审核待完成")
    return {
        "version": COVERAGE_VERSION,
        "snapshot_hash": snapshot["snapshot_hash"],
        "catalog_version": catalog["version"],
        "catalog_sha256": _digest(catalog),
        "sources": sources,
        "matrix": list(matrix.values()),
        "current_runs": current_runs,
        "legacy_runs": legacy_runs,
        "limitations": [
            "清单为本版显式边界，不是 nanobot 整体能力穷举；不计算整体覆盖率。",
            "passed仅指已观测完整执行，不能升级为所有场景或holdout均通过。",
            "组件运行不是LLM或完整Agent成绩；机器评分不构成人工审核。",
        ],
    }
