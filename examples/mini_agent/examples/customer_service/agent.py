"""Deterministic demonstration Agent, not a production customer-service system."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AGENT_VERSION = "customer-demo-v1"
POLICY_VERSION = "example-policy-v1"
EXAMPLE_POLICY = "示例政策：未使用的商品可在购买后 7 天内申请退款，需人工核实订单。"


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    user_input: str = Field(max_length=4000)


class CustomerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["SUCCESS", "NEED_CLARIFICATION", "HANDOFF_SUGGESTED"]
    final_response: str
    policy_version: str
    handoff_executed: Literal[False] = False
    events: list[str]


class CustomerServiceAgent:
    def run(self, user_input: str) -> CustomerResult:
        message = CustomerInput(user_input=user_input).user_input.strip()
        if not message:
            status = "NEED_CLARIFICATION"
            reply = "请说明你想咨询的问题。"
        elif "退款" in message:
            status = "SUCCESS"
            reply = EXAMPLE_POLICY
        else:
            status = "HANDOFF_SUGGESTED"
            reply = "这个问题超出示例政策范围，建议联系人工客服；尚未执行转接。"
        return CustomerResult(
            status=status,
            final_response=reply,
            policy_version=POLICY_VERSION,
            events=["run_started", "response_ready", "run_finished"],
        )
