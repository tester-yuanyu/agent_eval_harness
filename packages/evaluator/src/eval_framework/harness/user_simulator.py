"""Deterministic public user turns; no Oracle or scoring dependency."""

from __future__ import annotations

from collections.abc import Sequence


class FixedFollowupUserSimulator:
    def __init__(self, prompt: str, followups: Sequence[str] = ()) -> None:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("task prompt must be nonempty text")
        if isinstance(followups, str) or not all(
            isinstance(value, str) for value in followups
        ):
            raise ValueError("followups must be user-message strings")
        self._messages = (prompt, *followups)

    def next_message(self, history: Sequence[dict]) -> dict[str, str] | None:
        index = sum(message.get("role") == "user" for message in history)
        if index >= len(self._messages):
            return None
        return {"role": "user", "content": self._messages[index]}

    def should_terminate(self, history: Sequence[dict]) -> bool:
        return self.next_message(history) is None


def public_messages(prompt: str, followups: Sequence[str] = ()) -> list[str]:
    """Materialize the fixed plan passed to independent Agent workers."""
    simulator = FixedFollowupUserSimulator(prompt, followups)
    history = []
    while (message := simulator.next_message(history)) is not None:
        history.append(message)
    return [message["content"] for message in history]
