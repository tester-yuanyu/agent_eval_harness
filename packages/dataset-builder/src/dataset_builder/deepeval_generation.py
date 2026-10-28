"""Optional, slot-bound DeepEval synthesis of unreviewed semantic candidates."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from jsonschema import Draft202012Validator

from .candidate_parser import parse_candidates
from .coverage import _normalized
from .prompt_builder import build_prompt
from .scenario_requirements import (
    candidate_issues,
    check_requirement,
    load_requirements,
)
from .schemas import GenerationRequest, RawGeneration
from .source_pack import build_source_pack, sha256_bytes, sha256_file
from .suite_definition import SuiteDefinition

ADAPTER_VERSION = "deepeval-slot-v3"
SETTINGS = {
    "async_mode": False,
    "max_goldens_per_context": 1,
    "include_expected_output": True,
    "contract_gap_expected_output": False,
    "normalized_input_dedup": True,
    "num_evolutions": 0,
    "synthetic_input_quality_threshold": 0.0,
    "max_quality_retries": 1,
}


def build_slot_task(slot: dict[str, Any]) -> str:
    """The same contract-bound input instruction for all comparison arms."""
    slot_text = json.dumps(slot, ensure_ascii=False)
    input_only = bool(slot.get("acceptance", {}).get("oracle_gaps"))
    task = (
        "Generate exactly one Chinese user request for CURRENT_SLOT: "
        + slot_text
        + ". Preserve intentional missing, invalid or ambiguous parameters. "
        "Do not resolve ambiguity, repair invalid values, or invent capability "
        "rules. Use only the supplied contract. Do not put expected answers, "
        "slot identifiers or grading instructions into the user request. "
        "The acceptance description and predicates are mandatory input selection "
        "constraints. Generate an input that actually satisfies them; never "
        "force a planned label onto an incompatible input."
    )
    if input_only:
        task += (
            " This slot has unresolved oracle contract gaps. Generate the user "
            "input only. Do not generate or guess any expected output."
        )
    return task


class SynthesisRejected(ValueError):
    """Carries every original attempt when bounded synthesis cannot finish."""

    def __init__(self, message: str, attempt_audit: list[dict]) -> None:
        super().__init__(message)
        self.attempt_audit = attempt_audit


class SynthesisBlocked(SynthesisRejected):
    """Input-only scenarios and supported candidates, never a complete draft."""

    def __init__(self, partial_generation: RawGeneration) -> None:
        self.partial_generation = partial_generation
        super().__init__(
            "generation has unresolved oracle contract gaps; no complete draft",
            partial_generation.metadata["attempt_audit"],
        )


class DeepEvalGenerationClient:
    """Generate one Golden per planned slot; never inherit a seed oracle."""

    def __init__(
        self, *, suite: SuiteDefinition, model: str | Any, max_slot_attempts: int = 1
    ) -> None:
        if model is None or (isinstance(model, str) and not model.strip()):
            raise ValueError("an explicit DeepEval generator model is required")
        self.suite = suite
        self.model = model
        if type(max_slot_attempts) is not int or not 1 <= max_slot_attempts <= 10:
            raise ValueError("max_slot_attempts must be an integer from 1 to 10")
        self.max_slot_attempts = max_slot_attempts

    @classmethod
    def from_env(cls, suite: SuiteDefinition) -> DeepEvalGenerationClient:
        model = os.environ.get("DATASET_GENERATOR_MODEL")
        if not model or not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY and DATASET_GENERATOR_MODEL must both be set"
            )
        return cls(suite=suite, model=model)

    def _sdk_version(self) -> str:
        try:
            installed = version("deepeval")
        except PackageNotFoundError as exc:
            raise RuntimeError(
                "DeepEval is optional; install with: pip install -e '.[deepeval]'"
            ) from exc
        if installed != "4.3.2":
            raise RuntimeError("This adapter requires deepeval==4.3.2")
        return installed

    def _context(self, request: GenerationRequest) -> str:
        suite = self.suite
        source_pack, manifest = build_source_pack(suite)
        prompt = build_prompt(suite, source_pack)
        if (
            request.suite_id != suite.suite_id
            or request.prompt_version != suite.prompt_version
            or request.prompt != prompt
            or request.prompt_sha256 != sha256_bytes(prompt.encode())
            or request.source_manifest != manifest
            or request.candidate_schema != suite.batch_type.model_json_schema()
            or request.coverage_plan_sha256 != sha256_file(suite.coverage_plan_path)
            or request.suite_config_sha256
            != sha256_file(suite.suite_dir / "suite.json")
            or request.policy_bindings != list(suite.policy_bindings)
        ):
            raise ValueError("DeepEval sources do not match the prepared request")
        if "rule_refs" not in suite.candidate_type.model_fields:
            raise ValueError("DeepEval requires a candidate protocol with rule_refs")
        # Keep the IR and all allow-listed policies, but supply only the current
        # coverage slot below. No untrusted snapshot document/RAG ingestion.
        contextual_suite = replace(
            suite,
            source_files_resolved=tuple(
                p
                for p in suite.source_files_resolved
                if p.resolve() != suite.coverage_plan_path.resolve()
            ),
            authoritative_source_files=tuple(
                p
                for p in suite.authoritative_source_files
                if p.resolve() != suite.coverage_plan_path.resolve()
            ),
        )
        return build_source_pack(contextual_suite)[0]

    def _synthesize(self, context: str, slot: dict[str, Any], schema: str) -> list[Any]:
        # Disable anonymous SDK telemetry by default; no Confident AI push/login.
        os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
        from deepeval.models import OpenAIModel
        from deepeval.synthesizer import Synthesizer
        from deepeval.synthesizer.config import (
            EvolutionConfig,
            FiltrationConfig,
            StylingConfig,
        )

        model = (
            OpenAIModel(model=self.model) if isinstance(self.model, str) else self.model
        )
        slot_text = json.dumps(slot, ensure_ascii=False)
        input_only = bool(slot.get("acceptance", {}).get("oracle_gaps"))
        task = build_slot_task(slot)
        synthesizer = Synthesizer(
            model=model,
            async_mode=False,
            filtration_config=FiltrationConfig(
                critic_model=model,
                synthetic_input_quality_threshold=0.0,
                max_quality_retries=1,
            ),
            evolution_config=EvolutionConfig(num_evolutions=0),
            styling_config=StylingConfig(
                scenario=task,
                task="Route the request according to the supplied capability contract.",
                input_format=task,
                expected_output_format=(
                    None
                    if input_only
                    else "Return ONLY a JSON object matching this Candidate schema: "
                    + schema
                    + ". user_input MUST equal the current Input verbatim. "
                    "slot_id, expected_intent, expected_status, scenario_type and "
                    "rule_refs MUST match CURRENT_SLOT: "
                    + slot_text
                    + ". Derive the other fields from the current input and "
                    "explicit contract only. Never guess an unspecified outcome. "
                    "If unsupported by the contract return null (generation blocks)."
                ),
            ),
        )
        return synthesizer.generate_goldens_from_contexts(
            contexts=[[context, task]],
            include_expected_output=not input_only,
            max_goldens_per_context=1,
        )

    def generate(self, request: GenerationRequest) -> RawGeneration:
        context = self._context(request)
        sdk_version = self._sdk_version()
        requirements = load_requirements(self.suite)
        slots = self.suite.coverage_plan["slots"]
        if not slots or len({s["slot_id"] for s in slots}) != len(slots):
            raise ValueError("coverage plan must have nonempty unique slots")
        schema = self.suite.candidate_type.model_json_schema()
        validator = Draft202012Validator(schema)
        candidates, audit, attempt_audit, blocked_slots = [], [], [], []
        accepted_inputs: dict[str, str] = {}
        for slot in slots:
            if not slot.get("rule_refs") or not slot.get("scenario_type"):
                raise ValueError(
                    f"slot {slot['slot_id']} lacks explicit contract rules"
                )
        for slot in slots:
            slot_id = slot["slot_id"]
            requirement = requirements.get(slot_id)
            input_only = bool(requirement and requirement.oracle_gaps)
            diagnostics = []
            for attempt in range(1, self.max_slot_attempts + 1):
                attempt_context = context
                if diagnostics:
                    attempt_context += (
                        "\nREJECTED_ATTEMPT_DIAGNOSTICS "
                        "(validation data, not new capability facts):\n"
                        + json.dumps(diagnostics, ensure_ascii=False)
                        + (
                            "\nGenerate a fresh input only. Never invent an oracle."
                            if input_only
                            else "\nGenerate a fresh input and derive its "
                            "own expectation. "
                            "Do not copy or patch a prior answer."
                        )
                    )
                record = {
                    "slot_id": slot_id,
                    "attempt": attempt,
                    "context_sha256": sha256_bytes(attempt_context.encode()),
                    "feedback": list(diagnostics),
                    "goldens": [],
                    "issues": [],
                    "include_expected_output": not input_only,
                }
                attempt_audit.append(record)
                try:
                    goldens = self._synthesize(
                        attempt_context, slot, json.dumps(schema, ensure_ascii=False)
                    )
                except Exception as exc:
                    record["issues"] = [f"synthesis raised {type(exc).__name__}"]
                    raise SynthesisRejected(
                        f"slot {slot_id}: synthesis raised {type(exc).__name__}",
                        attempt_audit,
                    ) from exc
                record["goldens"] = [
                    {
                        "input": g.input,
                        "expected_output": g.expected_output,
                        "context": g.context,
                        "additional_metadata": g.additional_metadata,
                    }
                    for g in goldens
                ]
                try:
                    if len(goldens) != 1:
                        raise ValueError("expected exactly one Golden")
                    golden = goldens[0]
                    if not isinstance(golden.input, str) or not golden.input.strip():
                        raise ValueError("Golden must have a nonempty input")
                    normalized = _normalized(golden.input)
                    if normalized in accepted_inputs:
                        raise ValueError(
                            "duplicate input after punctuation/space normalization; "
                            f"already accepted in {accepted_inputs[normalized]}. "
                            "Rejected input: "
                            f"{json.dumps(golden.input, ensure_ascii=False)}. "
                            "Use different wording and a different synthetic value "
                            "unless the slot requires a fixed boundary value."
                        )
                    if input_only:
                        if golden.expected_output is not None:
                            raise ValueError(
                                "contract-gap slot must not have an oracle"
                            )
                        if (
                            not isinstance(golden.input, str)
                            or not golden.input.strip()
                        ):
                            raise ValueError(
                                "contract-gap slot must have a nonempty input"
                            )
                        diagnostics = check_requirement(golden.input, None, requirement)
                        record["issues"] = diagnostics
                        if diagnostics:
                            continue
                        blocked_slots.append(
                            {
                                "slot_id": slot_id,
                                "user_input": golden.input,
                                "oracle_gaps": requirement.oracle_gaps,
                                "evidence_refs": requirement.evidence_refs,
                                "status": "CONTRACT_BLOCKED",
                            }
                        )
                        accepted_inputs[normalized] = slot_id
                        break
                    if not isinstance(golden.expected_output, str):
                        raise ValueError(
                            "expected_output must be explicit Candidate JSON"
                        )
                    candidate = json.loads(golden.expected_output)
                    errors = sorted(
                        validator.iter_errors(candidate), key=lambda e: str(e.path)
                    )
                    if errors:
                        raise ValueError(errors[0].message)
                    if candidate["user_input"] != golden.input:
                        raise ValueError(
                            "Candidate user_input differs from Golden input"
                        )
                    diagnostics = candidate_issues(candidate, self.suite, slot)
                except ValueError as exc:
                    diagnostics = [str(exc)]
                record["issues"] = diagnostics
                if not diagnostics:
                    candidates.append(candidate)
                    accepted_inputs[normalized] = slot_id
                    audit.append({"slot_id": slot_id, **record["goldens"][0]})
                    break
            else:
                raise SynthesisRejected(
                    f"slot {slot_id}: exhausted {self.max_slot_attempts} attempts: "
                    + "; ".join(diagnostics),
                    attempt_audit,
                )
        raw = RawGeneration(
            request_id=request.request_id,
            mode="deepeval",
            model=self.model
            if isinstance(self.model, str)
            else self.model.get_model_name(),
            prompt_version=request.prompt_version,
            created_at=datetime.now(UTC),
            attempts=1,
            response={"candidates": candidates},
            metadata={
                "adapter_version": ADAPTER_VERSION,
                "sdk_version": sdk_version,
                "settings": {**SETTINGS, "max_slot_attempts": self.max_slot_attempts},
                "oracle_status": "unreviewed",
                "context_sha256": sha256_bytes(context.encode()),
                "goldens": audit,
                "attempt_audit": attempt_audit,
                "blocked_slots": blocked_slots,
            },
        )
        if blocked_slots:
            raise SynthesisBlocked(raw)
        parse_candidates(self.suite, raw)
        return raw
