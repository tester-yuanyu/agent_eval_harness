"""Strict fixture output records shared by handlers and exported schemas."""

from typing import Annotated

from pydantic import Field

from minimal_agent.contracts.intent_parameters import (
    EmailString,
    NonEmptyString,
    PhoneString,
    PositiveInt,
    PositiveIntList,
    StrictToolArguments,
)


class ResourceRecord(StrictToolArguments):
    resource_id: PositiveInt
    resource_type: NonEmptyString
    environment: NonEmptyString


class UserRecord(StrictToolArguments):
    user_id: PositiveInt
    room_id: PositiveInt
    email: EmailString
    phone: PhoneString


class GiftRecord(StrictToolArguments):
    gift_id: PositiveInt
    gift_name: NonEmptyString


class PoolRecord(StrictToolArguments):
    pool_id: PositiveInt
    gift_ids: PositiveIntList


class GrantRecord(StrictToolArguments):
    user_id: PositiveInt
    gift_id: PositiveInt
    num: Annotated[int, Field(ge=1, le=1000)]
    duration_days: Annotated[int, Field(ge=1, le=1000)]


ROW_MODELS = {
    "resources": ResourceRecord,
    "user": UserRecord,
    "gifts": GiftRecord,
    "pools": PoolRecord,
    "grants": GrantRecord,
}
