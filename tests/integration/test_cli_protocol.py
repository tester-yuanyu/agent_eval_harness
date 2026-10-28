"""Real canonical protocol subprocess checks in the installed Builder environment."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PYTHON = REPO / ".venvs/builder/bin/python"
FIXTURE = (
    REPO
    / "packages/evaluator/datasets/mini_agent/capability_bundles/99baea74b9a4fbd6c493fb5a3159a8f019769804d94232f0d89aa072ea9af3d8"
)


@unittest.skipUnless(
    PYTHON.is_file(), "make setup installs canonical validator environment"
)
class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fixture = self.root / "fixture"
        shutil.copytree(FIXTURE, self.fixture)
        (self.fixture / "tools").mkdir(exist_ok=True)

    def cli(self, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_eval_suite",
                "--root",
                str(self.root),
                "--builder-python",
                str(PYTHON),
                *args,
            ],
            env=dict(os.environ, PYTHONPATH=str(REPO / "src")),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_real_protocol_publication_and_both_hashes(self):
        result = self.cli(
            "bundle",
            "publish",
            "--input",
            str(self.fixture),
            "--agent",
            "mini_agent",
            "--version",
            "0.1.0",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["capability_bundle_sha256"], FIXTURE.name)
        original = json.loads((FIXTURE / "agent.json").read_text())
        self.assertEqual(record["agent_snapshot_sha256"], original["snapshot_sha256"])
        resolved = self.cli(
            "bundle", "resolve", "--agent", "mini_agent", "--version", "0.1.0"
        )
        self.assertEqual(resolved.returncode, 0, resolved.stderr)

    def test_supplied_schema_cannot_disable_trusted_validation(self):
        source = self.root / "input"
        shutil.copytree(self.fixture, source)
        (source / "schemas/agent.schema.json").write_text("{}")
        result = self.cli(
            "bundle",
            "publish",
            "--input",
            str(source),
            "--agent",
            "mini_agent",
            "--version",
            "0.1.0",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Schema artifact mismatch", result.stderr)
        self.assertFalse((self.root / "data/bundle-index.json").exists())

    def test_agent_payload_tampering_rejected_before_registration(self):
        source = self.root / "input"
        shutil.copytree(self.fixture, source)
        payload = json.loads((source / "agent.json").read_text())
        payload["agent_version"] = "forged"
        (source / "agent.json").write_text(json.dumps(payload))
        result = self.cli(
            "bundle",
            "publish",
            "--input",
            str(source),
            "--agent",
            "mini_agent",
            "--version",
            "0.1.0",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("snapshot_sha256 mismatch", result.stderr)
        self.assertFalse((self.root / "data/bundles/mini_agent/0.1.0").exists())


if __name__ == "__main__":
    unittest.main()
