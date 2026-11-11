"""版本扩展不得重写旧 reference 请求的内容身份。"""

import json

import pytest
from eval_contracts.full_readiness import FullRequest
from eval_contracts.readiness import digest_bytes


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_historical_request_hash_uses_original_version_fields(version):
    raw = {
        "schema_version": "builder-full-readiness-" + version,
        "source_manifest_sha256": "a" * 64,
        "bundle_sha256": "b" * 64,
        "source_files": {"manifest.json": "c" * 64},
        "definition_counts": {"behavior_case": 1},
        "tool_schema": {},
        "cases": [
            {
                "case_id": "one",
                "source_path": "cases.jsonl",
                "payload": {"case_id": "one"},
            }
        ],
    }
    if version == "v2":
        raw["target_schemas"] = {"intent.example": {"type": "object"}}
    expected = digest_bytes(
        json.dumps(
            raw, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    )
    parsed = FullRequest.model_validate(raw)
    assert parsed.sha256() == expected
