"""Audited, explicit sampling settings for both comparison arms."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

FLASH_PRICING = {"cache_hit": 0.006, "cache_miss": 0.3, "output": 1.2}
PRICING_REFERENCE = "https://api-docs.deepseek.com/quick_start/pricing/"


class ControlledProvider:
    def __init__(self, http, model: str, api_key: str, log_path: Path):
        self.http = http
        self.model = model
        self._api_key = api_key
        self.log_path = Path(log_path)
        self.calls = []
        self.slot_id = None
        self.attempt = None

    def complete(self, prompt: str, *, json_mode: bool) -> tuple[str, float]:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 4096,
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        record = {
            "index": len(self.calls) + 1,
            "slot_id": self.slot_id,
            "attempt": self.attempt,
            "started_at": datetime.now(UTC).isoformat(),
            "request_body": payload,
            "status_code": None,
            "response_body": None,
            "usage": None,
        }
        start = time.monotonic()
        try:
            response = self.http.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": "Bearer " + self._api_key},
                json=payload,
            )
            record["status_code"] = response.status_code
            record["request_sha256"] = hashlib.sha256(
                response.request.content
            ).hexdigest()
            try:
                body = response.json()
            except ValueError:
                record["response_text"] = response.text
                raise ValueError("provider response is not JSON") from None
            record["response_body"] = body
            record["usage"] = body.get("usage")
            if response.status_code != 200:
                raise RuntimeError(f"provider returned HTTP {response.status_code}")
            choices = body.get("choices") or []
            if not choices or choices[0].get("finish_reason") != "stop":
                raise ValueError("provider did not finish a complete response")
            content = choices[0].get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("provider returned no text")
            if self._api_key in content:
                raise RuntimeError("provider echoed a credential; sample rejected")
            cost = usage_summary([record])["estimated_usd_peak"]
            return content, cost or 0.0
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            safe_error = str(exc).replace(self._api_key, "[REDACTED]")
            raise RuntimeError(safe_error) from None
        finally:
            record["elapsed_seconds"] = time.monotonic() - start
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            # No headers are logged; redact defensively if a server echoes a key.
            serialized = json.dumps(record, ensure_ascii=False).replace(
                self._api_key, "[REDACTED]"
            )
            self.calls.append(json.loads(serialized))
            with self.log_path.open("a") as stream:
                stream.write(serialized + "\n")


def usage_summary(calls: list[dict]) -> dict:
    keys = (
        "prompt_tokens",
        "completion_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    )
    valid = [
        c["usage"]
        for c in calls
        if isinstance(c.get("usage"), dict)
        and all(isinstance(c["usage"].get(k), int) for k in keys)
    ]
    totals = {k: sum(u[k] for u in valid) for k in keys}
    missing = len(calls) - len(valid)
    supported_pricing = all(
        c.get("request_body", {}).get("model") == "deepseek-flash" for c in calls
    )
    can_price = not missing and supported_pricing
    peak = (
        (
            (
                totals["prompt_cache_hit_tokens"] * FLASH_PRICING["cache_hit"]
                + totals["prompt_cache_miss_tokens"] * FLASH_PRICING["cache_miss"]
                + totals["completion_tokens"] * FLASH_PRICING["output"]
            )
            / 1e6
        )
        if can_price
        else None
    )
    normalized = (
        (
            (
                totals["prompt_tokens"] * FLASH_PRICING["cache_miss"]
                + totals["completion_tokens"] * FLASH_PRICING["output"]
            )
            / 1e6
        )
        if can_price
        else None
    )
    return {
        **totals,
        "api_calls": len(calls),
        "missing_usage_calls": missing,
        "usage_totals_complete": not missing,
        "estimated_usd_peak": peak,
        "estimated_usd_off_peak": peak / 2 if peak is not None else None,
        "normalized_no_cache_usd_peak": normalized,
        "pricing_reference": PRICING_REFERENCE,
        "price_is_invoice": False,
    }
