"""Check the imported frozen/reference assets against the migration baseline."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    manifest = json.loads((ROOT / "docs/migration/frozen-assets.json").read_text())
    fixtures = json.loads(
        (ROOT / "docs/migration/builder-fixture-provenance.json").read_text()
    )
    entries = manifest["files"] + [
        {"path": item["destination"], "sha256": item["sha256"]} for item in fixtures
    ]
    failed = []
    for entry in entries:
        path = ROOT / entry["path"]
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
        ):
            failed.append(entry["path"])
    if failed:
        print("Changed or missing reference artifacts:\n" + "\n".join(failed))
        return 1
    print(f"Verified {len(entries)} imported reference artifacts and test fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
