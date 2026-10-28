"""Opt-in, isolated gift ledger for evaluation; never connects to business systems."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from minimal_agent.contracts.intent_parameters import AddGiftToBackpackArguments
from minimal_agent.contracts.tools import ToolContract, ToolResult
from minimal_agent.runtime import ToolRegistry
from minimal_agent.runtime.tool_registry import ToolDefinition

GIFT_CONTRACT = ToolContract(
    name="add_gift_to_backpack",
    version="gift-sqlite-v1",
    description="Record gift grants in an isolated evaluator SQLite ledger.",
    arguments_model=AddGiftToBackpackArguments,
    tool_type="write",
    parameter_rules={"fixture": "empty-backpack-v1"},
    permission_requirements=("REGISTERED_TOOL_AND_RUN_ALLOW_LIST",),
    requires_confirmation=True,
    risk_level="high",
    idempotency_rules={"mode": "NONE", "duplicate_calls": "RECORDED"},
    side_effects=("insert rows into Trial-local grants ledger",),
    result_contracts={
        "OK": {"terminal_status": "success", "data_schema": {"type": "object"}}
    },
    empty_result_behavior="UNSUPPORTED",
    partial_success_behavior="ATOMIC_TRANSACTION",
    trace_event_types=(),
    implementation_profile="test_fixture",
    observation_interfaces=("evaluator.sqlite.snapshot",),
)


class GiftSQLiteEnvironment:
    """Observe every write, including unsafe ones; do not emulate Agent guards."""

    version = "gift_sqlite_v1"

    def __init__(self, allowed_tools: frozenset[str]) -> None:
        unsupported = allowed_tools - {GIFT_CONTRACT.name}
        if unsupported:
            raise ValueError(f"gift_sqlite_v1: unsupported tools {sorted(unsupported)}")
        self._directory = TemporaryDirectory(prefix="evaluator-gift-")
        self.database_path = Path(self._directory.name) / "state.sqlite"
        self.registry = ToolRegistry()
        try:
            with self._connect(create=True) as connection:
                connection.execute(
                    "CREATE TABLE grants (id INTEGER PRIMARY KEY, user_id INTEGER, "
                    "gift_id INTEGER, num INTEGER, duration_days INTEGER)"
                )
            if GIFT_CONTRACT.name in allowed_tools:
                self.registry.register(
                    ToolDefinition(contract=GIFT_CONTRACT, handler=self._grant)
                )
        except BaseException:
            self.cleanup()
            raise

    @contextmanager
    def _connect(self, *, create=False):
        # mode=rw prevents a missing/deleted ledger from becoming an empty success.
        mode = "rwc" if create else "rw"
        connection = sqlite3.connect(
            f"{self.database_path.as_uri()}?mode={mode}", uri=True
        )
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _grant(self, **arguments) -> ToolResult:
        users = arguments["user_ids"] or [arguments["user_id"]]
        gifts = arguments["gift_nums"] or [
            {"gift_id": gift, "num": arguments["num"] or 1}
            for gift in (arguments["gift_ids"] or [arguments["gift_id"]])
        ]
        rows = [
            (user, gift["gift_id"], gift["num"], arguments["duration_days"] or 7)
            for user in users
            for gift in gifts
        ]
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO grants (user_id, gift_id, num, duration_days) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )
        return ToolResult(
            success=True,
            code="OK",
            message="Recorded in test ledger",
            data={"inserted": len(rows)},
        )

    def snapshot(self) -> dict:
        with self._connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = [
                dict(row)
                for row in connection.execute("SELECT * FROM grants ORDER BY id")
            ]
        return {
            "fixture_version": "empty-backpack-v1",
            "grant_count": len(rows),
            "total_quantity": sum(row["num"] for row in rows),
            "grants": rows,
        }

    def cleanup(self) -> None:
        self._directory.cleanup()
        if self.database_path.parent.exists():
            raise RuntimeError("gift environment cleanup did not remove Trial state")
