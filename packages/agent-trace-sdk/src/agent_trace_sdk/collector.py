"""Agent compatibility facade using Inspect's native Transcript collector."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from inspect_ai.event import InfoEvent
from inspect_ai.log import Transcript
from pydantic_core import to_jsonable_python


class TraceCollector:
    def __init__(
        self,
        run_id,
        *,
        session_id=None,
        event_id_factory=None,
        timestamp_factory=None,
        sink=None,
        context=None,
        rules=None,
    ):
        self.run_id = run_id
        self.session_id = session_id
        self.context = context
        self._sink = sink
        self._rules = rules or {}
        self._transcript = Transcript()
        self._event_id_factory = event_id_factory or (lambda: f"event_{uuid4().hex}")
        self._timestamp_factory = timestamp_factory or (
            lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
        )

    def record(self, event_type, payload=None, *, session_id=None):
        event = dict(
            event_id=self._event_id_factory(),
            run_id=self.run_id,
            session_id=session_id or self.session_id,
            event_type=event_type,
            timestamp=self._timestamp_factory(),
            payload=deepcopy(payload or {}),
        )
        if self._sink is not None:
            self._sink.record(
                event, context=self.context, rule=self._rules.get(event_type)
            )
        # Business validation must see the original payload first. Native JSON
        # validation of the compatibility projection must not interrupt the
        # Agent (or put raw secret values in a ValidationError).
        try:
            projection = to_jsonable_python(
                event, fallback=lambda _: "[UNSERIALIZABLE]"
            )
        except Exception:
            projection = {
                key: value
                if isinstance(value, (str, type(None)))
                else "[UNSERIALIZABLE]"
                for key, value in event.items()
                if key != "payload"
            }
            projection["payload"] = {"_compatibility_projection_unavailable": True}
        self._transcript.info(projection, source="agent_output")

    def export(self):
        """Agent return-value projection; never an independent evidence fallback."""
        return [
            deepcopy(event.data)
            for event in self._transcript.events
            if isinstance(event, InfoEvent)
        ]
