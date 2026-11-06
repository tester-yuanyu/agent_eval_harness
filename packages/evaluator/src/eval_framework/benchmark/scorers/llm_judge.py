"""显式 opt-in 的 Judge 插件；保留原 GEval/native 指标与请求预算。"""

from copy import deepcopy
from typing import Any

from .evidence import evidence_references, observation_from_evidence


class LLMJudgeScorer:
    """配置只保存于可信端，score 的 final_state 是完整 observation envelope。"""

    def __init__(
        self,
        model_config: dict[str, Any],
        *,
        dimensions: list[str] | None = None,
        max_evaluations: int | None = None,
    ) -> None:
        self.model_config = deepcopy(model_config)
        self.dimensions = deepcopy(dimensions)
        self.max_evaluations = max_evaluations

    def score(
        self,
        trace: list[dict[str, Any]],
        final_state: dict[str, Any],
        task: dict[str, Any],
    ) -> dict[str, Any]:
        from .trajectory_judge import _judge_observation

        return {
            "formal": False,
            "verdict": "INCONCLUSIVE",
            "validity": "VALID",
            "success": None,
            "checks": [],
            "evidence_refs": evidence_references(trace),
            "metrics": _judge_observation(
                task,
                observation_from_evidence(trace, final_state),
                self.model_config,
                dimensions=self.dimensions,
                max_evaluations=self.max_evaluations,
            ),
        }
