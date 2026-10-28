"""Reusable intent parameter contracts and deterministic decision policies."""

from __future__ import annotations

import re
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from minimal_agent.contracts.agent import IntentResult
from minimal_agent.contracts.intent_parameters import (
    EmailString,
    GiftQuantity,
    NonEmptyString,
    PhoneString,
    PositiveInt,
    PositiveIntList,
)

if TYPE_CHECKING:
    from minimal_agent.runtime.trace import TraceCollector

QUERY_USER_CONTRACT_VERSION = "query-user-intent-contract-v3"
QUERY_USER_MISSING_PARAMETERS = frozenset(
    {
        "user_id",
        "room_id",
        "email",
        "phone",
        "user_id_or_room_id",
        "user_id_or_room_id_or_email_or_phone",
        "single_user_id",
        "single_room_id",
        "single_email",
        "single_phone",
        "single_user_query_condition",
    }
)


class IntentContractError(RuntimeError):
    """Raised when a formal Intent contract cannot be applied safely."""


def _is_present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set, frozenset)):
        return bool(value)
    return True


@dataclass(frozen=True)
class NormalizationChange:
    """One public, deterministic parameter normalization."""

    field: str
    normalizer: str
    before: object
    after: object


@dataclass(frozen=True)
class NormalizationResult:
    """Copied parameters and their observable normalization changes."""

    parameters: dict[str, Any]
    changes: tuple[NormalizationChange, ...] = ()


class ParameterNormalizer(Protocol):
    """Normalize declared parameters without guessing missing values."""

    def normalize(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> NormalizationResult: ...


@dataclass(frozen=True)
class TrimStringNormalizer:
    """Strip surrounding whitespace from declared string fields."""

    fields: tuple[str, ...]

    def normalize(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> NormalizationResult:
        del user_input
        normalized = dict(parameters)
        changes: list[NormalizationChange] = []
        for field in self.fields:
            value = normalized.get(field)
            if not isinstance(value, str):
                continue
            stripped = value.strip()
            if stripped == value:
                continue
            normalized[field] = stripped
            changes.append(
                NormalizationChange(field, type(self).__name__, value, stripped)
            )
        return NormalizationResult(normalized, tuple(changes))


@dataclass(frozen=True)
class IntegerStringNormalizer:
    """Convert ASCII digit strings in declared integer fields."""

    fields: tuple[str, ...]

    def normalize(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> NormalizationResult:
        del user_input
        normalized = dict(parameters)
        changes: list[NormalizationChange] = []
        for field in self.fields:
            value = normalized.get(field)
            if not isinstance(value, str):
                continue
            if not value.isascii() or not value.isdecimal():
                continue
            converted = int(value)
            normalized[field] = converted
            changes.append(
                NormalizationChange(field, type(self).__name__, value, converted)
            )
        return NormalizationResult(normalized, tuple(changes))


@dataclass(frozen=True)
class ConstraintResult:
    """Public result of one reusable semantic or completeness constraint."""

    valid: bool
    missing_parameters: tuple[str, ...] = ()
    reason: str | None = None
    clear_parameters: bool = False


class SemanticConstraint(Protocol):
    """Evaluate parameter completeness or observable request semantics."""

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult: ...


@dataclass(frozen=True)
class RequiredFields:
    """Require every named field and report its canonical name."""

    fields: tuple[str, ...]

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult:
        del user_input
        missing = tuple(
            field for field in self.fields if not _is_present(parameters.get(field))
        )
        return ConstraintResult(not missing, missing)


@dataclass(frozen=True)
class AtLeastOneFieldGroup:
    """Require at least one present field from a named group."""

    fields: tuple[str, ...]
    missing_name: str

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult:
        del user_input
        valid = any(_is_present(parameters.get(field)) for field in self.fields)
        return ConstraintResult(valid, () if valid else (self.missing_name,))


@dataclass(frozen=True)
class ExactlyOneFieldGroup:
    """Require exactly one present field from a named group."""

    fields: tuple[str, ...]
    missing_name: str

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult:
        del user_input
        count = sum(_is_present(parameters.get(field)) for field in self.fields)
        valid = count == 1
        return ConstraintResult(valid, () if valid else (self.missing_name,))


@dataclass(frozen=True)
class MutuallyExclusiveFields:
    """Reject more than one present field from a named group."""

    fields: tuple[str, ...]
    missing_name: str

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult:
        del user_input
        count = sum(_is_present(parameters.get(field)) for field in self.fields)
        valid = count <= 1
        return ConstraintResult(valid, () if valid else (self.missing_name,))


@dataclass(frozen=True)
class FieldSemanticSpec:
    """Observable field vocabulary used by reusable query constraints."""

    field: str
    mention_pattern: str
    value_pattern: str
    single_value_missing_name: str


@dataclass(frozen=True)
class RequireMentionedFields:
    """Request a concrete field when the user names it but no valid value remains."""

    field_patterns: tuple[tuple[str, str], ...]

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult:
        missing = tuple(
            field
            for field, pattern in self.field_patterns
            if re.search(pattern, user_input, re.IGNORECASE)
            and not _is_present(parameters.get(field))
        )
        return ConstraintResult(not missing, missing)


@dataclass(frozen=True)
class DisallowAmbiguousBareInteger:
    """Reject an unlabeled positive integer when several ID fields are plausible."""

    qualified_patterns: tuple[str, ...]
    missing_name: str

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult:
        del parameters
        if any(
            re.search(pattern, user_input, re.IGNORECASE)
            for pattern in self.qualified_patterns
        ):
            return ConstraintResult(True)
        if "@" in user_input:
            return ConstraintResult(True)
        values = re.findall(
            r"(?<![0-9A-Za-z@])([0-9]+)(?![0-9A-Za-z@])",
            user_input,
        )
        unique_values = set(values)
        if not unique_values or all(len(value) == 11 for value in unique_values):
            return ConstraintResult(True)
        return ConstraintResult(
            False,
            (self.missing_name,),
            "请说明该数字是用户 ID 还是房间 ID。",
            clear_parameters=True,
        )


@dataclass(frozen=True)
class DisallowMultipleValuesPerField:
    """Reject multiple distinct values for one scalar query field."""

    specs: tuple[FieldSemanticSpec, ...]

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult:
        mentioned = [
            spec
            for spec in self.specs
            if re.search(spec.mention_pattern, user_input, re.IGNORECASE)
        ]
        if len(mentioned) != 1:
            return ConstraintResult(True)
        spec = mentioned[0]
        values = set(
            re.findall(spec.value_pattern, user_input, flags=re.IGNORECASE)
        )
        repeated_label = (
            len(
                re.findall(
                    spec.mention_pattern,
                    user_input,
                    flags=re.IGNORECASE,
                )
            )
            > 1
        )
        has_multi_signal = repeated_label or bool(
            re.search(r"(?:批量|多个|多位|分别|都查|、|，|,|\s和\s|\s及\s)", user_input)
        )
        if len(values) <= 1 or not has_multi_signal:
            return ConstraintResult(True)
        if self._has_resolved_replacement(user_input, parameters, spec):
            return ConstraintResult(True)
        return ConstraintResult(
            False,
            (spec.single_value_missing_name,),
            f"当前不支持同时查询多个 {spec.field}，请一次提供一个值。",
            clear_parameters=True,
        )

    @staticmethod
    def _has_resolved_replacement(
        user_input: str,
        parameters: dict[str, Any],
        spec: FieldSemanticSpec,
    ) -> bool:
        """Return true when one explicit replacement matches the candidate value."""

        candidate_value = parameters.get(spec.field)
        if not _is_present(candidate_value):
            return False

        replacement_suffixes = [
            user_input[match.end() :]
            for match in re.finditer(
                r"(?:改成|改为|更正成|更正为|换成|应为|应该是|而是)",
                user_input,
                re.IGNORECASE,
            )
        ]
        for match in re.finditer(
            r"[，,；;]\s*(?:请)?(?:查询|查找|查|使用|用|按)",
            user_input,
            re.IGNORECASE,
        ):
            prefix = user_input[: match.start()]
            if re.search(r"(?:不要|不用|别再?|无需)", prefix, re.IGNORECASE):
                replacement_suffixes.append(user_input[match.end() :])

        expected = str(candidate_value).casefold()
        for suffix in replacement_suffixes:
            replacement_values = {
                value.casefold()
                for value in re.findall(
                    spec.value_pattern,
                    suffix,
                    flags=re.IGNORECASE,
                )
            }
            if replacement_values == {expected}:
                return True
        return False


@dataclass(frozen=True)
class DisallowAlternativeQuery:
    """Reject explicit OR semantics when multiple query fields were extracted."""

    fields: tuple[str, ...]
    missing_name: str = "single_user_query_condition"
    field_patterns: tuple[str, ...] = ()

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult:
        present_count = sum(
            _is_present(parameters.get(field)) for field in self.fields
        )
        observed_count = sum(
            bool(re.search(pattern, user_input, re.IGNORECASE))
            for pattern in self.field_patterns
        )
        present_count = max(present_count, observed_count)
        has_alternative = bool(
            re.search(r"(?:\bOR\b|或|还是|二选一)", user_input, re.IGNORECASE)
        )
        if present_count < 2 or not has_alternative:
            return ConstraintResult(True)
        return ConstraintResult(
            False,
            (self.missing_name,),
            "当前不支持 OR 条件查询，请一次查询一个用户。",
            clear_parameters=True,
        )


@dataclass(frozen=True)
class DisallowBatchQuery:
    """Reject explicit batch semantics when multiple entities were extracted."""

    fields: tuple[str, ...]
    missing_name: str = "single_user_query_condition"
    field_patterns: tuple[str, ...] = ()

    def evaluate(
        self,
        user_input: str,
        parameters: dict[str, Any],
    ) -> ConstraintResult:
        extracted_count = sum(
            _is_present(parameters.get(field)) for field in self.fields
        )
        for field in self.fields:
            value = parameters.get(field)
            if isinstance(value, (list, tuple, set, frozenset)):
                extracted_count += max(0, len(value) - 1)
        observed_count = sum(
            bool(re.search(pattern, user_input, re.IGNORECASE))
            for pattern in self.field_patterns
        )
        extracted_count = max(extracted_count, observed_count)
        has_batch_signal = bool(
            re.search(r"(?:分别|批量|多个|多位|每个|这些|都查|一起查)", user_input)
        )
        if extracted_count < 2 or not has_batch_signal:
            return ConstraintResult(True)
        return ConstraintResult(
            False,
            (self.missing_name,),
            "当前不支持批量查询，请一次查询一个用户。",
            clear_parameters=True,
        )


Decision = tuple[
    Literal["READY", "NEED_CLARIFICATION", "NEED_CONFIRMATION", "REJECTED"],
    Literal["CALL_TOOL", "ASK_USER", "ASK_CONFIRMATION", "REJECT"],
]


class CompletionPolicy(Protocol):
    """Choose the canonical public state from contract validation."""

    def decide(self, has_issues: bool) -> Decision: ...


@dataclass(frozen=True)
class ReadIntentPolicy:
    def decide(self, has_issues: bool) -> Decision:
        return (
            ("NEED_CLARIFICATION", "ASK_USER")
            if has_issues
            else ("READY", "CALL_TOOL")
        )


@dataclass(frozen=True)
class WriteIntentPolicy:
    def decide(self, has_issues: bool) -> Decision:
        return (
            ("NEED_CLARIFICATION", "ASK_USER")
            if has_issues
            else ("NEED_CONFIRMATION", "ASK_CONFIRMATION")
        )


@dataclass(frozen=True)
class UnsupportedIntentPolicy:
    def decide(self, has_issues: bool) -> Decision:
        del has_issues
        return "REJECTED", "REJECT"


@dataclass(frozen=True)
class IntentDefinition:
    """One versioned intent parameter and decision contract."""

    intent: str
    contract_version: str
    parameters_model: type[BaseModel]
    normalizers: tuple[ParameterNormalizer, ...]
    semantic_constraints: tuple[SemanticConstraint, ...]
    completion_policy: CompletionPolicy
    execution_mode: Literal["read", "write", "unsupported"]
    tool_name: str | None = None
    missing_parameters: tuple[str, ...] = ()
    semantic_rules: dict[str, Any] = dataclass_field(default_factory=dict)


class IntentRegistry:
    """Resolve and apply deterministic intent definitions."""

    def __init__(self) -> None:
        self._definitions: dict[str, IntentDefinition] = {}

    @property
    def intents(self) -> frozenset[str]:
        return frozenset(self._definitions)

    @property
    def definitions(self) -> tuple[IntentDefinition, ...]:
        """Return registered contracts in their deterministic declaration order."""

        return tuple(self._definitions.values())

    def register(self, definition: IntentDefinition) -> None:
        if definition.intent in self._definitions:
            raise IntentContractError(
                f"intent already registered: {definition.intent!r}"
            )
        if not definition.contract_version.strip():
            raise IntentContractError(
                f"intent {definition.intent!r} has an empty contract version"
            )
        expected_policy = {
            "read": ReadIntentPolicy,
            "write": WriteIntentPolicy,
            "unsupported": UnsupportedIntentPolicy,
        }[definition.execution_mode]
        if not isinstance(definition.completion_policy, expected_policy):
            raise IntentContractError(
                "completion policy does not match execution mode "
                f"{definition.execution_mode!r} for intent {definition.intent!r}"
            )
        if not issubclass(definition.parameters_model, BaseModel):
            raise IntentContractError(
                f"intent {definition.intent!r} has an invalid parameters model"
            )
        self._definitions[definition.intent] = definition

    def get(self, intent: str) -> IntentDefinition:
        try:
            return self._definitions[intent]
        except KeyError as exc:
            raise IntentContractError(f"intent not registered: {intent!r}") from exc

    def validate(
        self,
        user_input: str,
        candidate: IntentResult,
        *,
        trace: TraceCollector | None = None,
    ) -> IntentResult:
        definition = self.get(candidate.intent)
        parameters = dict(candidate.parameters)
        if trace is not None:
            trace.record(
                "intent_definition_resolved",
                {
                    "intent": candidate.intent,
                    "contract_version": definition.contract_version,
                },
            )

        for normalizer in definition.normalizers:
            result = normalizer.normalize(user_input, parameters)
            parameters = result.parameters
            if trace is not None:
                for change in result.changes:
                    trace.record(
                        "intent_parameter_normalized",
                        {
                            "intent": candidate.intent,
                            "field": change.field,
                            "normalizer": change.normalizer,
                            "before": change.before,
                            "after": change.after,
                        },
                    )

        valid_parameters, invalid_fields = self._validate_fields(
            definition.parameters_model,
            parameters,
        )
        if trace is not None and invalid_fields:
            trace.record(
                "intent_parameter_validation_failed",
                {
                    "intent": candidate.intent,
                    "fields": invalid_fields,
                    "error_type": "invalid_parameter",
                },
            )
        constraint_results: list[ConstraintResult] = []
        for constraint in definition.semantic_constraints:
            result = constraint.evaluate(user_input, valid_parameters)
            constraint_results.append(result)
            if trace is not None and not result.valid:
                trace.record(
                    "intent_semantic_constraint_failed",
                    {
                        "intent": candidate.intent,
                        "constraint": type(constraint).__name__,
                        "missing_parameters": list(result.missing_parameters),
                        "reason": result.reason,
                    },
                )
        clear_results = [
            result
            for result in constraint_results
            if not result.valid and result.clear_parameters
        ]
        if clear_results:
            valid_parameters = {}

        missing = [] if clear_results else list(invalid_fields)
        reasons: list[str] = []
        active_results = clear_results[:1] if clear_results else constraint_results
        for result in active_results:
            if result.valid:
                continue
            missing.extend(result.missing_parameters)
            if result.reason:
                reasons.append(result.reason)
        if not clear_results:
            for constraint, result in zip(
                definition.semantic_constraints,
                constraint_results,
                strict=True,
            ):
                if not isinstance(constraint, AtLeastOneFieldGroup) or result.valid:
                    continue
                if any(field in missing for field in constraint.fields):
                    missing = [
                        name
                        for name in missing
                        if name != constraint.missing_name
                    ]
        missing = list(dict.fromkeys(missing))
        status, next_action = definition.completion_policy.decide(bool(missing))
        if status != "NEED_CLARIFICATION":
            missing = []

        reason = candidate.reason
        if status == "NEED_CLARIFICATION":
            reason = reasons[0] if reasons else self._clarification_reason(missing)

        if trace is not None:
            trace.record(
                "intent_contract_validated",
                {
                    "intent": candidate.intent,
                    "contract_version": definition.contract_version,
                    "valid": not missing,
                    "invalid_fields": invalid_fields,
                },
            )
        result = IntentResult(
            intent=candidate.intent,
            status=status,
            next_action=next_action,
            parameters=valid_parameters,
            missing_parameters=missing,
            reason=reason,
        )
        if trace is not None:
            trace.record(
                "intent_decided",
                {
                    "intent": result.intent,
                    "status": result.status,
                    "next_action": result.next_action,
                    "missing_parameters": result.missing_parameters,
                },
            )
        return result

    @staticmethod
    def _validate_fields(
        model: type[BaseModel],
        parameters: dict[str, Any],
    ) -> tuple[dict[str, Any], list[str]]:
        valid: dict[str, Any] = {}
        invalid: list[str] = []
        for name, value in parameters.items():
            field = model.model_fields.get(name)
            if field is None:
                invalid.append(name)
                continue
            adapter = TypeAdapter(field.annotation, config=ConfigDict(strict=True))
            try:
                valid[name] = adapter.validate_python(value)
            except ValidationError:
                invalid.append(name)

        try:
            parsed = model.model_validate(valid)
        except ValidationError as exc:
            for error in exc.errors():
                location = error.get("loc", ())
                invalid.append(str(location[0]) if location else "parameters")
            return valid, list(dict.fromkeys(invalid))
        return parsed.model_dump(exclude_none=True), list(dict.fromkeys(invalid))

    @staticmethod
    def _clarification_reason(missing: list[str]) -> str:
        joined = ", ".join(missing)
        return f"Please provide valid values for: {joined}."


class _PartialParameters(BaseModel):
    """Strict candidate parameters; completeness is evaluated separately."""

    model_config = ConfigDict(extra="forbid", strict=True)


class _QueryInformationParameters(_PartialParameters):
    resource_type: NonEmptyString | None = None
    environment: NonEmptyString | None = None


class _PrepareResourceParameters(_PartialParameters):
    resource_type: NonEmptyString | None = None
    environment: NonEmptyString | None = None
    count: PositiveInt | None = None
    request_id: NonEmptyString | None = None


class _QueryUserParameters(_PartialParameters):
    user_id: PositiveInt | None = None
    room_id: PositiveInt | None = None
    email: EmailString | None = None
    phone: PhoneString | None = None


class _QueryGiftParameters(_PartialParameters):
    gift_id: PositiveInt | None = None
    gift_ids: PositiveIntList | None = None
    gift_name: NonEmptyString | None = None
    limit: PositiveInt | None = None


class _AddBackpackGiftParameters(_PartialParameters):
    gift_id: PositiveInt | None = None
    gift_ids: PositiveIntList | None = None
    gift_nums: list[GiftQuantity] | None = None
    user_id: PositiveInt | None = None
    user_ids: PositiveIntList | None = None
    num: int | None = Field(default=None, ge=1, le=1000)
    duration_days: int | None = Field(default=None, ge=1, le=1000)
    environment: NonEmptyString | None = None


class _QueryPoolParameters(_PartialParameters):
    gift_id: PositiveInt | None = None
    pool_id: PositiveInt | None = None


class _UnsupportedParameters(_PartialParameters):
    pass


_QUERY_USER_FIELD_SPECS = (
    FieldSemanticSpec(
        "user_id",
        r"(?:user[ _-]?id|用户\s*(?:id|编号))",
        r"(?<![0-9A-Za-z])([0-9]+)(?![0-9A-Za-z])",
        "single_user_id",
    ),
    FieldSemanticSpec(
        "room_id",
        r"(?:room[ _-]?id|(?:直播间|房间)\s*(?:id|编号|号)?)",
        r"(?<![0-9A-Za-z])([0-9]+)(?![0-9A-Za-z])",
        "single_room_id",
    ),
    FieldSemanticSpec(
        "email",
        r"(?:e-?mail|电子邮箱|电子邮件地址|邮箱)",
        r"([0-9A-Z._%+-]+@[0-9A-Z.-]+)",
        "single_email",
    ),
    FieldSemanticSpec(
        "phone",
        r"(?:phone|手机号码|手机号|电话号码|手机)",
        r"(?<![0-9A-Za-z])([0-9A-Za-z-]{5,})(?![0-9A-Za-z])",
        "single_phone",
    ),
)

_QUERY_USER_FIELD_PATTERNS = tuple(
    spec.mention_pattern for spec in _QUERY_USER_FIELD_SPECS
)


def build_default_intent_registry() -> IntentRegistry:
    """Build the complete registry for the public IntentResult vocabulary."""

    registry = IntentRegistry()
    contract_version = "intent-contract-v1"
    definitions = (
        IntentDefinition(
            intent="query_information",
            contract_version=contract_version,
            tool_name="query_information",
            missing_parameters=("environment", "resource_type"),
            semantic_rules={
                "required_fields": ["resource_type", "environment"],
                "string_normalization": "TRIM_SURROUNDING_WHITESPACE",
            },
            parameters_model=_QueryInformationParameters,
            normalizers=(
                TrimStringNormalizer(("resource_type", "environment")),
            ),
            semantic_constraints=(
                RequiredFields(("resource_type", "environment")),
            ),
            completion_policy=ReadIntentPolicy(),
            execution_mode="read",
        ),
        IntentDefinition(
            intent="prepare_resource",
            contract_version=contract_version,
            tool_name="prepare_resource",
            missing_parameters=(
                "count",
                "environment",
                "request_id",
                "resource_type",
            ),
            semantic_rules={
                "required_fields": [
                    "resource_type",
                    "environment",
                    "count",
                    "request_id",
                ],
                "count": "POSITIVE_INTEGER",
                "request_id": "NONEMPTY_MODEL_ARGUMENT",
            },
            parameters_model=_PrepareResourceParameters,
            normalizers=(
                TrimStringNormalizer(
                    ("resource_type", "environment", "count", "request_id")
                ),
                IntegerStringNormalizer(("count",)),
            ),
            semantic_constraints=(
                RequiredFields(
                    ("resource_type", "environment", "count", "request_id")
                ),
            ),
            completion_policy=ReadIntentPolicy(),
            execution_mode="read",
        ),
        IntentDefinition(
            intent="query_user",
            contract_version=QUERY_USER_CONTRACT_VERSION,
            tool_name="query_user_info",
            missing_parameters=tuple(sorted(QUERY_USER_MISSING_PARAMETERS)),
            semantic_rules={
                "multiple_fields": "AND",
                "email_format": "EXACTLY_ONE_AT_WITH_NONEMPTY_SIDES",
                "phone_format": "ASCII_DIGITS_EXACTLY_11",
                "explicit_field_overrides_value_shape": True,
                "bare_integer": "CLARIFY_USER_ID_OR_ROOM_ID",
                "repeated_bare_integer": "CLARIFY_USER_ID_OR_ROOM_ID",
                "or_query": "NEED_CLARIFICATION_CLEAR_PARAMETERS",
                "batch_query": "NEED_CLARIFICATION_CLEAR_PARAMETERS",
                "same_field_multiple_values": "NEED_CLARIFICATION_CLEAR_PARAMETERS",
                "explicit_correction": "USE_FINAL_UNIQUE_VALUE",
                "negation_then_restatement": "USE_FINAL_UNIQUE_VALUE",
                "unresolved_pronoun": (
                    "NEED_CLARIFICATION_MISSING_ALL_CONDITIONS"
                ),
                "field_aliases": {
                    "user_id": [
                        "user_id",
                        "user id",
                        "user-id",
                        "userid",
                        "用户 ID",
                        "用户ID",
                        "用户编号",
                        "用户",
                    ],
                    "room_id": [
                        "room_id",
                        "room id",
                        "room-id",
                        "roomid",
                        "直播间 ID",
                        "直播间ID",
                        "房间 ID",
                        "房间ID",
                        "直播间编号",
                        "房间编号",
                        "直播间号",
                        "房间号",
                        "直播间",
                        "房间",
                    ],
                    "email": [
                        "email",
                        "e-mail",
                        "电子邮箱",
                        "电子邮件地址",
                        "邮箱",
                    ],
                    "phone": ["phone", "手机号码", "手机号", "电话号码", "手机"],
                },
            },
            parameters_model=_QueryUserParameters,
            normalizers=(
                TrimStringNormalizer(("user_id", "room_id", "email", "phone")),
                IntegerStringNormalizer(("user_id", "room_id")),
            ),
            semantic_constraints=(
                AtLeastOneFieldGroup(
                    ("user_id", "room_id", "email", "phone"),
                    missing_name="user_id_or_room_id_or_email_or_phone",
                ),
                RequireMentionedFields(
                    tuple(
                        (spec.field, spec.mention_pattern)
                        for spec in _QUERY_USER_FIELD_SPECS
                    )
                ),
                DisallowAmbiguousBareInteger(
                    qualified_patterns=(
                        *_QUERY_USER_FIELD_PATTERNS,
                        r"用户\s*(?:为|是)?\s*[0-9]+",
                    ),
                    missing_name="user_id_or_room_id",
                ),
                DisallowMultipleValuesPerField(_QUERY_USER_FIELD_SPECS),
                DisallowAlternativeQuery(
                    ("user_id", "room_id", "email", "phone"),
                    field_patterns=_QUERY_USER_FIELD_PATTERNS,
                ),
                DisallowBatchQuery(
                    ("user_id", "room_id", "email", "phone"),
                    field_patterns=_QUERY_USER_FIELD_PATTERNS,
                ),
            ),
            completion_policy=ReadIntentPolicy(),
            execution_mode="read",
        ),
        IntentDefinition(
            intent="query_gift",
            contract_version=contract_version,
            tool_name="query_gift_info",
            missing_parameters=(
                "gift_id",
                "gift_ids",
                "gift_name",
                "limit",
                "single_gift_query_mode",
            ),
            semantic_rules={
                "query_modes": ["gift_id", "gift_ids", "gift_name"],
                "query_mode_cardinality": "EXACTLY_ONE",
                "limit": "OPTIONAL_POSITIVE_INTEGER",
            },
            parameters_model=_QueryGiftParameters,
            normalizers=(
                TrimStringNormalizer(("gift_id", "gift_name", "limit")),
                IntegerStringNormalizer(("gift_id", "limit")),
            ),
            semantic_constraints=(
                ExactlyOneFieldGroup(
                    ("gift_id", "gift_ids", "gift_name"),
                    missing_name="single_gift_query_mode",
                ),
            ),
            completion_policy=ReadIntentPolicy(),
            execution_mode="read",
        ),
        IntentDefinition(
            intent="add_backpack_gift",
            contract_version=contract_version,
            tool_name="add_gift_to_backpack",
            missing_parameters=(
                "duration_days",
                "environment",
                "gift_id",
                "gift_ids",
                "gift_nums",
                "num",
                "single_gift_selection_mode",
                "single_user_selection_mode",
                "user_id",
                "user_ids",
            ),
            semantic_rules={
                "required_fields": ["environment"],
                "user_selection_modes": ["user_id", "user_ids"],
                "user_selection_cardinality": "EXACTLY_ONE",
                "gift_selection_modes": ["gift_id", "gift_ids", "gift_nums"],
                "gift_selection_cardinality": "EXACTLY_ONE",
                "default_num": 1,
                "default_duration_days": 7,
                "permanent_duration_days": 1000,
            },
            parameters_model=_AddBackpackGiftParameters,
            normalizers=(
                TrimStringNormalizer(
                    (
                        "gift_id",
                        "user_id",
                        "num",
                        "duration_days",
                        "environment",
                    )
                ),
                IntegerStringNormalizer(
                    ("gift_id", "user_id", "num", "duration_days")
                ),
            ),
            semantic_constraints=(
                RequiredFields(("environment",)),
                ExactlyOneFieldGroup(
                    ("user_id", "user_ids"),
                    missing_name="single_user_selection_mode",
                ),
                ExactlyOneFieldGroup(
                    ("gift_id", "gift_ids", "gift_nums"),
                    missing_name="single_gift_selection_mode",
                ),
            ),
            completion_policy=WriteIntentPolicy(),
            execution_mode="write",
        ),
        IntentDefinition(
            intent="query_pool",
            contract_version=contract_version,
            tool_name="query_pool_config",
            missing_parameters=("gift_id", "pool_id", "single_pool_query_mode"),
            semantic_rules={
                "query_modes": ["pool_id", "gift_id"],
                "query_mode_cardinality": "EXACTLY_ONE",
            },
            parameters_model=_QueryPoolParameters,
            normalizers=(
                TrimStringNormalizer(("gift_id", "pool_id")),
                IntegerStringNormalizer(("gift_id", "pool_id")),
            ),
            semantic_constraints=(
                ExactlyOneFieldGroup(
                    ("gift_id", "pool_id"),
                    missing_name="single_pool_query_mode",
                ),
            ),
            completion_policy=ReadIntentPolicy(),
            execution_mode="read",
        ),
        IntentDefinition(
            intent="unsupported",
            contract_version=contract_version,
            tool_name=None,
            missing_parameters=(),
            semantic_rules={
                "scope": "REQUEST_OUTSIDE_DECLARED_CURRENT_CAPABILITIES",
                "tools_executed": False,
            },
            parameters_model=_UnsupportedParameters,
            normalizers=(),
            semantic_constraints=(),
            completion_policy=UnsupportedIntentPolicy(),
            execution_mode="unsupported",
        ),
    )
    for definition in definitions:
        registry.register(definition)
    return registry
