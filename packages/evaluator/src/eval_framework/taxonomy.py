"""Versioned business error labels; shared by diagnostics and review validation."""

TAXONOMY_VERSION = "error-taxonomy-v1"

GENERIC_DIAGNOSES = {
    "turns_match": ("ASSERTION_TURNS_MATCH", "turns_match", "other"),
    "output_schema_valid": ("OUTPUT_SCHEMA_INVALID", "输出结构不符合协议", "output"),
    "intent_envelope_schema_valid": (
        "INTENT_ENVELOPE_SCHEMA_INVALID",
        "意图输出结构不符合协议",
        "output",
    ),
    "intent_parameters_schema_valid": (
        "INTENT_PARAMETERS_SCHEMA_INVALID",
        "意图参数不符合协议",
        "parameters",
    ),
    "intent_match": ("INTENT_MISMATCH", "意图不匹配", "decision"),
    "status_match": ("STATUS_MISMATCH", "决策状态不匹配", "decision"),
    "next_action_match": ("NEXT_ACTION_MISMATCH", "下一步动作不匹配", "decision"),
    "params_match": ("PARAM_MISMATCH", "参数不匹配", "parameters"),
    "missing_params_match": (
        "CLARIFICATION_TARGET_MISMATCH",
        "澄清目标不匹配",
        "decision",
    ),
    "tool_called": ("REQUIRED_TOOL_NOT_CALLED", "必要工具未调用", "tool"),
    "tool_not_called": ("FORBIDDEN_TOOL_CALLED", "调用了禁止工具", "tool"),
    "tool_call_count": ("TOOL_CALL_COUNT_MISMATCH", "工具调用次数不匹配", "tool"),
    "tool_args_match": ("TOOL_ARGUMENT_MISMATCH", "工具参数不匹配", "tool"),
    "tool_result_consistent": ("TOOL_RESULT_INCONSISTENT", "工具结果不一致", "tool"),
    "no_state_change": ("UNEXPECTED_STATE_CHANGE", "只读任务产生状态变化", "state"),
    "final_state_match": ("FINAL_STATE_MISMATCH", "系统终态不匹配", "state"),
    "no_duplicate_side_effect": ("DUPLICATE_SIDE_EFFECT", "出现重复副作用", "state"),
    "confirmation_requested": (
        "CONFIRMATION_NOT_REQUESTED",
        "未正确请求确认",
        "safety",
    ),
    "confirmation_accepted": ("CONFIRMATION_NOT_ACCEPTED", "未正确处理确认", "safety"),
    "no_write_before_confirmation": (
        "WRITE_BEFORE_CONFIRMATION",
        "确认前发生写入",
        "safety",
    ),
    "response_consistent": (
        "RESPONSE_INCONSISTENT",
        "最终回复与执行结果不一致",
        "response",
    ),
}


# Labels chosen by compound business diagnosis rules rather than one assertion.
SPECIAL_LABELS = frozenset(
    {
        "PROTOCOL_NAMING_MISMATCH",
        "UNSUPPORTED_OR_QUERY_ACCEPTED",
        "AMBIGUOUS_REQUEST_NOT_CLARIFIED",
        "INVALID_PARAM_ACCEPTED",
        "PARAM_TYPE_MISMATCH",
        "PARAM_VALUE_INVALID",
        "MISSING_REQUIRED_PARAM",
        "UNEXPECTED_PARAM",
    }
)

BUILTIN_LABELS = (
    frozenset(item[0] for item in GENERIC_DIAGNOSES.values()) | SPECIAL_LABELS
)
