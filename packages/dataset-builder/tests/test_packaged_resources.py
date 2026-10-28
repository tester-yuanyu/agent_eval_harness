# ruff: noqa: E501
# Keep subprocess integration programs readable.
"""An installed Builder keeps its trusted schemas and suite catalogue."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_built_distribution_contains_trusted_resources(tmp_path):
    built = tmp_path / 'lib'
    process = subprocess.run(
        [sys.executable, 'setup.py', 'build_py', '--build-lib', str(built)],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    script = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from dataset_builder.suite_definition import ROOT, discover_suite_configs
from dataset_builder.capability_profiles import load_trusted_profile
assert ROOT.is_relative_to(Path(sys.argv[1]))
assert 'mini_agent_intent_v2' in discover_suite_configs()
profile = load_trusted_profile('capability-snapshot', '3.0', ROOT / 'protocol_profiles/trust_store.json')
assert profile.profile.protocol_version == '3.0'
assert (ROOT / 'schemas/policies/source_policy.schema.json').is_file()
'''
    process = subprocess.run(
        [sys.executable, '-I', '-c', script, str(built)],
        cwd=tmp_path, text=True, capture_output=True,
        env={key: value for key, value in os.environ.items() if key != 'PYTHONPATH'},
    )
    assert process.returncode == 0, process.stdout + process.stderr
