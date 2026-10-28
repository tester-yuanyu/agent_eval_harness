# ruff: noqa: E501
# Keep subprocess integration programs readable.
"""The contracts and Builder must work with runtime packages unavailable."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_contracts_and_builder_validate_without_evaluator_or_agent(tmp_path):
    script = '''
import importlib.abc
import json
import sys
from pathlib import Path

class NoRuntimes(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'eval_framework', 'minimal_agent', 'inspect_ai'}:
            raise ImportError(f'forbidden runtime dependency: {fullname}')

sys.meta_path.insert(0, NoRuntimes())
root, workspace = map(Path, sys.argv[1:])
sys.path[:0] = [str(root / 'packages/contracts/src'), str(root / 'packages/dataset-builder/src')]
from eval_contracts import load_dataset, validate_dataset
from capability_snapshot_kit import validate_capability_bundle_v3
from dataset_builder.generation_client import ScriptedGenerationClient
from dataset_builder.pipeline import prepare_generation, generate_candidates, compile_candidates, validate_draft
from dataset_builder.suite_definition import load_suite
suite = load_suite('mini_agent_intent_v2')
result = validate_capability_bundle_v3(suite.capability_bundle_path)
assert result.capability_bundle_sha256 == suite.config.capability_input.bundle_hash
request = prepare_generation(suite, workspace)
raw = generate_candidates(request, ScriptedGenerationClient(json.loads(suite.seed_catalog_path.read_text())), workspace)
compile_candidates(suite, raw, workspace)
report = validate_draft(suite, workspace / 'draft.jsonl')
assert report.valid, report.model_dump()
rows = [json.loads(line) for line in (workspace / 'draft.jsonl').read_text().splitlines()]
rows[0]['oracle']['evaluation']['checks'][0]['name'] = 'confirmation_accepted'
(workspace / 'draft.jsonl').write_text(''.join(json.dumps(row) + '\\n' for row in rows))
report = validate_draft(suite, workspace / 'draft.jsonl')
assert not report.valid
assert any('required evidence' in issue for gate in report.gates if gate.name == 'evaluator' for issue in gate.issues)
'''
    process = subprocess.run(
        [sys.executable, '-I', '-c', script, str(ROOT), str(tmp_path / 'work')],
        text=True, capture_output=True, cwd=tmp_path,
    )
    assert process.returncode == 0, process.stdout + process.stderr
