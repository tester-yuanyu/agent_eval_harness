"""Small shared preflight gate also used through Builder's evaluator gate."""

_REQUIREMENTS = {
    "output_schema_valid": ("intent_result", None),
    "intent_envelope_schema_valid": ("intent_result", None),
    "intent_parameters_schema_valid": ("intent_result", None),
    "intent_match": ("intent_result", None),
    "next_action_match": ("intent_result", None),
    "params_match": ("intent_result", None),
    "missing_params_match": ("intent_result", None),
    "tool_called": ("tool_trace", "tool_requested"),
    "tool_not_called": ("tool_trace", "tool_requested"),
    "tool_call_count": ("tool_trace", "tool_requested"),
    "tool_args_match": ("tool_trace", "tool_requested"),
    "tool_result_consistent": ("tool_trace", "tool_succeeded"),
    "confirmation_requested": ("safety_recovery_event", "confirmation_required"),
    "confirmation_accepted": ("safety_recovery_event", "confirmation_accepted"),
    "no_write_before_confirmation": ("context_state", None),
    "no_state_change": ("context_state", None),
    "final_state_match": ("context_state", None),
    "no_duplicate_side_effect": ("context_state", None),
    "response_consistent": ("final_response", None),
}

_EVENT_FIELDS = {
    "tool_requested": {"call_id", "name", "arguments"},
    "tool_succeeded": {"call_id", "name", "output"},
    "confirmation_required": {"response"},
    "confirmation_accepted": set(),
}


def _delivery_issues(delivery, event):
    if not isinstance(delivery, dict):
        return ["delivery declaration missing"]
    errors = []
    for field in ("correlation",):
        value = delivery.get(field)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            return [f"invalid evidence {field}"]
    if not isinstance(delivery.get("events"), dict):
        return ["invalid evidence event rules"]
    if delivery.get("version") != "1.0" or delivery.get("protocol_version") != "1.0":
        errors.append("unsupported evidence delivery/protocol version")
    if delivery.get("independent_interface") != "agent_trace_sdk.EvidenceReader.read":
        errors.append("unsupported independent evidence interface")
    if not isinstance(delivery.get("event_rules_version"), str) or not delivery.get(
        "event_rules_version"
    ):
        errors.append("event rules version missing")
    if not {"trace_id", "run_id", "turn_index"} <= set(delivery.get("correlation", [])):
        errors.append("evidence correlation fields missing")
    if event is not None:
        rule = delivery.get("events", {}).get(event, {})
        if not isinstance(rule, dict):
            return [f"invalid event rule: {event}"]
        for field in ("required_fields", "allowed_fields"):
            value = rule.get(field, [])
            if not isinstance(value, list) or not all(
                isinstance(v, str) for v in value
            ):
                return [f"invalid event rule {event}.{field}"]
        fields = _EVENT_FIELDS.get(event, set())
        if not rule or not fields <= set(rule.get("required_fields", [])):
            errors.append(f"{event}: required payload fields missing")
        if not fields <= set(rule.get("allowed_fields", [])):
            errors.append(f"{event}: payload fields not collectable")
    return errors


def evidence_requirement_issues(
    case, capabilities, *, environment_state_available=False
):
    observation_issues = [
        "observations_match: independent environment evidence is unavailable"
        for check in case.oracle.evaluation.checks
        if check.name == "observations_match"
        and check.config.get("channel", "returned") == "independent"
        and not environment_state_available
    ]
    documents = {
        d.snapshot_id: d.payload
        for d in capabilities.bundle.documents
        if d.snapshot_type == "evidence"
    }
    # Frozen legacy contracts have no new delivery declaration. Preserve them.
    if not any(
        "x-evidence-delivery" in d.get("payload_schema", {}) for d in documents.values()
    ):
        return observation_issues
    issues = list(observation_issues)
    for check in case.oracle.evaluation.checks:
        requirement = _REQUIREMENTS.get(check.name)
        turns = check.config.get("turns")
        if (
            check.name == "turns_match"
            and isinstance(turns, list)
            and any(
                isinstance(turn, dict) and turn.get("state") is not None
                for turn in turns
            )
        ):
            requirement = ("context_state", None)
        if check.name == "status_match":
            requirement = (
                "intent_result" if case.test_scope == "module" else "final_response",
                None,
            )
        if requirement is None:
            continue
        evidence_id, event = requirement
        if evidence_id == "context_state" and environment_state_available:
            # State is independently queried by an explicitly configured Provider.
            # This does not claim that the Agent emits context-state evidence.
            continue
        declaration = documents.get(f"evidence.{evidence_id}", {})
        available = declaration.get("availability", {}).get("support_status")
        if available != "supported" or (
            event is not None and event not in declaration.get("event_types", [])
        ):
            issues.append(
                f"{check.name}: required evidence {evidence_id}"
                f"{('/' + event) if event else ''} unavailable"
            )
        delivery = declaration.get("payload_schema", {}).get("x-evidence-delivery")
        # Result assertions read the returned result; do not require its fields
        # to be duplicated by process events in the independent channel.
        issues.extend(
            f"{check.name}: {message}" for message in _delivery_issues(delivery, event)
        )
    return issues
