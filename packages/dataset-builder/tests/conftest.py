from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset_builder.generation_client import ScriptedGenerationClient
from dataset_builder.pipeline import (
    compile_candidates,
    generate_candidates,
    prepare_generation,
)
from dataset_builder.suite_definition import load_suite


@pytest.fixture
def suite():
    return load_suite("mini_agent_intent_v1")


@pytest.fixture
def seed(suite):
    return json.loads((suite.suite_dir / "seed_catalog.json").read_text())


@pytest.fixture
def authored(tmp_path: Path, suite, seed):
    workspace = tmp_path / "run"
    request = prepare_generation(suite, workspace)
    raw = generate_candidates(request, ScriptedGenerationClient(seed), workspace)
    cases = compile_candidates(suite, raw, workspace)
    return workspace, request, raw, cases
