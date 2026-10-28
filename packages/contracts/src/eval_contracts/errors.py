"""Stable evaluator preflight errors shared across loading and execution."""

from __future__ import annotations


class EvaluationPreflightError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        evidence_path: str | None = None,
        evidence_refs: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.evidence_path = evidence_path
        self.evidence_refs = list(evidence_refs or [])
        if evidence_path is not None and evidence_path not in self.evidence_refs:
            self.evidence_refs.append(evidence_path)
