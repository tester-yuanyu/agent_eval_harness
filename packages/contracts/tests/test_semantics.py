import pytest


def test_semantics_protocol_accepts_agent_owned_descriptor_without_agent_imports():
    from capability_snapshot_kit.semantics import describe_semantics

    class Rule:
        def snapshot_semantics(self):
            return {
                "component_id": "other_agent.rule",
                "version": "1",
                "parameters": {"fields": ["x"], "enabled": True},
            }

    assert describe_semantics(Rule())["parameters"] == {
        "fields": ["x"],
        "enabled": True,
    }


@pytest.mark.parametrize("value", [object(), {"value": float("nan")}, {1: "value"}])
def test_semantics_rejects_non_json_configuration(value):
    from capability_snapshot_kit.semantics import validate_semantics

    with pytest.raises(ValueError):
        validate_semantics(
            {"component_id": "rule", "version": "1", "parameters": {"config": value}}
        )


def test_custom_rule_must_explicitly_describe_semantics():
    from capability_snapshot_kit.semantics import describe_semantics

    with pytest.raises(ValueError, match="snapshot_semantics"):
        describe_semantics(object())


def test_model_instance_cannot_bypass_json_validation():
    from capability_snapshot_kit.semantics import SemanticDescriptor, validate_semantics

    unsafe = SemanticDescriptor.model_construct(
        component_id="bad", version="1", parameters={"number": float("nan")}
    )
    with pytest.raises(ValueError, match="dictionary"):
        validate_semantics(unsafe)
