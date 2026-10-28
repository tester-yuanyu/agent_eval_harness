"""Strict parameter contracts for the Agent's formal Intent vocabulary."""

from typing import Annotated, Self

from pydantic import ConfigDict, Field, model_validator

from minimal_agent.contracts.agent import ProtocolModel

PositiveInt = Annotated[int, Field(gt=0)]
NonEmptyString = Annotated[str, Field(min_length=1)]
PositiveIntList = Annotated[list[PositiveInt], Field(min_length=1)]


EmailString = Annotated[
    str,
    Field(min_length=3, pattern=r"^[^@]+@[^@]+$"),
]
PhoneString = Annotated[str, Field(pattern=r"^[0-9]{11}$")]


class StrictToolArguments(ProtocolModel):
    """Base class for strict, model-visible Intent parameters."""

    model_config = ConfigDict(extra="forbid", strict=True)


class GiftQuantity(StrictToolArguments):
    """One gift and its quantity in a strict batch payload."""

    gift_id: PositiveInt
    num: int = Field(ge=1, le=1000)


class QueryUserInfoArguments(StrictToolArguments):
    """Lookup a mock user using one or more combined conditions."""

    user_id: PositiveInt | None
    room_id: PositiveInt | None
    email: EmailString | None
    phone: PhoneString | None

    @model_validator(mode="after")
    def require_query_condition(self) -> Self:
        if all(
            value is None
            for value in (self.user_id, self.room_id, self.email, self.phone)
        ):
            raise ValueError("at least one user query condition is required")
        return self


class QueryGiftInfoArguments(StrictToolArguments):
    """Query mock gift details using exactly one lookup mode."""

    gift_id: PositiveInt | None
    gift_ids: PositiveIntList | None
    gift_name: NonEmptyString | None
    limit: PositiveInt | None

    @model_validator(mode="after")
    def require_exactly_one_query_mode(self) -> Self:
        modes = (self.gift_id, self.gift_ids, self.gift_name)
        if sum(value is not None for value in modes) != 1:
            raise ValueError("exactly one gift query mode is required")
        return self


class AddGiftToBackpackArguments(StrictToolArguments):
    """Business parameters for a confirmed mock backpack grant."""

    gift_id: PositiveInt | None
    gift_ids: PositiveIntList | None
    gift_nums: Annotated[list[GiftQuantity], Field(min_length=1)] | None
    user_id: PositiveInt | None
    user_ids: PositiveIntList | None
    num: Annotated[int, Field(ge=1, le=1000)] | None
    duration_days: Annotated[int, Field(ge=1, le=1000)] | None

    @model_validator(mode="after")
    def validate_selection_modes(self) -> Self:
        user_modes = (self.user_id, self.user_ids)
        if sum(value is not None for value in user_modes) != 1:
            raise ValueError("exactly one user selection mode is required")

        gift_modes = (self.gift_id, self.gift_ids, self.gift_nums)
        if sum(value is not None for value in gift_modes) != 1:
            raise ValueError("exactly one gift selection mode is required")
        return self


class QueryPoolConfigArguments(StrictToolArguments):
    """Query mock pools using exactly one lookup mode."""

    gift_id: PositiveInt | None
    pool_id: PositiveInt | None

    @model_validator(mode="after")
    def require_exactly_one_query_mode(self) -> Self:
        if (self.gift_id is None) == (self.pool_id is None):
            raise ValueError("exactly one pool query mode is required")
        return self


SHADOW_TOOL_ARGUMENT_MODELS = {
    "query_user_info": QueryUserInfoArguments,
    "query_gift_info": QueryGiftInfoArguments,
    "add_gift_to_backpack": AddGiftToBackpackArguments,
    "query_pool_config": QueryPoolConfigArguments,
}
