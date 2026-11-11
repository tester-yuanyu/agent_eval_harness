"""只从同一原始执行与评分配置复用已保存的Judge项。"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .runner import digest


def load_judge_seeds(
    directory: Path, source: dict, source_hash: str, config: dict, repeats: int
) -> tuple[dict, dict]:
    directory = Path(directory)
    path = directory / "results.json"
    if not path.exists():
        path = directory / "judge-run.json"
    raw = path.read_bytes()
    saved = json.loads(raw)
    identity = saved["identity"]
    if digest(identity) != saved["identity_hash"]:
        raise ValueError("Judge recovery identity Hash mismatch")
    if (
        identity.get("source_results_sha256") != source_hash
        or identity.get("judge_config") != config
        or identity.get("judge_repeats") != repeats
    ):
        raise ValueError("Judge recovery requires identical source/config/repeats")
    originals = {(r["case_id"], r["trial"]): r for r in source["trials"]}
    result = {}
    if "trials" in saved:
        for row in saved["trials"]:
            key = row["case_id"], row["trial"]
            if (
                key not in originals
                or row.get("source_trial_sha256") != digest(originals[key])
                or row.get("source_assessment") != originals[key]["assessment"]
            ):
                raise ValueError("Judge recovery execution binding mismatch")
            for repeat in range(1, repeats + 1):
                result[(*key, repeat)] = [
                    copy.deepcopy(m)
                    for m in row["assessment"]["metrics"]
                    if m.get("judge_repeat") == repeat
                ]
    else:
        by_hash = {digest(r): k for k, r in originals.items()}
        for journal in (directory / "judgments").glob("*.json"):
            value = json.loads(journal.read_text())
            if (
                value.get("identity_hash") != saved["identity_hash"]
                or value.get("source_trial_sha256") not in by_hash
            ):
                raise ValueError("Judge recovery journal binding mismatch")
            repeat = value["judge_repeat"]
            if type(repeat) is not int or not 1 <= repeat <= repeats:
                raise ValueError("Invalid Judge repeat")
            result[(*by_hash[value["source_trial_sha256"]], repeat)] = value["metrics"]
    return result, {
        "source": str(path.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "identity_hash": saved["identity_hash"],
        "checkpoint_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((directory / "metric-checkpoints").glob("*.json"))
        },
    }
