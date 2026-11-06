"""引擎无关的只读分析策略；不允许悄悄过滤计划总体。"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AnalysisPolicy:
    ks: tuple[int, ...] = (1, 3, 5)
    analysis_version: str = "benchmark-analysis-v1"
    annotation_policy: str = "reviewed_only"
    incomplete_policy: str = "require_complete"
    repeat_protocol: dict[str, Any] | None = None

    def __post_init__(self):
        if (
            not isinstance(self.ks, tuple)
            or not self.ks
            or any(type(k) is not int or k < 1 for k in self.ks)
            or len(self.ks) != len(set(self.ks))
        ):
            raise ValueError("ks must be distinct positive integers")
        if (
            self.analysis_version != "benchmark-analysis-v1"
            or self.annotation_policy != "reviewed_only"
            or self.incomplete_policy != "require_complete"
        ):
            raise ValueError("unsupported analysis policy")
        if self.repeat_protocol is not None and (
            not isinstance(self.repeat_protocol, dict)
            or self.repeat_protocol.get("independent_trials") is not True
            or any(
                not isinstance(self.repeat_protocol.get(k), str)
                or not self.repeat_protocol[k].strip()
                for k in ("environment_reset", "randomness")
            )
        ):
            raise ValueError(
                "repeat protocol requires independence, environment_reset and randomness"
            )
