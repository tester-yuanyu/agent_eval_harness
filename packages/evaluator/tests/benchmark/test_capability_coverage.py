"""覆盖状态必须来自绑定身份的真实证据，不能由已评分标志推断。"""

import hashlib
import importlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]


def api():
    try:
        return importlib.import_module("eval_framework.benchmark.capability_coverage")
    except ModuleNotFoundError:
        pytest.fail("nanobot source snapshot and coverage report are not implemented")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "agent"
    (root / "nanobot").mkdir(parents=True)
    (root / "nanobot/agent.py").write_text("VALUE = 1\n")
    (root / "nanobot/__init__.py").write_text("")
    (root / "pyproject.toml").write_text('[project]\nname="example"\nversion="1.0"\n')
    for args in [
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ]:
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


def snapshot(source):
    return api().snapshot_nanobot(
        {"nanobot_root": str(source), "python": sys.executable}
    )


def test_snapshot_binds_dirty_worktree_dependency_and_profiles_without_paths(source):
    first = snapshot(source)
    (source / "nanobot/agent.py").write_text("VALUE = 2\n")
    second = snapshot(source)
    assert first["source"]["commit"] == second["source"]["commit"]
    assert first["source"]["dirty"] is False and second["source"]["dirty"] is True
    assert (
        first["source"]["working_tree_sha256"]
        != second["source"]["working_tree_sha256"]
    )
    assert first["snapshot_hash"] != second["snapshot_hash"]
    assert (
        second["source"]["files"]["nanobot/agent.py"]
        == hashlib.sha256(b"VALUE = 2\n").hexdigest()
    )
    assert second["environment"]["dependencies_sha256"] == digest(
        second["environment"]["dependencies"]
    )
    assert (
        second["profiles"]["file_tools"]["profile_hash"]
        != second["profiles"]["core_modules"]["profile_hash"]
    )
    assert str(source) not in json.dumps(second) and sys.executable not in json.dumps(
        second
    )


def test_snapshot_hash_binds_effective_profile_code(source, tmp_path, monkeypatch):
    module = api()
    first = snapshot(source)
    fake_repo = tmp_path / "harness"
    # Copy only hash inputs into a fixture repository, never modify real code.
    monkeypatch.setattr(module, "_REPO_ROOT", fake_repo)
    for profile in first["profiles"].values():
        for name in profile["code_hashes"]:
            path = fake_repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("changed implementation\n")
    changed = snapshot(source)
    assert (
        changed["profiles"]["file_tools"]["adapter_sha256"]
        != first["profiles"]["file_tools"]["adapter_sha256"]
    )
    assert changed["snapshot_hash"] != first["snapshot_hash"]


@pytest.mark.parametrize(
    "extra",
    [{"api_key": "SECRET"}, {"base_url": "secret"}, {"config_path": "/private/config"}],
)
def test_snapshot_rejects_unneeded_or_secret_config(source, extra):
    with pytest.raises(ValueError, match="config"):
        api().snapshot_nanobot(
            {"nanobot_root": str(source), "python": sys.executable, **extra}
        )


@pytest.fixture
def catalog():
    return {
        "version": "test-catalog-v1",
        "capabilities": [
            {
                "id": "file_tools",
                "title": "文件工具",
                "priority": "P0",
                "source_paths": ["nanobot/agent.py"],
                "profiles": {"file_tools": True, "core_modules": False},
                "scenarios": ["读取后检查独立文件状态"],
                "success_conditions": ["已声明终态正确"],
                "evidence_requirements": ["工具事件及独立快照"],
                "family_prefixes": ["read_search/"],
            }
        ],
    }


@pytest.fixture
def dataset(tmp_path):
    from eval_framework.benchmark.tasks import dataset_identity

    path = tmp_path / "dataset"
    path.mkdir()
    task = {
        "id": "dev",
        "family": "read_search/dev",
        "category": "read_search",
        "split": "dev",
        "description": "Fixture read",
        "prompt": "Read x",
        "followups": [],
        "fixtures": {"x": "value"},
        "oracle": {
            "expected_files": {"x": "value"},
            "absent_files": [],
            "response_contains": [],
            "preserve_other_files": True,
            "forbid_extra_files": True,
        },
        "required_tools": ["read_file"],
        "allowed_tools": ["read_file"],
        "max_steps": 3,
        "reference": [{"op": "read", "path": "x"}],
    }
    holdout = {
        **deepcopy(task),
        "id": "holdout",
        "family": "read_search/holdout",
        "split": "holdout",
    }
    raw = "\n".join(json.dumps(t) for t in [task, holdout]) + "\n"
    (path / "tasks.jsonl").write_text(raw)
    manifest = {
        "dataset_id": "coverage-fixture",
        "contract_version": "file-tools-task-v1",
        "grader_version": "file-tools-oracle-v1",
        "tasks_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "case_count": 2,
        "category_counts": {"read_search": 2},
        "split_counts": {"dev": 1, "holdout": 1},
    }
    (path / "manifest.json").write_text(json.dumps(manifest))
    identity = dataset_identity(path)
    return {
        "path": str(path),
        "kind": "file_tools",
        "identity": identity,
        "identity_hash": digest(identity),
        "profile": "file_tools",
    }


def saved_run(tmp_path, snap, dataset, *, legacy=False):
    from eval_framework.benchmark.metrics import score_task
    from eval_framework.benchmark.tasks import load_tasks

    task = load_tasks(Path(dataset["path"]))[0]
    profile = snap["profiles"]["file_tools"]
    identity = {
        "dataset": dataset["identity"],
        "snapshot": snap["snapshot_hash"],
        "profile": "file_tools",
        "profile_hash": profile["profile_hash"],
        "adapter_sha256": profile["adapter_sha256"],
        "scoring_sha256": profile["scoring_sha256"],
    }
    if legacy:
        identity = {
            "dataset": dataset["identity"],
            "scoring_version": "file-tools-deepeval-v2.1",
            "runtime": {
                "agent": "nanobot",
                "source_commit": "old",
                "working_tree_sha256": "old",
            },
        }
    obs = {
        "status": "completed",
        "execution_kind": "real_agent",
        "evidence_complete": True,
        "runtime_identity": {
            "snapshot": snap["snapshot_hash"],
            "profile": "file_tools",
            **{
                k: profile[k]
                for k in ("profile_hash", "adapter_sha256", "scoring_sha256")
            },
            "source_sha256": snap["source"]["working_tree_sha256"],
            "dependencies_sha256": snap["environment"]["dependencies_sha256"],
        },
        "before_files": {"x": "value"},
        "final_files": {"x": "value"},
        "turns": [{"input": task["prompt"], "output": "value"}],
        "usage": {},
        "errors": [],
        "events": [
            {
                "id": "tool-1",
                "type": "tool",
                "name": "read_file",
                "input": {"path": "x"},
                "output": "value",
                "execution_started": True,
                "is_error": False,
                "start_time": "2026-11-02T00:00:00Z",
                "end_time": "2026-11-02T00:00:01Z",
            }
        ],
    }
    run = {
        "run_id": "legacy" if legacy else "current",
        "identity": identity,
        "identity_hash": digest(identity),
        "planned_case_ids": ["dev"],
        "trials_per_case": 1,
        "trials": [
            {
                "case_id": "dev",
                "trial": 1,
                "identity_hash": digest(identity),
                "observation": obs,
                "assessment": score_task(task, obs),
            }
        ],
    }
    path = tmp_path / (run["run_id"] + ".json")
    path.write_text(json.dumps(run))
    return run, {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "kind": "legacy" if legacy else "current",
    }


def rewrite(run, descriptor):
    path = Path(descriptor["path"])
    path.write_text(json.dumps(run))
    descriptor["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def row(report):
    return next(
        row
        for row in report["matrix"]
        if row["capability"] == "file_tools" and row["profile"] == "file_tools"
    )


def test_coverage_separates_execution_holdout_and_human_review(
    tmp_path, source, catalog, dataset
):
    snap = snapshot(source)
    _, run = saved_run(tmp_path, snap, dataset)
    result = api().build_coverage_report(snap, catalog, [dataset], [run])
    item = row(result)
    assert (
        item["source_present"]
        and item["enabled_in_profile"]
        and item["dataset_defined"]
    )
    assert item["executed"] and item["passed"] and item["human_reviewed"] is False
    assert item["splits"]["dev"]["executed_trials"] == 1
    assert item["splits"]["holdout"]["defined_cases"] == 1
    assert item["splits"]["holdout"]["executed_trials"] == 0
    assert item["splits"]["holdout"]["status"] == "not_executed"
    assert "overall_coverage" not in result
    assert str(tmp_path) not in json.dumps(result)


def test_defined_dataset_is_not_executed_without_run(source, catalog, dataset):
    item = row(api().build_coverage_report(snapshot(source), catalog, [dataset], []))
    assert item["dataset_defined"] and not item["executed"] and not item["passed"]


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "identity",
        "snapshot",
        "profile",
        "unplanned",
        "fractional_trial",
        "reference",
        "fake_pass",
    ],
)
def test_invalid_execution_claims_are_rejected(
    tmp_path, source, catalog, dataset, change
):
    snap = snapshot(source)
    run, desc = saved_run(tmp_path, snap, dataset)
    if change == "duplicate":
        run["trials"].append(deepcopy(run["trials"][0]))
    if change == "identity":
        run["trials"][0]["identity_hash"] = "wrong"
    if change in {"snapshot", "profile"}:
        run["identity"][change] = "wrong"
        run["identity_hash"] = digest(run["identity"])
        run["trials"][0]["identity_hash"] = run["identity_hash"]
    if change == "unplanned":
        run["trials"][0]["case_id"] = "holdout"
    if change == "fractional_trial":
        run["trials"][0]["trial"] = 1.5
    if change == "reference":
        run["trials"][0]["observation"]["execution_kind"] = (
            "deterministic_reference_not_agent"
        )
    if change == "fake_pass":
        run["trials"][0]["observation"]["final_files"] = {"x": "wrong"}
    rewrite(run, desc)
    with pytest.raises(ValueError):
        api().build_coverage_report(snap, catalog, [dataset], [desc])


def test_missing_observation_is_not_executed_even_with_scored_assessment(
    tmp_path, source, catalog, dataset
):
    snap = snapshot(source)
    run, desc = saved_run(tmp_path, snap, dataset)
    run["trials"][0]["observation"]["evidence_complete"] = False
    run["trials"][0]["assessment"] = {
        "verdict": "INCONCLUSIVE",
        "validity": "VALID",
        "metrics": [],
    }
    rewrite(run, desc)
    item = row(api().build_coverage_report(snap, catalog, [dataset], [desc]))
    assert not item["executed"] and not item["passed"]
    assert item["splits"]["dev"]["observed_trials"] == 1


def test_run_and_dataset_source_tampering_rejected(tmp_path, source, catalog, dataset):
    snap = snapshot(source)
    _, desc = saved_run(tmp_path, snap, dataset)
    Path(desc["path"]).write_text("{}")
    with pytest.raises(ValueError, match="hash|Hash"):
        api().build_coverage_report(snap, catalog, [dataset], [desc])
    dataset["identity"]["dataset_id"] = "fake"
    dataset["identity_hash"] = digest(dataset["identity"])
    with pytest.raises(ValueError, match="identity"):
        api().build_coverage_report(snap, catalog, [dataset], [])


def test_legacy_run_keeps_own_identity_and_never_upgrades_current_profile(
    tmp_path, source, catalog, dataset
):
    snap = snapshot(source)
    _, desc = saved_run(tmp_path, snap, dataset, legacy=True)
    report = api().build_coverage_report(snap, catalog, [dataset], [desc])
    assert not row(report)["executed"]
    assert report["legacy_runs"][0]["identity_hash"]
    assert report["legacy_runs"][0]["not_bound_to_current_profile"] is True


def test_duplicate_source_run_rejected(tmp_path, source, catalog, dataset):
    snap = snapshot(source)
    _, desc = saved_run(tmp_path, snap, dataset)
    with pytest.raises(ValueError, match="duplicate"):
        api().build_coverage_report(snap, catalog, [dataset], [desc, desc])


def test_catalog_has_explicit_out_of_scope_domains_and_review_boundaries():
    catalog = json.loads((ROOT / "data/coverage/nanobot-v1/catalog.json").read_text())
    domains = {item["id"] for item in catalog["capabilities"]}
    assert {
        "file_tools",
        "memory",
        "session",
        "context",
        "skills",
        "shell",
        "web",
        "mcp",
        "channels",
        "cron",
        "subagent",
        "plugins",
    } <= domains
    assert all(
        item["priority"]
        and item["scenarios"]
        and item["success_conditions"]
        and item["evidence_requirements"]
        for item in catalog["capabilities"]
    )


def test_snapshot_pins_import_origin_and_skill_template_bytes(source):
    (source / "nanobot/skills/example").mkdir(parents=True)
    (source / "nanobot/skills/example/SKILL.md").write_text("skill source")
    (source / "nanobot/template.j2").write_text("{{ name }}")
    value = snapshot(source)
    assert (
        value["environment"]["source_import_identity"]["relative_path"]
        == "nanobot/__init__.py"
    )
    assert (
        value["environment"]["source_import_identity"]["sha256"]
        == value["source"]["files"]["nanobot/__init__.py"]
    )
    assert "nanobot/skills/example/SKILL.md" in value["source"]["files"]
    assert "nanobot/template.j2" in value["source"]["files"]
    assert value["environment"]["dependency_identity_scope"] == (
        "installed distribution names and versions; "
        "editable dependency contents not hashed"
    )


def test_observation_runtime_identity_cannot_disagree_with_snapshot(
    tmp_path, source, catalog, dataset
):
    snap = snapshot(source)
    run, desc = saved_run(tmp_path, snap, dataset)
    run["trials"][0]["observation"]["runtime_identity"]["snapshot"] = "another-source"
    rewrite(run, desc)
    with pytest.raises(ValueError, match="runtime identity"):
        api().build_coverage_report(snap, catalog, [dataset], [desc])


def test_core_profile_binds_execution_and_snapshot_helpers(source):
    value = snapshot(source)
    required = {
        "capability_coverage.py",
        "core_runner.py",
        "core_worker.py",
        "core_tasks.py",
        "inspect_runtime.py",
        "nanobot_runtime.py",
        "runner.py",
        "inspect_docker.py",
    }
    keys = value["profiles"]["core_modules"]["code_hashes"]
    assert required <= {Path(key).name for key in keys}


def test_current_profile_rejects_legacy_decision_but_legacy_retains_it(
    tmp_path, source, catalog, dataset
):
    snap = snapshot(source)
    current, descriptor = saved_run(tmp_path, snap, dataset)
    current["trials"][0]["observation"]["execution_kind"] = "real_model_decision"
    rewrite(current, descriptor)
    with pytest.raises(ValueError, match="execution kind"):
        api().build_coverage_report(snap, catalog, [dataset], [descriptor])
    legacy, descriptor = saved_run(tmp_path, snap, dataset, legacy=True)
    legacy["trials"][0]["observation"]["execution_kind"] = "real_model_decision"
    rewrite(legacy, descriptor)
    report = api().build_coverage_report(snap, catalog, [dataset], [descriptor])
    assert report["legacy_runs"][0]["not_bound_to_current_profile"] is True
    assert row(report)["executed"] is False


def test_real_core_dataset_maps_components_without_implying_execution(source):
    from eval_framework.benchmark.core_tasks import core_dataset_identity

    path = ROOT / "data/benchmarks/nanobot-core-v1"
    identity = core_dataset_identity(path / "tasks.jsonl")
    descriptor = {
        "path": str(path),
        "kind": "core",
        "identity": identity,
        "identity_hash": digest(identity),
        "profile": "core_modules",
    }
    catalog = json.loads((ROOT / "data/coverage/nanobot-v1/catalog.json").read_text())
    report = api().build_coverage_report(snapshot(source), catalog, [descriptor], [])
    rows = [
        r
        for r in report["matrix"]
        if r["profile"] == "core_modules" and r["dataset_defined"]
    ]
    assert {r["capability"] for r in rows} == {"memory", "session", "context", "skills"}
    assert sum(r["splits"]["dev"]["defined_cases"] for r in rows) == 24
    assert sum(r["splits"]["holdout"]["defined_cases"] for r in rows) == 8
    assert all(not r["executed"] and not r["human_reviewed"] for r in rows)
    assert all(r["splits"]["holdout"]["status"] == "not_executed" for r in rows)


def test_snapshot_also_binds_harness_python_and_dependencies(source):
    value = snapshot(source)
    harness = value["harness_environment"]
    assert harness["python_version"]
    assert harness["python_binary_sha256"]
    assert harness["dependencies_sha256"] == digest(harness["dependencies"])
    assert {"inspect-ai", "deepeval"} <= {
        d["name"].lower().replace("_", "-") for d in harness["dependencies"]
    }
    assert sys.executable not in json.dumps(harness)


@pytest.mark.parametrize(
    "start,end,complete",
    [
        (1793592000.125, 1793592000.25, True),
        (1793592000, 1793592000, True),
        (1793592001.0, 1793592000.0, False),
        (float("nan"), 1793592000.0, False),
        (1793592000.0, float("inf"), False),
        (True, 1793592000.0, False),
        (1793592000.0, False, False),
        (None, 1793592000.0, False),
        ("1793592000.0", "1793592001.0", False),
    ],
)
def test_core_worker_numeric_timestamps_have_strict_execution_semantics(
    start, end, complete
):
    observation = {
        "execution_kind": "real_core_module",
        "status": "completed",
        "evidence_complete": True,
        "before_files": {},
        "final_files": {},
        "events": [
            {
                "id": "op-1",
                "type": "module",
                "operation": "memory.read",
                "input": {"since_cursor": 0},
                "output": [],
                "error": None,
                "start_time": start,
                "end_time": end,
                "incomplete": False,
            }
        ],
    }
    assert api()._complete(observation, "core") is complete
    observation["events"][0].update(type="tool", execution_started=True)
    assert api()._complete(observation, "file_tools") is False


@pytest.mark.parametrize(
    "layout", ["file_link", "parent_link", "ignored_python", "extension"]
)
def test_snapshot_rejects_importable_source_omitted_from_manifest(source, layout):
    if layout == "file_link":
        target = source / "linked_source.py"
        target.write_text("VALUE = 2\n")
        (source / "nanobot/linked.py").symlink_to(target)
    elif layout == "parent_link":
        target = source / "linked_package"
        target.mkdir()
        (target / "child.py").write_text("VALUE = 2\n")
        (source / "nanobot/linked_package").symlink_to(target, target_is_directory=True)
    elif layout == "ignored_python":
        (source / ".gitignore").write_text("nanobot/ignored.py\n")
        (source / "nanobot/ignored.py").write_text("VALUE = 2\n")
    else:
        import importlib.machinery

        extension = importlib.machinery.EXTENSION_SUFFIXES[0]
        (source / "nanobot" / ("native" + extension)).write_bytes(b"fixture binary")
    with pytest.raises(ValueError, match="unsupported import source"):
        snapshot(source)


def test_snapshot_import_check_ignores_cache_and_nonexecuting_resources(source):
    (source / "nanobot/__pycache__").mkdir()
    (source / "nanobot/__pycache__/cached.py").write_text("ignored cache")
    (source / ".gitignore").write_text("__pycache__/\nnanobot/image.png\n")
    (source / "nanobot/image.png").write_bytes(b"image")
    (source / "nanobot/image-link.png").symlink_to(source / "nanobot/image.png")
    resource = source / "resource_directory"
    resource.mkdir()
    (resource / "image.png").write_bytes(b"image")
    (source / "nanobot/assets").symlink_to(resource, target_is_directory=True)
    assert snapshot(source)["profiles"]["core_modules"]["available"] is True


def test_snapshot_rejects_cyclic_parent_link_with_importable_children(source):
    (source / "nanobot/alias").symlink_to(source / "nanobot", target_is_directory=True)
    with pytest.raises(ValueError, match="unsupported import source"):
        snapshot(source)


def test_snapshot_rejects_direct_bytecode_outside_pycache(source):
    (source / "nanobot/direct.pyc").write_bytes(b"unbound direct bytecode")
    with pytest.raises(ValueError, match="unsupported import source"):
        snapshot(source)
