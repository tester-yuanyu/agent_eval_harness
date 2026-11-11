"""Offline Inspect crash-log recovery. Recovered evidence never implies PASS."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def recover_interrupted_log(
    log: str | Path, *, output: str | Path | None = None
) -> dict:
    """Preserve the original and buffer; export native events as partial evidence.

    Inspect owns recovery and cancellation classification. This function does not
    resume Agent execution, invoke a model, score samples, or merge official runs.
    Even a flushed successful sample requires the normal evidence/scoring boundary
    before it can be used as an assessment.
    """
    from inspect_ai.log import recover_eval_log

    source = Path(log).resolve(strict=True)
    target = (
        Path(output).resolve()
        if output is not None
        else source.with_name(source.stem + "-recovered.eval")
    )
    if target == source or target.exists():
        raise ValueError("recovery output must be new and distinct from the source")
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    recovered = recover_eval_log(
        str(source),
        output=str(target),
        overwrite=False,
        cleanup=False,
        no_events=False,
        incomplete_action="retry",
    )
    return {
        "schema_version": "inspect-partial-recovery-v1",
        "source_log": str(source),
        "source_sha256": original_sha,
        "recovered_log": str(target),
        "recovered_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "status": "error",
        "evidence_complete": False,
        "native_status": recovered.status,
        "samples": [
            {
                "id": sample.id,
                "epoch": sample.epoch,
                "status": "error",
                "evidence_complete": False,
                "native_events": [
                    event.model_dump(mode="json") for event in sample.events
                ],
                "native_error": sample.error.model_dump(mode="json")
                if sample.error
                else None,
                "errors": [
                    {
                        "code": "RECOVERED_EVIDENCE_REQUIRES_VALIDATION",
                        "message": (
                            "Recovered logs do not establish completed Agent "
                            "evidence or a passing assessment."
                        ),
                    }
                ],
            }
            for sample in recovered.samples or []
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="离线恢复 Inspect 崩溃日志（不执行、不评分）"
    )
    parser.add_argument("log", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    print(
        json.dumps(
            recover_interrupted_log(args.log, output=args.output),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
