"""MiniAgent 内置规则到通用语义身份的显式适配。"""

import json
from dataclasses import asdict

from capability_snapshot_kit.semantics import describe_semantics, validate_semantics

from minimal_agent.contracts import intents

# Exact types only: subclasses may change behavior and must declare their own identity.
_BUILTINS = {
    intents.TrimStringNormalizer,
    intents.IntegerStringNormalizer,
    intents.RequiredFields,
    intents.AtLeastOneFieldGroup,
    intents.ExactlyOneFieldGroup,
    intents.MutuallyExclusiveFields,
    intents.RequireMentionedFields,
    intents.DisallowAmbiguousBareInteger,
    intents.DisallowMultipleValuesPerField,
    intents.DisallowAlternativeQuery,
    intents.DisallowBatchQuery,
    intents.ReadIntentPolicy,
    intents.WriteIntentPolicy,
    intents.UnsupportedIntentPolicy,
}


def component_semantics(component):
    if type(component) not in _BUILTINS:
        return describe_semantics(component)
    # These Agent-owned dataclasses contain only explicitly known configuration.
    return validate_semantics(
        {
            "component_id": "mini_agent.intent." + type(component).__name__,
            "version": "1.0",
            "parameters": json.loads(json.dumps(asdict(component), allow_nan=False)),
        }
    )


def intent_semantics(definition):
    return {
        "version": "2.0",
        "normalizers": [component_semantics(item) for item in definition.normalizers],
        "constraints": [
            component_semantics(item) for item in definition.semantic_constraints
        ],
        "completion_policy": component_semantics(definition.completion_policy),
    }
