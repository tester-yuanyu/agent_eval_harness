"""版本化 P0 制作协议；只支持 read_file，独立于历史 EvalCase/v3 bundle。"""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def assertion_identity() -> str:
    """跨独立 Python 环境绑定实际安装的协议和断言代码。"""
    return digest_bytes(Path(__file__).read_bytes())


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def local_path(value: str) -> None:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or value == "."
        or "\\" in value
    ):
        raise ValueError("fixture paths must be canonical relative file paths")


class ReadinessCase(StrictRecord):
    case_id: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    fixtures: dict[str, str]
    reference_path: str
    expected_output: str

    @model_validator(mode="after")
    def paths(self) -> Self:
        local_path(self.reference_path)
        for path in self.fixtures:
            local_path(path)
        return self


class ReadinessDataset(StrictRecord):
    schema_version: Literal["1.0"] = "1.0"
    cases: list[ReadinessCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate case_id")
        return self


class RunnerIdentity(StrictRecord):
    runner_id: Literal[
        "native-read-file-v1",
        "native-mini-query-user-v1",
        "inspect-mini-operations-v2",
        "inspect-mini-agent-v3",
    ] = "native-read-file-v1"
    implementation_sha256: Hash
    runtime: dict[str, str] = Field(min_length=1)


class CaseEvidence(StrictRecord):
    case_id: str
    status: str
    evidence_complete: bool
    before_files: dict[str, str]
    final_files: dict[str, str]
    final_output: str
    executed_tools: list[str]
    observed_path: str | None
    errors: list[str]


class ReadinessEvidence(StrictRecord):
    schema_version: Literal["1.0"] = "1.0"
    dataset_sha256: Hash
    runner: RunnerIdentity
    results: list[CaseEvidence]


class ReleaseReview(StrictRecord):
    approved: Literal[True]
    reviewer: str = Field(min_length=1, pattern=r"\S")
    dataset_sha256: Hash
    evidence_sha256: Hash
    reviewed_case_ids: list[str] = Field(min_length=1)


def reference_checks(case: ReadinessCase, row: CaseEvidence) -> dict[str, bool]:
    """版本化断言实现也进入 runner 身份；不向执行端提供期望答案。"""
    return {
        "harness_binding": (
            row.evidence_complete
            and row.executed_tools == ["read_file"]
            and row.observed_path == case.reference_path
            and row.before_files == case.fixtures
            and not row.errors
        ),
        "execution_completed": row.status == "completed",
        "output_exact": row.final_output == case.expected_output,
        "files_unchanged": row.final_files == case.fixtures,
    }
