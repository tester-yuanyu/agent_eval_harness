"""可选阶段计时旁路；未知阶段不补零，并发阶段累计耗时不能相加当墙钟。"""

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .runner import now, save_json

_LOCK = threading.Lock()


@contextmanager
def timed_phase(directory: Path, phase: str, **labels):
    started, clock = now(), time.monotonic()
    status = "complete"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        path = Path(directory) / "phase-timings.json"
        event = {
            "phase": phase,
            "started_at": started,
            "seconds": time.monotonic() - clock,
            "status": status,
            **labels,
        }
        with _LOCK:
            value = (
                json.loads(path.read_text())
                if path.exists()
                else {
                    "version": "phase-timings-v1",
                    "events": [],
                    "note": (
                        "并发阶段可能重叠；未采集阶段为未知，"
                        "不能将累计耗时相加作为墙钟。"
                    ),
                }
            )
            value["events"].append(event)
            save_json(path, value)
