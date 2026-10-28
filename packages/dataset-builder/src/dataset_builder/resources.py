"""Locate authoring resources in an editable checkout or installed wheel."""
from importlib.resources import files
from pathlib import Path


def resource_root() -> Path:
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "protocol_profiles/trust_store.json").is_file():
        return checkout
    return Path(str(files("dataset_builder").joinpath("resources")))
