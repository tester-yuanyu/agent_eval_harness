"""Small functional fixture; data/state never enter capability snapshots."""

from copy import deepcopy

from minimal_agent.contracts.tools import ToolResult
from minimal_agent.runtime.tool_binding import bind_tools
from minimal_agent.runtime.tool_registry import ToolRegistry

from .contracts import CONTRACTS
from .results import ROW_MODELS


class FixtureEnvironment:
    def __init__(self):
        self.users = {
            10001: {
                "user_id": 10001,
                "room_id": 20001,
                "email": "example-user@example.invalid",
                "phone": "13000000001",
            },
            10002: {
                "user_id": 10002,
                "room_id": 20002,
                "email": "other-user@example.invalid",
                "phone": "13000000002",
            },
        }
        self.gifts = {
            101: {"gift_id": 101, "gift_name": "Rose"},
            102: {"gift_id": 102, "gift_name": "Star"},
        }
        self.pools = {201: {"pool_id": 201, "gift_ids": [101, 102]}}
        self.resources = []
        self.requests = {}
        self.grants = []
        self._grant_approved = False

    def registry(self) -> ToolRegistry:
        return bind_tools(
            CONTRACTS,
            {contract.name: getattr(self, contract.name) for contract in CONTRACTS},
        )

    def approve_next_grant(self) -> None:
        """Fixture owner only; not exposed as a model-callable tool."""
        self._grant_approved = True

    @staticmethod
    def _ok(field, value):
        model = ROW_MODELS[field]
        if isinstance(value, list):
            value = [model.model_validate(row).model_dump() for row in value]
        elif value is not None:
            value = model.model_validate(value).model_dump()
        return ToolResult(
            success=True,
            code="OK" if value else "EMPTY",
            message="isolated example fixture result",
            data={field: deepcopy(value)},
        )

    @staticmethod
    def _failure(code):
        return ToolResult(
            success=False,
            code=code,
            message="isolated example fixture: " + code,
            data={},
        )

    def query_information(self, resource_type, environment):
        if environment != "test":
            return self._failure("ENVIRONMENT_UNSUPPORTED")
        return self._ok(
            "resources",
            [
                row
                for row in self.resources
                if row["resource_type"] == resource_type
                and row["environment"] == environment
            ],
        )

    def prepare_resource(self, resource_type, environment, count, request_id):
        if environment != "test":
            return self._failure("ENVIRONMENT_UNSUPPORTED")
        if count > 1000:
            return self._failure("LIMIT_EXCEEDED")
        key = (resource_type, environment, count)
        previous = self.requests.get(request_id)
        if previous:
            return (
                self._ok("resources", previous[1])
                if previous[0] == key
                else self._failure("CONFLICT")
            )
        rows = [
            {
                "resource_id": len(self.resources) + offset + 1,
                "resource_type": resource_type,
                "environment": environment,
            }
            for offset in range(count)
        ]
        self.resources.extend(rows)
        self.requests[request_id] = (key, rows)
        return self._ok("resources", rows)

    def query_user_info(self, **conditions):
        found = next(
            (
                row
                for row in self.users.values()
                if all(
                    row[key] == value
                    for key, value in conditions.items()
                    if value is not None
                )
            ),
            None,
        )
        return self._ok("user", found)

    def query_gift_info(self, gift_id, gift_ids, gift_name, limit):
        ids = [gift_id] if gift_id is not None else gift_ids
        if ids is not None:
            if gift_ids is not None and any(i not in self.gifts for i in ids):
                return self._failure("NOT_FOUND")
            rows = [self.gifts[i] for i in sorted(set(ids)) if i in self.gifts]
        else:
            rows = [
                row
                for _, row in sorted(self.gifts.items())
                if gift_name.casefold() in row["gift_name"].casefold()
            ]
        return self._ok("gifts", rows[:limit] if limit is not None else rows)

    def query_pool_config(self, gift_id, pool_id):
        rows = [
            row
            for _, row in sorted(self.pools.items())
            if (
                row["pool_id"] == pool_id
                if pool_id is not None
                else gift_id in row["gift_ids"]
            )
        ]
        return self._ok("pools", rows)

    def add_gift_to_backpack(
        self,
        gift_id,
        gift_ids,
        gift_nums,
        user_id,
        user_ids,
        num,
        duration_days,
    ):
        if not self._grant_approved:
            return self._failure("CONFIRMATION_REQUIRED")
        self._grant_approved = False
        users = sorted(set([user_id] if user_id is not None else user_ids))
        quantities = (
            gift_nums
            if gift_nums is not None
            else [
                {"gift_id": value, "num": num if num is not None else 1}
                for value in ([gift_id] if gift_id is not None else gift_ids)
            ]
        )
        if len({item["gift_id"] for item in quantities}) != len(quantities):
            return self._failure("DUPLICATE_GIFT")
        if any(value not in self.users for value in users) or any(
            item["gift_id"] not in self.gifts for item in quantities
        ):
            return self._failure("NOT_FOUND")
        grants = [
            {
                "user_id": user,
                **item,
                "duration_days": duration_days if duration_days is not None else 7,
            }
            for user in users
            for item in quantities
        ]
        self.grants.extend(deepcopy(grants))
        return self._ok("grants", grants)
