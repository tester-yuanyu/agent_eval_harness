# ruff: noqa: E501
# Prompt templates retain their readable contract sentences.
"""Two independently generative backends sharing the exact slot instruction."""

from __future__ import annotations

import json
import os
from importlib.metadata import version

os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
os.environ["DEEPEVAL_UPDATE_WARNING_OPT_IN"] = "0"

from deepeval.models import DeepSeekModel
from jsonschema import Draft202012Validator

from dataset_builder.full_generation.contract_cases import EVENT_STIMULI

from .plan import canonical
from .protocol import FullCandidate


def strict_sdk_value(raw, schema):
    contract = schema.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            if "properties" in node:
                node["additionalProperties"] = False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(contract)
    errors = list(Draft202012Validator(contract).iter_errors(json.loads(raw)))
    if errors:
        raise ValueError(errors[0].message)
    return schema.model_validate_json(raw, strict=True)


class ControlledDeepSeek(DeepSeekModel):
    def __init__(self, provider, key):
        self.provider = provider
        super().__init__(
            model=provider.model,
            api_key=key,
            temperature=0.4,
            cost_per_input_token=0.3 / 1e6,
            cost_per_output_token=1.2 / 1e6,
        )

    def generate(self, prompt, schema=None, audio=None):
        if audio:
            raise ValueError("text-only experiment")
        if schema is not None:
            prompt += (
                "\nFINAL SDK TRANSPORT CONTRACT (takes priority over embedded candidate schemas): "
                + canonical(schema.model_json_schema())
                + "\nRespond ONLY with JSON matching this transport schema. All string fields, especially input, "
                "must remain JSON strings, never objects. If a string contains JSON, serialize it once with normal JSON escaping. "
                "Do not add candidate-envelope fields to the outer transport response. The candidate instructions describe the CONTENT of the string only."
            )
        else:
            prompt += "\nReturn only the requested Candidate JSON object without markdown fences or explanatory text."
        raw, cost = self.provider.complete(prompt, json_mode=True)
        return (strict_sdk_value(raw, schema) if schema else raw), cost

    async def a_generate(self, *args, **kwargs):
        raise RuntimeError("per-slot generation must be synchronous")


def slot_task(s, plan):
    kind = s["case_kind"]
    dim = s["dimension"]
    instructions = [
        "Generate one Chinese-described evaluation candidate for CURRENT_SLOT. Use only SOURCE contracts. "
        "Do not copy any previous candidate. Invent synthetic values, never outcomes. "
        "Keep intentional missing/invalid/conflicting inputs. Produce JSON without markdown.",
        "CURRENT_SLOT: " + canonical(s),
        "ENVELOPE_SCHEMA: " + canonical(FullCandidate.model_json_schema()),
        "evidence_refs must equal CURRENT_SLOT.evidence_refs exactly. "
        "Do not put oracle, expected output, grading instructions or slot IDs in input. "
        "rationale is a short Chinese explanation. gap=null for supported cases. "
        "preconditions describe isolated controlled fixtures, never real production.",
        "Every extracted parameter value must occur literally in user_input, including English environment test and resource_type. Write environment as 环境 test, not just 测试环境. "
        "Checks use exactly {op,actual,expected}. actual is a STRING path, never a {ref:...} object. Use op=unchanged exactly when specified, never replace it with equals. Keep check order as specified. "
        "Do not add any other assertions or oracle fields.",
    ]
    if s["input_only"]:
        instructions += [
            "Oracle must be null, preconditions must be [], gap must describe the supplied gap. "
            "Do not invent a complete executable test or an expected result."
        ]
        if s["extra_oracle_gap"]:
            instructions += [
                'input must be exactly {"user_input": "Chinese request"}. '
                "Generate the designated missing/invalid intent input; do not infer missing_parameters."
            ]
        else:
            instructions += [
                'input must be exactly {"operation":"contract_gap", "requirement":"Chinese summary of the specific unresolved source requirement", "needed_contract":"what specific stimulus/predicate/contract binding must be supplied"}. '
                "This is a gap description, not a runnable scenario."
            ]
    elif kind == "schema_constraint":
        instructions += [
            'input={operation:"inspect_declared_constraint",pointer:CURRENT_SLOT.pointer}; preconditions=[]. '
            'oracle has only checks:[{op:"equals",actual:"contract"+pointer,expected:the exact source value at that pointer}]. '
            "This is a static contract assertion, not Agent behavior."
        ]
    elif kind == "parameter":
        instructions += [
            'input={operation:"validate_arguments",arguments:{...},parameter:CURRENT_SLOT.parameter,dimension:CURRENT_SLOT.dimension}. '
            "Only mutate the selected parameter; all other arguments must satisfy the parameter schema. "
            "The tool argument schema may require nullable fields; supply them as null if necessary. "
            "Intent schemas may allow omitted fields. Do not call any handler. "
            "valid: selected value is present, non-null, valid. wrong_type: wrong JSON type (not merely wrong value). "
            "omitted: remove selected key, even if optional; overall validity depends on required. "
            "boundary: maximum if declared, otherwise minimum, exclusiveMinimum+1 for integers, minimum string/array length; "
            "phone exactly11 ASCII digits. outside_boundary: same JSON type but invalid constraint value. "
            "For pattern with minLength choose a shortest valid string at minLength. "
            'oracle={arguments_schema_valid:boolean,checks:[{op:"schema_valid",actual:"input.arguments",expected:that same boolean}]}. '
            'preconditions=[{kind:"validation_only",invoke_handler:false}].'
        ]
    elif kind == "intent_case":
        instructions += [
            'input={user_input:"Chinese user request"}. For complete/expression_variant supply all business-required fields, '
            "use exactly one mode per selection group, clear explicit field labels, and preserve every extracted value literally in text (environment test must appear as test, not just 测试环境). "
            "Unsupported requests stay outside all supported intents. "
            "oracle={expected_module_output:{intent:capability_id,status:source complete decision status,next_action:source complete decision action,parameters:{extracted non-null fields only},missing_parameters:[]}}. "
            "Do not add reason or checks in this oracle. preconditions=[]."
        ]
    elif kind == "module_event":
        binding = {
            k: v
            for k, v in EVENT_STIMULI[plan.declared(s)].items()
            if k not in {"user_input", "parameters", "tool_name"}
        }
        if s["target_id"] == "module.execution_guard":
            binding = {"action": "request_disallowed_tool", "allowed_tools": []}
        instructions += [
            'input={operation:"observe_module_event",stimulus:{...}}. '
            "The controlled harness binding requires these trigger fields: "
            + canonical(binding)
            + ". "
            "Add concrete synthetic user_input/parameters/tool_name when needed by the action. "
            'oracle has only checks:[{op:"subset",actual:"trace.event_types",expected:[the selected declared event]}]. '
            'preconditions=[{kind:"controlled_module_harness",isolated:true}].'
        ]
    elif kind == "tool_result":
        instructions += [
            'input={operation:"invoke_tool",tool_name:source tool_name,arguments:{valid argument object}}. '
            "Choose concrete isolated fixture records that actually produce the selected result branch. DUPLICATE_GIFT means repeated IDs in arguments.gift_ids/gift_nums, never duplicate records in fixture. "
            'preconditions include {kind:"fixture_setup",records:{users/gifts/pools/resources/grants as relevant},fresh_instance:true}. '
            "Use full source record shapes for read tools. For add_gift_to_backpack, users and gifts must be explicit lists containing user_id/gift_id records. Matching IDs must match arguments; empty/not-found branches have absent matching records. "
            "For confirmation-required use owner_authorized_attempts:0; other branches of a confirmation tool require1. "
            "For CONFLICT fixture_setup.prior_calls=[{tool_name:source tool,arguments:{prior valid test-environment request with same request_id and different count}}]; omit prior_calls otherwise. Use count <=1000 except LIMIT_EXCEEDED; environment=test except ENVIRONMENT_UNSUPPORTED. "
            "For query_gift_info NOT_FOUND use gift_ids with at least one absent ID (ALL_MUST_EXIST rule), never single gift_id. For EMPTY prefer unmatched gift_name. "
            "For LIMIT_EXCEEDED exceed maximum_fixture_count; for ENVIRONMENT_UNSUPPORTED environment differs from test. "
            'oracle={checks:[{op:"equals",actual:"tool_result.code",expected:CURRENT_SLOT.dimension},'
            '{op:"schema_valid",actual:"tool_result.data",expected:exact source data_schema for that code}],'
            "declared_terminal_status:exact source terminal_status}."
        ]
    elif kind == "chain_case":
        intent_id, branch = dim.split(":")
        if branch == "early_stop":
            instructions += [
                'input={user_input:"Chinese early-stop request",intent_parameters:{extracted non-null fields only}}. For add_backpack_gift give complete parameters but no session confirmation; '
                "unsupported must be an unsupported task with intent_parameters={}. Other intents must omit ALL identifying fields, use intent_parameters={}, and include no digits, @, test, or request_id in user_input; simply request the action without identifying details. "
                "oracle={terminal_status:source intent complete status for unsupported/add_backpack_gift, otherwise source incomplete status}. "
                "No tool must be called. preconditions=[]."
            ]
        else:
            instructions += [
                'input={operation:"agent_run",user_input:"complete Chinese request",intent_id:"'
                + intent_id
                + '",'
                'intent_parameters:{extracted non-null fields},tool_arguments:{complete schema-valid tool arguments},tool_name:the intent required_tool_name,branch:"'
                + branch
                + '"}. '
                'For error add controlled_fault:{at:"tool_handler",behavior:"raise_exception"}. '
                "preconditions=[{kind:fixture_setup,fresh_instance:true,records:{concrete matching users/gifts/pools/resources},owner_authorized_attempts:1 if tool needs confirmation else0}]. Use full source record schemas; environment=test,count<=1000. All parameters must appear explicitly in user_input and agree with tool_arguments. "
                'oracle has only checks:[{op:"equals",actual:"agent_result.status",expected:"FAILED" for error otherwise "SUCCESS"},'
                '{op:"subset",actual:"tool_trace.names",expected:[required_tool_name]}]. '
                "Do not claim multirun recovery or invent ordered-node expectations."
            ]
    elif kind == "tool_rule":
        instructions += [_rule_task(dim, plan.declared(s))]
    return "\n".join(instructions)


def _rule_task(dim, declared):
    common = (
        "All arguments obey the source JSON Schema. preconditions=[{kind:fixture_setup,fresh_instance:true,share_instance_within_case:true,records:{concrete matching users/gifts/pools/resources},owner_authorized_attempts:1 if confirmation tool else0}]. Read records must follow full source result record schemas. Write records need user_id/gift_id. Use environment=test,count<=1000. preconditions must declare isolated fixture initialization, "
        "matching records and owner authorization where required. Never mutate production. "
    )
    if dim in {
        "query_modes",
        "query_mode_cardinality",
        "user_selection_modes",
        "gift_selection_modes",
        "selection_cardinality",
    }:
        return common + (
            'input={operation:"validate_selection_modes",arguments:{...},modes:[source selected mode group]}. '
            "Activate more than one field in that group; keep individual types valid. "
            "If dimension is a cardinality string, choose one declared query_modes/user_selection_modes/gift_selection_modes group from the same source. "
            'oracle={business_arguments_valid:false,checks:[{op:"equals",actual:"argument_validator.accepted",expected:false}]}.'
        )
    if dim == "confirmation":
        return common + (
            'input={operation:"authorization_sequence",tool_name:source tool,steps:[{action:"owner_authorize_one_attempt"},'
            '{action:"invoke",arguments:{...}},{action:"invoke",arguments:{the identical values}}]}. '
            "All selected IDs exist and fixture_setup.owner_authorized_attempts=0 because the first step explicitly grants authorization. "
            "oracle has checks in order: equals step[1].code OK; equals step[2].code CONFIRMATION_REQUIRED; "
            'unchanged state.after_step[2] {ref:"state.after_step[1]"}.'
        )
    if (
        dim == "idempotency_rules"
        and declared.get("mode") == "REQUEST_ID_WITHIN_FIXTURE_INSTANCE"
    ):
        return common + (
            'input={operation:"idempotency_sequence",tool_name:source tool,steps:[{arguments:{...}},{arguments:{identical values}},{arguments:{same request_id but changed count}}]}. '
            "Use one fresh fixture shared across these3 steps. oracle has checks: "
            'equals step[1].resources {ref:"step[0].resources"}; equals step[2].code CONFLICT; '
            'unchanged state.after_step[2] {ref:"state.after_step[1]"}.'
        )
    text = (
        common
        + 'input={operation:"invoke_tool",tool_name:source tool,arguments:{...}}. oracle has only checks. '
    )
    if dim.startswith("default_"):
        field = dim.removeprefix("default_")
        return (
            text
            + f"Set {field}=null to select the default. For default_num require gift_nums=null and select gift_id or gift_ids; explicit gift quantities override the default. One check equals tool_result.data.grants[0].{field} to the declared default value."
        )
    if dim == "duplicate_users":
        return (
            text
            + "Use repeated identical user_ids, null user_id, one gift_id and null gift_ids. One check count tool_result.data.grants 1."
        )
    if dim == "mutation":
        return (
            text
            + 'Use user_ids containing an existing and a missing user; no partial mutation. Checks: equals tool_result.code NOT_FOUND; unchanged fixture.after {ref:"fixture.before"}.'
        )
    return text + 'READ_ONLY: one check unchanged fixture.after {ref:"fixture.before"}.'


class DirectBackend:
    def __init__(self, provider):
        self.provider = provider

    def generate(self, context, s, plan):
        raw, _ = self.provider.complete(
            context
            + "\n"
            + slot_task(s, plan)
            + "\nReturn the complete Candidate JSON.",
            json_mode=True,
        )
        return {"candidate": json.loads(raw), "raw": raw}


class DeepEvalBackend:
    def __init__(self, provider, key):
        if version("deepeval") != "4.3.2":
            raise RuntimeError("deepeval==4.3.2 required")
        self.model = ControlledDeepSeek(provider, key)

    def generate(self, context, s, plan):
        from deepeval.synthesizer import Synthesizer
        from deepeval.synthesizer.config import (
            EvolutionConfig,
            FiltrationConfig,
            StylingConfig,
        )

        task = slot_task(s, plan)
        input_format = (
            'Return a JSON text string encoding exactly {"input":{structured stimulus described by CURRENT_SLOT},'
            '"preconditions":[structured fixture setup]}. Include no oracle, gap, rationale, evidence_refs or expected answer. '
            "Do not rewrite an intentionally invalid value into a valid value."
        )
        syn = Synthesizer(
            model=self.model,
            async_mode=False,
            filtration_config=FiltrationConfig(
                critic_model=self.model,
                synthetic_input_quality_threshold=0,
                max_quality_retries=1,
            ),
            evolution_config=EvolutionConfig(num_evolutions=0),
            styling_config=StylingConfig(
                scenario=task,
                task="Author the designated source-bound evaluation stimulus.",
                input_format=input_format,
                expected_output_format=None
                if s["input_only"]
                else "Return complete Candidate JSON as specified. Its input and preconditions must equal the current Input JSON values exactly. Derive oracle solely from those inputs and the source contract. "
                + task,
            ),
        )
        goldens = syn.generate_goldens_from_contexts(
            contexts=[[context, task]],
            include_expected_output=not s["input_only"],
            max_goldens_per_context=1,
            _send_data=False,
        )
        if len(goldens) != 1:
            raise ValueError("expected one Golden")
        g = goldens[0]
        stimulus = json.loads(g.input)
        if not isinstance(stimulus, dict) or set(stimulus) != {
            "input",
            "preconditions",
        }:
            raise ValueError("Golden input has unexpected fields")
        if s["input_only"]:
            if g.expected_output is not None:
                raise ValueError("blocked Golden invented oracle")
            c = {
                **stimulus,
                "oracle": None,
                "evidence_refs": s["evidence_refs"],
                "rationale": "输入/缺口说明由模型生成；预期契约缺失。",
                "gap": s["gap_reason"],
            }
        else:
            c = json.loads(g.expected_output)
            if (
                c.get("input") != stimulus["input"]
                or c.get("preconditions") != stimulus["preconditions"]
            ):
                raise ValueError("Golden oracle rewrote its original stimulus")
        return {
            "candidate": c,
            "raw": {
                "input": g.input,
                "expected_output": g.expected_output,
                "metadata": g.additional_metadata,
            },
        }
