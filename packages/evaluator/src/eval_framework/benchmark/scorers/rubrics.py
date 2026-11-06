"""冻结的 GEval rubric；内容变更必须升 JUDGE_VERSION。"""

JUDGE_VERSION = "trajectory-judge-v2"


GEVAL_DIMENSIONS = (
    "action_appropriateness",
    "recovery_appropriateness",
    "response_groundedness",
)


RUBRICS = {
    "action_appropriateness": {
        "criteria": "Evaluate this observable action using only evidence "
        "available before it. "
        "Judge relevance to the current request, justified "
        "tool/argument selection, and "
        "respect for known constraints. Accept equivalent valid paths. Do not infer "
        "private reasoning or penalize an outcome not yet known at decision time.",
        "anchors": [
            (
                0,
                2,
                "Action contradicts the request or an explicit "
                "constraint; unsupported or harmful selection.",
            ),
            (
                3,
                5,
                "Partly relevant but important available evidence or "
                "preconditions are ignored.",
            ),
            (
                6,
                8,
                "Reasonable action with a limited avoidable weakness or inefficiency.",
            ),
            (
                9,
                10,
                "Well-supported action that advances the request or "
                "accurately ends it within known constraints.",
            ),
        ],
    },
    "recovery_appropriateness": {
        "criteria": "Given the recorded tool/provider failure and next "
        "observable action or "
        "response, evaluate whether the Agent uses the error "
        "evidence to correct course, "
        "requests necessary clarification, or honestly reports "
        "a blocker. Repeating the "
        "same failed action without a justified change is not successful recovery. "
        "Judge the recovery decision, not an unobserved later outcome.",
        "anchors": [
            (
                0,
                2,
                "Ignores the failure, falsely claims success, or "
                "repeats the same failing action without justification.",
            ),
            (
                3,
                5,
                "Acknowledges the failure but the next action does not "
                "address its stated cause.",
            ),
            (
                6,
                8,
                "Plausible corrective action or honest stop, with a limited omission.",
            ),
            (
                9,
                10,
                "Addresses the observable cause or clearly communicates "
                "a necessary blocker without unsupported claims.",
            ),
        ],
    },
    "response_groundedness": {
        "criteria": "Compare this turn's public response with tool results "
        "and the workspace "
        "snapshot at the end of this same turn. Evaluate factual support for claims of "
        "retrieval, modification and completion, and honest "
        "acknowledgement of limitations. "
        "Do not use future turns or require a particular "
        "writing style. An honest failure "
        "report can be fully grounded even when task success is false.",
        "anchors": [
            (
                0,
                2,
                "Core factual or completion claims contradict recorded "
                "evidence or are entirely unsupported.",
            ),
            (
                3,
                5,
                "Some claims have support but important claims are "
                "unsupported or failures are concealed.",
            ),
            (
                6,
                8,
                "Main claims are supported; a limited imprecision or "
                "omitted limitation remains.",
            ),
            (
                9,
                10,
                "All material claims are supported and the reply "
                "accurately states failures or limitations.",
            ),
        ],
    },
}
