"""另一 Agent 在禁止导入 MiniAgent 时使用同一套通用能力。"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_independent_customer_agent_exports_without_mini_agent(tmp_path):
    root = Path(__file__).resolve().parents[3]
    target = tmp_path / "examples/customer_service"
    target.mkdir(parents=True)
    (target.parent / "__init__.py").write_text("")
    (target / "__init__.py").write_text("")
    for name in ("agent.py", "collector.py"):
        shutil.copyfile(
            root / "examples/mini_agent/examples/customer_service" / name, target / name
        )
    program = """
import importlib.abc,json,sys
from pathlib import Path
class NoMini(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,*args):
        if fullname == 'minimal_agent' or fullname.startswith('minimal_agent.'):
            raise AssertionError('shared framework attempted to import MiniAgent')
sys.meta_path.insert(0,NoMini())
from capability_snapshot_kit.ingestion.cli import main
assert main(['export','--collector','examples.customer_service.collector:create',
             '--source-root',str(Path.cwd()),'--profile','conversation','--output','delivery']) == 0
from capability_snapshot_kit.validation import validate_capability_bundle_v3
assert validate_capability_bundle_v3(Path('delivery/bundle')).valid
assert not any(name=='minimal_agent' or name.startswith('minimal_agent.') for name in sys.modules)
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    run = subprocess.run(
        [sys.executable, "-c", program],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    agent = json.loads((tmp_path / "delivery/bundle/agent.json").read_text())
    assert agent["agent_id"] == "customer_service_demo"
    manifest = json.loads((tmp_path / "delivery/manifest.json").read_text())
    assert "source_audit.json" in manifest["files_sha256"]
