from __future__ import annotations

from pathlib import Path

import pytest

from capability_snapshot_kit.spec_loader import (
    CapabilitySpecLoadErrorV3,
    load_capability_spec_pack_v3,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPEC_ROOT = PROJECT_ROOT / "capability_specs"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _protocol(root: Path) -> None:
    _write(
        root / "protocol.md",
        """---
spec_id: protocol.capability_v3
version: "1.0"
snapshot_format_version: "3.0"
agent_capability_groups: {}
---
# Protocol

Portable protocol documentation.
""",
    )


def _scope(snapshot_id: str, evidence_id: str = "evidence.intent_result") -> str:
    return f"""---
snapshot_id: {snapshot_id}
description: Test scope.
inputs: [user_input]
outputs: [intent_result]
entrypoint_binding: entrypoint.intent_only
stop_binding: node.intent_decided
module_roles: [intent_routing]
evidence_ids: [{evidence_id}]
boundary_id: boundary.understanding
requirements: []
completion_condition: Complete.
unresolved_behavior: Unknown remains unknown.
---
# Scope

Human-readable scope rules.
"""


def _boundary() -> str:
    return """---
snapshot_id: boundary.understanding
description: Test boundary.
entry_binding: entrypoint.intent_only
stop_binding: node.intent_decided
module_roles: [intent_routing]
evidence_ids: [evidence.intent_result]
terminal_condition_template: The {stop_node} node is reached.
no_overrun_rule_template: No node after {stop_node} may execute.
---
# Boundary

Human-readable boundary rules.
"""


def _evidence() -> str:
    return """---
snapshot_id: evidence.intent_result
description: Intent decision evidence.
consumer_roles: [builder, evaluator]
required: true
applicable_result_paths: [success]
---
# Evidence

Human-readable evidence rules.
"""


def test_checked_in_spec_pack_loads_expected_ids_and_counts() -> None:
    pack = load_capability_spec_pack_v3(SPEC_ROOT)

    assert set(pack.scopes) == {
        "scope.understanding",
        "scope.context",
        "scope.planning_execution",
        "scope.safety_recovery",
        "scope.result",
    }
    assert set(pack.chains) == {
        "chain.understanding_to_planning",
        "chain.planning_to_result",
        "chain.end_to_end",
    }
    assert len(pack.evidence) == 5
    assert len(pack.boundaries) == 7


def test_yaml_python_object_tag_is_rejected_without_execution(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "must-not-exist"
    _write(
        tmp_path / "protocol.md",
        f"""---
!!python/object/apply:pathlib.Path.touch
- {marker}
---
# Unsafe
""",
    )

    with pytest.raises(CapabilitySpecLoadErrorV3, match="unsafe|YAML|mapping"):
        load_capability_spec_pack_v3(tmp_path)

    assert not marker.exists()


def test_duplicate_spec_id_is_rejected(tmp_path: Path) -> None:
    _protocol(tmp_path)
    _write(tmp_path / "scopes" / "one.md", _scope("scope.understanding"))
    _write(tmp_path / "scopes" / "two.md", _scope("scope.understanding"))
    _write(tmp_path / "evidence" / "intent_result.md", _evidence())
    _write(tmp_path / "boundaries" / "understanding.md", _boundary())

    with pytest.raises(
        CapabilitySpecLoadErrorV3,
        match="duplicate.*scope.understanding",
    ):
        load_capability_spec_pack_v3(tmp_path)


def test_broken_evidence_or_boundary_reference_is_rejected(tmp_path: Path) -> None:
    _protocol(tmp_path)
    _write(
        tmp_path / "scopes" / "understanding.md",
        _scope("scope.understanding", evidence_id="evidence.missing"),
    )
    _write(tmp_path / "evidence" / "intent_result.md", _evidence())
    _write(tmp_path / "boundaries" / "understanding.md", _boundary())

    with pytest.raises(CapabilitySpecLoadErrorV3, match="evidence.missing"):
        load_capability_spec_pack_v3(tmp_path)


def test_markdown_body_is_required_but_never_compiled_as_fields(
    tmp_path: Path,
) -> None:
    _protocol(tmp_path)
    _write(
        tmp_path / "evidence" / "intent_result.md",
        _evidence().replace(
            "Human-readable evidence rules.",
            "support_status: supported belongs only to this prose.",
        ),
    )
    pack = load_capability_spec_pack_v3(tmp_path)

    dumped = pack.evidence["evidence.intent_result"].model_dump(mode="json")
    assert "documentation" not in dumped
    assert "support_status" not in dumped

    _write(
        tmp_path / "evidence" / "intent_result.md",
        _evidence().split("\n---\n", 1)[0] + "\n---\n",
    )
    with pytest.raises(CapabilitySpecLoadErrorV3, match="Markdown body"):
        load_capability_spec_pack_v3(tmp_path)
