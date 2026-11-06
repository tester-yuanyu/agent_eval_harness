"""历史 Oracle 与 reference 入口；可信实现归 scorers。"""

from typing import Any

from .scorers.reference_runner import reference_observation as reference_observation
from .tasks import GRADER_VERSION as GRADER_VERSION


def evaluate_oracle(
    task: dict[str, Any], observation: dict[str, Any]
) -> dict[str, Any]:
    """保持旧 API，不维护第二份评分实现。"""
    from .scorers.executable import ExecutableScorer

    return ExecutableScorer().score_observation(task, observation)
