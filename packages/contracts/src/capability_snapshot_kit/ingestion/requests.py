"""Model-agnostic extraction requests: explicit source files, no SDK or network."""

from __future__ import annotations

import hashlib
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from capability_snapshot_kit.base import ProtocolModel
from capability_snapshot_kit.spec_loader import load_capability_spec_pack_v3

from .models import FactDocument, SourceReference
from .providers import FactExtractor
from .sources import MAX_SOURCE_BYTES, MAX_TOTAL_BYTES, read_source


def extraction_instructions() -> str:
    return (
        files("capability_snapshot_kit")
        .joinpath("resources/extraction.md")
        .read_text(encoding="utf-8")
    )


class SourceText(ProtocolModel):
    reference: SourceReference
    content: str

    @model_validator(mode="after")
    def verify_hash(self) -> Self:
        if len(self.content.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("request source too large")
        if (
            hashlib.sha256(self.content.encode("utf-8")).hexdigest()
            != self.reference.sha256
        ):
            raise ValueError("request source content hash mismatch")
        return self


class ExtractionRequest(ProtocolModel):
    request_version: Literal["1.0"] = "1.0"
    instructions: str
    document_schema: dict[str, Any]
    evaluation_spec: dict[str, Any]
    sources: dict[str, SourceText] = Field(min_length=1)

    @model_validator(mode="after")
    def current_contract(self) -> Self:
        if self.instructions != extraction_instructions():
            raise ValueError(
                "request instructions differ from installed extraction contract"
            )
        if self.document_schema != FactDocument.model_json_schema():
            raise ValueError(
                "request schema differs from installed FactDocument schema"
            )
        if (
            sum(len(s.content.encode("utf-8")) for s in self.sources.values())
            > MAX_TOTAL_BYTES
        ):
            raise ValueError("total source size exceeds limit")
        return self


def prepare_request(
    root: Path,
    paths: list[str],
    spec_root: Path | None = None,
) -> ExtractionRequest:
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate input source")
    sources = {}
    total = 0
    for path in sorted(paths):
        data = read_source(root, path)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("total source size exceeds limit")
        sources[path] = SourceText(
            reference=SourceReference(
                path=path,
                sha256=hashlib.sha256(data).hexdigest(),
                kind="documentation" if path.endswith(".md") else "code",
            ),
            content=data.decode("utf-8"),
        )
    return ExtractionRequest(
        instructions=extraction_instructions(),
        document_schema=FactDocument.model_json_schema(),
        evaluation_spec=load_capability_spec_pack_v3(
            spec_root
            or Path(
                str(files("capability_snapshot_kit").joinpath("resources/conversation"))
            )
        ).model_dump(mode="json"),
        sources=sources,
    )


def check_candidate_request(
    candidate: FactDocument, request: ExtractionRequest
) -> None:
    permitted = {
        (item.reference.path, item.reference.sha256, item.reference.kind)
        for item in request.sources.values()
    }
    for source in candidate.sources.values():
        if (source.path, source.sha256, source.kind) not in permitted:
            raise ValueError(f"candidate source not in request: {source.path}")


def extract_document(
    extractor: FactExtractor, request: ExtractionRequest
) -> FactDocument:
    request = ExtractionRequest.model_validate(request.model_dump(mode="json"))
    result = extractor.extract(request)
    if not isinstance(result, FactDocument):
        raise ValueError("extractor must return FactDocument")
    result = FactDocument.model_validate(result.model_dump(mode="json"))
    check_candidate_request(result, request)
    return result
