from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from eval_framework.onboarding import prepare_input


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_delivery(tmp_path, agent_id="another_agent"):
    root = tmp_path / "delivery"
    bundle = root / "source_delivery/bundle"
    module = {
        "snapshot_id": "module.sdk",
        "snapshot_type": "module",
        "snapshot_format_version": "3.0",
        "contract_version": "1.0",
        "module_id": "sdk",
        "input_schema": {"type": "string"},
        "output_schema": {"type": "object"},
    }

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    module["snapshot_sha256"] = hashlib.sha256(canonical(module)).hexdigest()
    write_json(bundle / "modules/sdk.json", module)
    reference = {
        key: module[key]
        for key in (
            "snapshot_id",
            "snapshot_type",
            "snapshot_format_version",
            "contract_version",
            "snapshot_sha256",
        )
    }
    reference["path"] = "modules/sdk.json"
    bundle_hash = hashlib.sha256(canonical([reference])).hexdigest()
    agent = {
        "agent_id": agent_id,
        "agent_version": "1.0",
        "snapshot_id": f"agent.{agent_id}",
        "snapshot_type": "agent",
        "snapshot_format_version": "3.0",
        "contract_version": "1.0",
        "capability_bundle_sha256": bundle_hash,
        "module_refs": [reference],
        **{
            f"{kind}_refs": []
            for kind in ("intent", "tool", "scope", "chain", "evidence", "boundary")
        },
    }
    agent["snapshot_sha256"] = hashlib.sha256(canonical(agent)).hexdigest()
    write_json(bundle / "agent.json", agent)
    for name in ("agent", "module"):
        write_json(bundle / f"schemas/{name}.schema.json", {"type": "object"})
    ref = {
        "path": "bundle/modules/sdk.json",
        "sha256": sha(bundle / "modules/sdk.json"),
        "pointer": "/input_schema",
    }
    base = {
        "schema_version": "1.0",
        "dataset_format": "agent_candidate",
        "agent_id": agent_id,
        "target_id": "module.sdk",
        "layer": "modules",
        "category": "normal",
        "title": "An independently authored SDK case",
        "support_status": "supported",
        "source_basis": "snapshot",
        "runtime_execution": "NOT_RUN",
        "approval": "PENDING",
        "preconditions": [],
        "source_refs": [ref],
        "runner_requirements": [],
        "blocker_ids": [],
    }
    rows = [
        {
            **base,
            "case_id": f"{agent_id}:schema:1",
            "kind": "schema_contract",
            "execution_readiness": "static_only",
            "input": {
                "operation": "validate_schema",
                "schema_ref": ref,
                "instance": 42,
                "invoke_handler": False,
            },
            "oracle": {
                "checks": [
                    {
                        "subject": "schema_validation.valid",
                        "operator": "equals",
                        "expected": False,
                    }
                ]
            },
        },
        {
            **base,
            "case_id": f"{agent_id}:behavior:1",
            "kind": "behavior_candidate",
            "execution_readiness": "needs_runner",
            "input": {"operation": "echo", "value": "actual input"},
            "oracle": {
                "checks": [
                    {
                        "subject": "result.text",
                        "operator": "equals",
                        "expected": "private expected value",
                    }
                ]
            },
        },
        {
            **base,
            "case_id": f"{agent_id}:blocked:1",
            "kind": "blocked_obligation",
            "execution_readiness": "blocked",
            "support_status": "unknown",
            "source_basis": "missing_contract",
            "input": {"operation": "resolve"},
            "oracle": {"checks": []},
        },
    ]
    datasets = []
    for row in rows:
        path = root / f"datasets/{row['kind']}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row) + "\n")
        datasets.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": sha(path),
                "case_count": 1,
                "kind": row["kind"],
                "layer": row["layer"],
                "target_id": row["target_id"],
                "dataset_format": "agent_candidate",
            }
        )
    write_json(root / "blockers.json", [])
    manifest = {
        "schema_version": "1.0",
        "agent_id": agent_id,
        "agent_version": "1.0",
        "dataset_format": "agent_candidate",
        "state": "DRAFT",
        "runtime_execution": "NOT_RUN",
        "approval": "PENDING",
        "bundle_sha256": bundle_hash,
        "case_count": 3,
        "counts_by_kind": {row["kind"]: 1 for row in rows},
        "datasets": datasets,
        "files_sha256": {
            str(p.relative_to(root)): sha(p) for p in root.rglob("*") if p.is_file()
        },
    }
    write_json(root / "manifest.json", manifest)
    return root


def test_candidate_intake_runs_static_and_records_missing_runtime(tmp_path):
    source = make_delivery(tmp_path)
    original = sha(source / "manifest.json")
    prepared = prepare_input(source, tmp_path / "output")
    assert len(prepared.suite_paths) == 1
    assert prepared.report["agent_id"] == "another_agent"
    assert prepared.report["counts"] == {"static": 1, "behavior": 0, "blocked": 2}
    assert prepared.report["release_eligible"] is False
    entries = {item["source_case_id"]: item for item in prepared.report["cases"]}
    assert (
        entries["another_agent:behavior:1"]["reason_code"] == "RUNTIME_BINDING_REQUIRED"
    )
    assert (
        entries["another_agent:blocked:1"]["reason_code"]
        == "MISSING_EXECUTABLE_CONTRACT"
    )
    assert sha(source / "manifest.json") == original


def test_candidate_intake_with_explicit_binding_keeps_oracle_private(tmp_path):
    source = make_delivery(tmp_path)
    binding = {
        "version": "1.0",
        "agent_id": "another_agent",
        "adapter": "stdio",
        "argv": ["/usr/bin/true"],
    }
    prepared = prepare_input(source, tmp_path / "output", binding=binding)
    assert prepared.report["counts"] == {"static": 1, "behavior": 1, "blocked": 1}
    normalized = json.loads((prepared.root / "evaluator/behavior.json").read_text())
    case = normalized["cases"][0]
    assert "private expected value" not in json.dumps(case["execution"])
    assert (
        case["oracle"]["evaluation"]["checks"][0]["config"]["checks"][0]["expected"]
        == "private expected value"
    )
    assert ":" not in case["case_id"]
    assert normalized["metadata"]["total_count"] == 2


def test_zip_delivery_has_same_source_identity(tmp_path):
    source = make_delivery(tmp_path)
    archive = tmp_path / "delivery.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        for path in source.rglob("*"):
            if path.is_file():
                handle.write(path, "top/" + str(path.relative_to(source)))
    first = prepare_input(source, tmp_path / "first")
    second = prepare_input(archive, tmp_path / "second")
    assert (
        first.report["source_manifest_sha256"]
        == second.report["source_manifest_sha256"]
    )
    assert first.report["cases"] == second.report["cases"]


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "folder/../../escape", "a\\b"]
)
def test_zip_rejects_unsafe_paths(tmp_path, name):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(name, "bad")
    with pytest.raises(ValueError, match="path"):
        prepare_input(archive, tmp_path / "output")
    assert not (tmp_path / "escape").exists()


def test_tampered_delivery_is_not_partially_executed(tmp_path):
    source = make_delivery(tmp_path)
    (source / "datasets/schema_contract.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="hash"):
        prepare_input(source, tmp_path / "output")


def test_symlink_is_rejected_before_copy(tmp_path):
    source = make_delivery(tmp_path)
    (source / "external").symlink_to(tmp_path / "outside")
    with pytest.raises(ValueError, match="symlink"):
        prepare_input(source, tmp_path / "output")


def test_binding_identity_must_match_delivery(tmp_path):
    source = make_delivery(tmp_path)
    with pytest.raises(ValueError, match="identity"):
        prepare_input(
            source,
            tmp_path / "output",
            binding={
                "version": "1.0",
                "agent_id": "wrong",
                "adapter": "stdio",
                "argv": ["/usr/bin/true"],
            },
        )


def compile_prepared(prepared):
    from eval_framework.composition import default_plugin_catalog
    from eval_framework.contracts.compiler import compile_suite, load_suite_definition
    from eval_framework.contracts.store import ContractStore

    catalog = default_plugin_catalog()
    compiled = []
    for path in prepared.suite_paths:
        loaded = load_suite_definition(path)
        compiled.append(compile_suite(loaded, catalog, ContractStore(loaded.root)))
    return catalog, compiled


def test_second_agent_compiles_and_executes_with_private_oracle(tmp_path, monkeypatch):
    import sys

    from eval_framework.compiled_execution import execute_compiled_suite

    monkeypatch.setenv("INSPECT_TRACE_FILE", str(tmp_path / "trace.log"))
    source = make_delivery(tmp_path)
    stub = tmp_path / "agent.py"
    stub.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        "assert 'oracle' not in request['execution']\n"
        "assert 'private expected value' not in json.dumps(request)\n"
        "value = request['execution']['adapter_input']['input']['value']\n"
        "print(json.dumps({'protocol_version':'1.0', "
        "'observations':{'result':{'text':value}}}))\n"
    )
    prepared = prepare_input(
        source,
        tmp_path / "output",
        binding={
            "version": "1.0",
            "agent_id": "another_agent",
            "adapter": "stdio",
            "argv": [sys.executable, "-I", str(stub)],
        },
    )
    catalog, suites = compile_prepared(prepared)
    results = [
        execute_compiled_suite(suite, catalog, output_dir=tmp_path / str(index))
        for index, suite in enumerate(suites)
    ]
    assert results[0].cases[0].quality_conclusion == "PASS"
    assert results[1].cases[0].quality_conclusion == "FAIL"
    assert results[1].cases[0].execution_status == "COMPLETED"
    assert results[1].onboarding["release_eligible"] is False
    assert suites[1].dataset.total_count == 2
    assert suites[1].dataset.lifecycle_state == "DRAFT"


def test_compilation_rejects_changed_bound_source(tmp_path):
    from eval_framework.contracts.compiler import SuiteCompilationError

    prepared = prepare_input(make_delivery(tmp_path), tmp_path / "output")
    (prepared.root / "blockers.json").write_text("[1]")
    with pytest.raises(SuiteCompilationError, match="SOURCE_FINGERPRINT_MISMATCH"):
        compile_prepared(prepared)


def test_no_behavior_oracle_can_claim_independent_state(tmp_path):
    from eval_framework.onboarding.candidates import translate
    from eval_framework.onboarding.delivery import read_delivery
    from eval_framework.providers.external import RuntimeBinding

    source = make_delivery(tmp_path)
    manifest, rows = read_delivery(source)
    behavior = next(row for row in rows if row.kind == "behavior_candidate")
    behavior.oracle.checks[0].subject = "workspace.files.result"
    case, ledger = translate(
        behavior,
        source,
        manifest,
        RuntimeBinding(
            version="1.0",
            agent_id="another_agent",
            adapter="stdio",
            argv=["/usr/bin/true"],
        ),
    )
    assert case is None
    assert ledger["reason_code"] == "INDEPENDENT_EVIDENCE_REQUIRED"


def test_source_pointer_is_verified_before_intake(tmp_path):
    from eval_framework.onboarding.delivery import pointer_value

    assert pointer_value({"a/b": {"~key": None}}, "/a~1b/~0key") is None
    with pytest.raises(ValueError, match="pointer"):
        pointer_value({"items": [1]}, "/items/01")


@pytest.mark.parametrize(
    "readiness", ["static_only", "blocked", "unknown_future_value"]
)
def test_behavior_requires_explicit_executable_readiness(tmp_path, readiness):
    from eval_framework.onboarding.candidates import translate
    from eval_framework.onboarding.delivery import read_delivery
    from eval_framework.providers.external import RuntimeBinding

    source = make_delivery(tmp_path)
    manifest, rows = read_delivery(source)
    behavior = next(row for row in rows if row.kind == "behavior_candidate")
    behavior.execution_readiness = readiness
    case, ledger = translate(
        behavior,
        source,
        manifest,
        RuntimeBinding(
            version="1.0",
            agent_id="another_agent",
            adapter="stdio",
            argv=["/usr/bin/true"],
        ),
    )
    assert case is None
    assert ledger["reason_code"] == "SOURCE_EXECUTION_BLOCKED"


@pytest.mark.parametrize("claim", [None, {"release_eligible": True}])
def test_authored_candidate_suite_cannot_remove_provisional_provenance(tmp_path, claim):
    from eval_framework.contracts.compiler import SuiteCompilationError

    prepared = prepare_input(make_delivery(tmp_path), tmp_path / "output")
    normalized = prepared.root / "evaluator/static.json"
    document = json.loads(normalized.read_text())
    if claim is None:
        document["metadata"].pop("onboarding")
    else:
        document["metadata"]["onboarding"].update(claim)
    document["metadata"]["lifecycle_state"] = "FROZEN"
    write_json(normalized, document)
    suite_path = prepared.suite_paths[0]
    suite = json.loads(suite_path.read_text())
    suite["dataset_sources"][0]["sha256"] = sha(normalized)
    write_json(suite_path, suite)
    with pytest.raises(SuiteCompilationError, match="provenance"):
        compile_prepared(prepared)


def test_authored_suite_cannot_rewrite_source_code_digest(tmp_path):
    from eval_framework.contracts.compiler import SuiteCompilationError

    source = make_delivery(tmp_path)
    code = source / "source_delivery/sources/another_agent/worker.py"
    code.parent.mkdir(parents=True)
    code.write_text("# source evidence\n")
    row_path = source / "datasets/behavior_candidate.jsonl"
    row = json.loads(row_path.read_text())
    row["source_refs"].append(
        {
            "path": "sources/another_agent/worker.py",
            "sha256": sha(code),
            "anchor": "source evidence",
        }
    )
    row_path.write_text(json.dumps(row) + "\n")
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files_sha256"][code.relative_to(source).as_posix()] = sha(code)
    manifest["files_sha256"][row_path.relative_to(source).as_posix()] = sha(row_path)
    for entry in manifest["datasets"]:
        if entry["kind"] == "behavior_candidate":
            entry["sha256"] = sha(row_path)
    write_json(manifest_path, manifest)
    prepared = prepare_input(
        source,
        tmp_path / "out",
        binding={
            "version": "1.0",
            "agent_id": "another_agent",
            "adapter": "stdio",
            "argv": ["/usr/bin/true"],
        },
    )
    path = prepared.root / "evaluator/behavior.json"
    document = json.loads(path.read_text())
    document["cases"][0]["execution"]["adapter_input"]["source_files"][0]["sha256"] = (
        "0" * 64
    )
    write_json(path, document)
    suite_path = prepared.suite_paths[1]
    suite = json.loads(suite_path.read_text())
    suite["dataset_sources"][0]["sha256"] = sha(path)
    write_json(suite_path, suite)
    with pytest.raises(SuiteCompilationError, match="source code provenance"):
        compile_prepared(prepared)
