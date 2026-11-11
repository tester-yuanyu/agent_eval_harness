"""P0 使用原生 Harness 和确定性本地模型替身，禁止真实 API。"""

import json


def dataset(tmp_path, *, expected="hello\n", path="input.txt"):
    target = tmp_path / "dataset.json"
    target.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "cases": [
                    {
                        "case_id": "read-1",
                        "prompt": "读取 input.txt。",
                        "fixtures": {"input.txt": "hello\n"},
                        "reference_path": path,
                        "expected_output": expected,
                    }
                ],
            }
        )
    )
    return target


def test_native_read_file_produces_complete_evidence_without_oracle(tmp_path):
    from eval_framework.benchmark.readiness import run

    proof = run(
        dataset(tmp_path, expected="PRIVATE_ORACLE_SENTINEL"), tmp_path / "logs"
    )
    row = proof.results[0]
    assert row.status == "completed"
    assert row.evidence_complete
    assert row.executed_tools == ["read_file"]
    assert row.final_output == "hello\n"
    assert row.before_files == row.final_files == {"input.txt": "hello\n"}
    assert not row.errors
    from inspect_ai.log import read_eval_log

    logs = list((tmp_path / "logs").glob("*.eval"))
    assert len(logs) == 1
    log = read_eval_log(str(logs[0]))
    assert log.samples[0].target == ""
    assert "PRIVATE_ORACLE_SENTINEL" not in log.model_dump_json()


def test_failed_tool_does_not_produce_success_evidence(tmp_path):
    from eval_framework.benchmark.readiness import run

    proof = run(dataset(tmp_path, path="missing.txt"), tmp_path / "logs")
    assert proof.results[0].errors


def test_identity_binds_source_and_runtime():
    from eval_framework.benchmark.readiness import identity

    value = identity()
    assert value == identity()
    assert len(value.implementation_sha256) == 64
    assert value.runtime["inspect-ai"]
