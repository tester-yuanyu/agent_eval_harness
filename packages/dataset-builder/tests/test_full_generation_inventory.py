import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT.parent / "mini_agent/exports/full_tools_fixture_v1"
HASH = "215a9a3a445c8857f3bdd8dbecba935ce646bd8c784f16ecfc4a5da6042cce3c"


def load(root=DELIVERY):
    from dataset_builder.full_generation.inventory import load_inventory

    return load_inventory(root / "bundle", root, HASH)


def test_full_inventory_has_23_targets():
    inv = load()
    from collections import Counter

    assert Counter(t["snapshot_type"] for t in inv.targets) == {
        "module": 7,
        "intent": 7,
        "tool": 6,
        "chain": 3,
    }
    assert inv.bundle_sha256 == HASH


@pytest.mark.parametrize(
    "relative", ["bundle/tools/query_user_info.json", "capability_contract_gaps.json"]
)
def test_tampered_inputs_rejected(tmp_path, relative):
    root = tmp_path / "delivery"
    shutil.copytree(DELIVERY, root)
    p = root / relative
    data = json.loads(p.read_text())
    data["unexpected_change"] = True
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load(root)


def test_missing_source_pointer_rejected():
    from dataset_builder.full_generation.inventory import source_ref

    with pytest.raises(ValueError):
        source_ref(load(), "tool.query_user_info", "/not_present")
