"""Shared strict model base for the portable capability protocol."""

from pydantic import BaseModel, ConfigDict


class ProtocolModel(BaseModel):
    """Reject fields that are not part of the declared protocol."""

    model_config = ConfigDict(extra="forbid")
