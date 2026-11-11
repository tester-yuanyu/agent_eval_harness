"""显式同步保存结果；profile、限流与续传不拥有执行或评分。"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import ipaddress
import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx

from ..observability import stable_id
from .report_links import safe_base
from .runner import save_json


@dataclass(frozen=True)
class DeliveryProfile:
    profile: str
    base_url: str
    project_id: str
    public_key_env: str
    secret_key_env: str
    intervals: dict = field(default_factory=dict)

    def credentials(self) -> tuple[str, str]:
        values = [
            os.environ.get(key, "").strip()
            for key in (self.public_key_env, self.secret_key_env)
        ]
        for key, value in zip(
            (self.public_key_env, self.secret_key_env), values, strict=True
        ):
            if not value:
                raise ValueError(
                    f"Missing profile credential environment variable: {key}"
                )
        return values[0], values[1]

    def destination(self) -> str:
        public, _ = self.credentials()
        # Preserve the historical export fingerprint algorithm.
        return stable_id(self.base_url, public)

    def client(self):
        from ..optional_dependencies import require_langfuse

        require_langfuse()
        from langfuse.api.client import LangfuseAPI

        public, secret = self.credentials()
        return LangfuseAPI(
            base_url=self.base_url,
            username=public,
            password=secret,
            headers={"x-langfuse-ingestion-version": "4"},
            timeout=30,
            follow_redirects=False,
        )


def load_profile(path: Path) -> DeliveryProfile:
    data = json.loads(Path(path).read_text())
    allowed = {
        "profile",
        "base_url",
        "project_id",
        "public_key_env",
        "secret_key_env",
        "intervals",
    }
    if not isinstance(data, dict) or set(data) - allowed:
        raise ValueError(
            "unknown profile fields; credentials must use environment references"
        )
    required = allowed - {"intervals"}
    if any(not isinstance(data.get(k), str) or not data[k].strip() for k in required):
        raise ValueError("Incomplete explicit delivery profile")
    if data["profile"] not in {"local", "cloud"}:
        raise ValueError("profile must be local or cloud")
    base = safe_base(data["base_url"])
    url = urlsplit(base)
    if url.path not in ("", "/"):
        raise ValueError("Profile requires an origin URL")
    try:
        local = (
            url.hostname == "localhost"
            or ipaddress.ip_address(url.hostname).is_loopback
        )
    except ValueError:
        local = False
    if data["profile"] == "local" and not local:
        raise ValueError("local profile requires a loopback URL")
    if data["profile"] == "cloud" and (local or url.scheme != "https"):
        raise ValueError("cloud profile requires a remote HTTPS URL")
    intervals = data.get("intervals", {})
    RateLimiter(intervals)  # Validate before creating a client or contacting a server.
    return DeliveryProfile(**{**data, "base_url": base})


class RateLimiter:
    """Separate Dataset, Tracing and Read schedules shared by all SDK calls."""

    def __init__(self, intervals: dict, *, clock=time.monotonic, sleep=time.sleep):
        if not isinstance(intervals, dict) or set(intervals) - {
            "dataset",
            "tracing",
            "read",
        }:
            raise ValueError("unknown rate bucket")
        if any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v < 0
            for v in intervals.values()
        ):
            raise ValueError("Rate intervals must be finite nonnegative seconds")
        self.intervals = {"dataset": 0, "tracing": 0, "read": 0, **intervals}
        self.clock, self.sleep = clock, sleep
        self.next = dict.fromkeys(self.intervals, 0.0)
        self.locks = {bucket: threading.Lock() for bucket in self.intervals}

    def wait(self, bucket: str) -> None:
        with self.locks[bucket]:
            delay = max(0, self.next[bucket] - self.clock())
            if delay:
                self.sleep(delay)
            self.next[bucket] = self.clock() + self.intervals[bucket]

    def defer(self, bucket: str, headers: dict | None) -> None:
        value = next(
            (v for k, v in (headers or {}).items() if k.lower() == "retry-after"), "1"
        )
        try:
            delay = float(value)
        except (ValueError, TypeError):
            try:
                delay = (
                    parsedate_to_datetime(value) - datetime.now(UTC)
                ).total_seconds()
            except (ValueError, TypeError, OverflowError):
                delay = 1
        if not math.isfinite(delay):
            delay = 1
        with self.locks[bucket]:
            self.next[bucket] = max(self.next[bucket], self.clock() + max(0, delay))


class NeedsReconciliation(RuntimeError):
    """Absence from an eventually consistent index is not proof of rejection."""


class _Reply(SimpleNamespace):
    def model_dump(self, **_kwargs):
        return vars(self)


def _json_default(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(type(value).__name__)


class _Resource:
    def __init__(self, owner, name):
        self.owner, self.name = owner, name

    def __getattr__(self, method):
        def invoke(**kwargs):
            return self.owner.call(self.name, method, kwargs)

        return invoke


class DeliveryClient:
    """Journal mutations before sending; reconcile uncertain IDs before any reuse.

    Journal ownership is one sync process per run. The thread lock protects the
    existing exporter's item workers. Payloads and credentials are never stored.
    """

    def __init__(self, client, journal: Path, *, destination: str, limiter=None):
        self.raw, self.path, self.destination = client, Path(journal), destination
        self.limiter = limiter or RateLimiter({})
        self.lock = threading.RLock()
        self.state = (
            json.loads(self.path.read_text())
            if self.path.exists()
            else {"destination": destination, "operations": {}}
        )
        if self.state["destination"] != destination:
            raise ValueError("Immutable delivery destination changed")

    def __getattr__(self, name):
        return _Resource(self, name)

    def _request(self, resource, method, kwargs, bucket):
        for attempt in range(3):
            self.limiter.wait(bucket)
            try:
                return getattr(getattr(self.raw, resource), method)(
                    **{**kwargs, "request_options": {"max_retries": 0}}
                )
            except Exception as error:
                if getattr(error, "status_code", None) != 429:
                    raise
                self.limiter.defer(bucket, getattr(error, "headers", None))
                if attempt == 2:
                    raise

    def call(self, resource: str, method: str, kwargs: dict):
        write = method in {"create", "export_traces"}
        bucket = (
            ("dataset" if resource in {"datasets", "dataset_items"} else "tracing")
            if write
            else "read"
        )
        if not write:
            return self._request(resource, method, kwargs, bucket)
        wire = {k: v for k, v in kwargs.items() if k != "request_options"}
        key = hashlib.sha256(
            json.dumps(
                [resource, method, wire], sort_keys=True, default=_json_default
            ).encode()
        ).hexdigest()
        with self.lock:
            operation = self.state["operations"].get(key)
            if operation:
                if operation["status"] == "ACCEPTED":
                    return _Reply(**operation["response"])
                return self._reconcile(operation)
            operation = {"resource": resource, "status": "UNCERTAIN"}
            if resource == "datasets":
                operation["name"] = kwargs["name"]
            elif resource == "dataset_items":
                operation["ids"] = [kwargs["id"]]
            elif resource == "scores":
                operation["ids"] = [s.id for s in kwargs["request"]]
                operation["traces"] = list(
                    dict.fromkeys(s.trace_id for s in kwargs["request"])
                )
            elif resource == "opentelemetry":
                spans = [
                    s
                    for r in kwargs["resource_spans"]
                    for scope in r.scope_spans
                    for s in scope.spans
                ]
                operation["ids"] = [s.span_id for s in spans]
                operation["traces"] = list(dict.fromkeys(s.trace_id for s in spans))
            else:
                raise ValueError(f"Unsupported delivery mutation: {resource}.{method}")
            self.state["operations"][key] = operation
            save_json(self.path, self.state)
            try:
                result = self._request(resource, method, kwargs, bucket)
            except Exception as error:
                # Only connect failures and explicit rejection prove no acceptance.
                if isinstance(
                    error, (httpx.ConnectError, httpx.ConnectTimeout)
                ) or getattr(error, "status_code", None) in {
                    400,
                    401,
                    403,
                    404,
                    422,
                    429,
                }:
                    del self.state["operations"][key]
                    save_json(self.path, self.state)
                raise
            body = result.model_dump()
            partial = body.get("partial_success") or body.get("partialSuccess") or {}
            if (
                partial.get("rejected_spans")
                or partial.get("rejectedSpans")
                or partial.get("error_message")
                or partial.get("errorMessage")
                or body.get("rejected")
                or body.get("errors")
                or (
                    resource == "scores"
                    and body.get("accepted", len(operation["ids"]))
                    != len(operation["ids"])
                )
            ):
                raise NeedsReconciliation(
                    "Partial acceptance requires remote ID readback"
                )
            response = (
                {"id": result.id, "name": kwargs["name"]}
                if resource == "datasets"
                else {"accepted": len(operation["ids"])}
                if resource == "scores"
                else {}
            )
            operation.update(status="ACCEPTED", response=response)
            save_json(self.path, self.state)
            return result

    def _reconcile(self, operation):
        resource = operation["resource"]
        try:
            if resource == "datasets":
                result = self._request(
                    "datasets", "get", {"dataset_name": operation["name"]}, "read"
                )
                if result.name != operation["name"]:
                    raise NeedsReconciliation("Dataset name mismatch")
                response = {"id": result.id, "name": result.name}
            elif resource == "dataset_items":
                result = self._request(
                    resource, "get", {"id": operation["ids"][0]}, "read"
                )
                if result.id != operation["ids"][0]:
                    raise NeedsReconciliation("Dataset item ID mismatch")
                response = {}
            else:
                from .langfuse_export import _paginate

                rows = []
                for trace in operation["traces"]:
                    method = (
                        self.observations.get_many
                        if resource == "opentelemetry"
                        else self.scores.get_many
                    )
                    rows.extend(
                        _paginate(
                            method,
                            trace_id=trace,
                            fields="core" if resource == "opentelemetry" else "subject",
                        )
                    )
                found = {row["id"] for row in rows}
                if not set(operation["ids"]).issubset(found):
                    raise NeedsReconciliation(
                        "Uncertain IDs are not fully indexed; no replay"
                    )
                response = (
                    {"accepted": len(operation["ids"])} if resource == "scores" else {}
                )
        except Exception as error:
            if getattr(error, "status_code", None) == 404:
                raise NeedsReconciliation(
                    "Uncertain ID is not indexed; no replay"
                ) from None
            raise
        operation.update(status="ACCEPTED", response=response)
        save_json(self.path, self.state)
        return _Reply(**response)

    def reconcile_inflight(self, ids: list[str]) -> None:
        with self.lock:
            for operation in self.state["operations"].values():
                if operation["resource"] == "opentelemetry" and set(ids) == set(
                    operation["ids"]
                ):
                    if operation["status"] != "ACCEPTED":
                        self._reconcile(operation)
                    return
        raise NeedsReconciliation("No matching journal for inflight IDs; no replay")


def _exclusive_sync(function):
    @wraps(function)
    def locked(run_dir, *args, **kwargs):
        with (Path(run_dir) / ".langfuse_delivery.lock").open("a") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Delivery is already active for this run") from None
            try:
                return function(run_dir, *args, **kwargs)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    return locked


@_exclusive_sync
def sync_run(
    run_dir: Path,
    dataset_path: Path,
    *,
    profile: DeliveryProfile,
    client=None,
    destination: str | None = None,
    verification_attempts: int = 3,
    index_wait: float = 2,
    sleep=time.sleep,
    dashboard: bool = False,
) -> dict:
    """Explicit opt-in: replay saved artifacts, then bounded read-only verification."""
    from .langfuse_export import export_metadata_evidence, export_run, verify_run
    from .phase_timing import timed_phase

    if verification_attempts < 1 or not math.isfinite(index_wait) or index_wait < 0:
        raise ValueError("Invalid bounded verification policy")
    root = Path(run_dir)
    source = hashlib.sha256((root / "results.json").read_bytes()).hexdigest()
    target = destination or profile.destination()
    path = root / "langfuse_delivery.json"
    if path.exists():
        previous = json.loads(path.read_text())
        if previous["source_hash"] != source or previous["destination"] != target:
            raise ValueError("Immutable delivery source/destination changed")
    state = {
        "version": "langfuse-delivery-v1",
        "source_hash": source,
        "destination": target,
        "profile": profile.profile,
        "local_status": "COMPLETE",
        "sync_status": "PENDING",
        "verification_attempts": 0,
    }
    save_json(path, state)
    wrapped = None
    try:
        wrapped = DeliveryClient(
            client if client is not None else profile.client(),
            root / "langfuse_delivery_journal.json",
            destination=target,
            limiter=RateLimiter(profile.intervals, sleep=sleep),
        )
        labels = {"source_hash": source, "destination": target}
        with timed_phase(root, "langfuse_export", **labels):
            export_run(root, dataset_path, client=wrapped)
        with timed_phase(root, "langfuse_metadata_export", **labels):
            export_metadata_evidence(root, dataset_path, client=wrapped)
        for attempt in range(verification_attempts):
            with timed_phase(
                root, "langfuse_index_wait", attempt=attempt + 1, **labels
            ):
                sleep(index_wait)
            with timed_phase(root, "langfuse_verify", attempt=attempt + 1, **labels):
                result = verify_run(root, dataset_path, client=wrapped)
            state["verification_attempts"] = attempt + 1
            if result["status"] == "VERIFIED":
                state["sync_status"] = "VERIFIED"
                break
        else:
            state["sync_status"] = "PENDING_INDEX"
    except Exception as error:
        uncertain = wrapped is not None and any(
            op["status"] == "UNCERTAIN" for op in wrapped.state["operations"].values()
        )
        state["sync_status"] = (
            "NEEDS_RECONCILIATION"
            if uncertain
            or isinstance(
                error,
                (
                    NeedsReconciliation,
                    httpx.ReadTimeout,
                    httpx.WriteTimeout,
                    httpx.ReadError,
                    httpx.WriteError,
                ),
            )
            else "FAILED"
        )
        state["error_type"] = type(error).__name__
    if dashboard:
        state.update(dashboard_status="PENDING", delivery_status="PENDING_DATA")
        if state["sync_status"] == "VERIFIED":
            from .dashboard_delivery import deliver_dashboard

            try:
                presentation = deliver_dashboard(root, profile=profile, client=client)
                state.update(
                    {
                        key: presentation[key]
                        for key in (
                            "dashboard_status",
                            "delivery_status",
                            "dashboard_url",
                            "presentation_dir",
                        )
                        if key in presentation
                    }
                )
            except Exception as error:
                state.update(
                    dashboard_status="FAILED",
                    delivery_status="PENDING_DASHBOARD",
                    dashboard_error_type=type(error).__name__,
                )
    save_json(path, state)
    return state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--verification-attempts", type=int, default=3)
    parser.add_argument("--index-wait", type=float, default=2)
    parser.add_argument(
        "--data-only", action="store_true", help="仅导出证据；默认还交付统计看板"
    )
    args = parser.parse_args(argv)
    result = sync_run(
        args.run,
        args.dataset,
        profile=load_profile(args.profile),
        verification_attempts=args.verification_attempts,
        index_wait=args.index_wait,
        dashboard=not args.data_only,
    )
    print(json.dumps(result, ensure_ascii=False))
    complete = result["sync_status"] == "VERIFIED" and (
        args.data_only or result.get("delivery_status") == "COMPLETE"
    )
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
