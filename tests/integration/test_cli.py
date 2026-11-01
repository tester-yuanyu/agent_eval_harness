"""Root dispatcher and publication boundaries; fake runtime only observes argv."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "runtime"
        self.runtime.write_text(
            f"#!{sys.executable}\n"
            "import json,sys\n"
            "print(json.dumps({'argv':sys.argv[1:], 'valid':True, "
            "'capability_bundle_sha256':'" + "a" * 64 + "', "
            "'agent_snapshot_sha256':'" + "b" * 64 + "'}))\n"
        )
        self.runtime.chmod(0o755)

    def cli(self, *args, runtime=True):
        env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
        env.pop("OPENAI_API_KEY", None)
        command = [sys.executable, "-m", "agent_eval_suite", "--root", str(self.root)]
        if runtime:
            command += [
                "--builder-python",
                str(self.runtime),
                "--evaluator-python",
                str(self.runtime),
            ]
        return subprocess.run(
            command + list(args), env=env, text=True, capture_output=True, check=False
        )

    def bundle(self):
        source = self.root / "input"
        source.mkdir(exist_ok=True)
        (source / "agent.json").write_text(
            json.dumps({"agent_id": "test-agent", "agent_version": "1.0.0"})
        )
        return source

    def publish(self, source=None, agent="test-agent", version="1.0.0"):
        return self.cli(
            "bundle",
            "publish",
            "--agent",
            agent,
            "--version",
            version,
            "--input",
            str(source or self.bundle()),
        )

    def test_help_needs_no_environment_or_credentials(self):
        result = self.cli("--help", runtime=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dataset", result.stdout)
        self.assertIn("bundle", result.stdout)

    def test_missing_environment_is_actionable(self):
        result = self.cli("eval", "run", "--output-dir", "out", runtime=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("make setup", result.stderr)

    def test_run_forwards_all_arguments_unchanged(self):
        result = self.cli(
            "eval",
            "run",
            "--dataset",
            "frozen.jsonl",
            "--capability-bundle",
            "reference-bundle",
            "--output-dir",
            "out",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["argv"],
            [
                "-m",
                "eval_framework.cli",
                "run",
                "--dataset",
                "frozen.jsonl",
                "--capability-bundle",
                "reference-bundle",
                "--output-dir",
                "out",
            ],
        )

    def test_benchmark_analysis_commands_keep_the_runtime_boundary(self):
        for command, flags in (
            ("judge", ["--source", "saved", "--config", "judge.json"]),
            ("calibration-sheet", ["--run", "saved"]),
            ("calibration-page", ["--worksheet", "labels.json"]),
            ("calibration-check", ["--labels", "labels.json"]),
            ("quality-audit", ["--run", "saved"]),
            ("export-langfuse-evidence", ["--run", "saved"]),
            ("report", ["--run", "saved", "--format", "inspect"]),
            ("compare", ["--baseline", "a", "--candidate", "b", "--view-dir", "v"]),
        ):
            with self.subTest(command=command):
                result = self.cli("benchmark", command, *flags)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout)["argv"],
                    ["-m", "eval_framework.benchmark.cli", command, *flags],
                )

    def test_baseline_run_is_explicit_compare_alias(self):
        result = self.cli(
            "eval",
            "compare",
            "--baseline-run",
            "runs/base",
            "--candidate",
            "runs/new",
            "--output-dir",
            "diff",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["argv"][3:5], ["--baseline", "runs/base"]
        )

    def test_duplicate_baseline_options_rejected(self):
        result = self.cli("eval", "compare", "--baseline-run", "a", "--baseline", "b")
        self.assertNotEqual(result.returncode, 0)

    def test_ingest_forwards_offline_response_compilation(self):
        result = self.cli(
            "dataset",
            "ingest",
            "--request",
            "request.json",
            "--response",
            "response.json",
            "--workspace",
            "draft",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["argv"][:3],
            ["-m", "dataset_builder.cli", "ingest"],
        )

    def test_freeze_preserves_human_review_arguments(self):
        result = self.cli(
            "dataset",
            "freeze",
            "--suite",
            "s",
            "--draft",
            "draft.json",
            "--reviewer",
            "actual-human",
            "--review-file",
            "approved.json",
            "--output",
            "frozen.jsonl",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("actual-human", json.loads(result.stdout)["argv"])
        self.assertIn("approved.json", json.loads(result.stdout)["argv"])

    def test_publish_copies_exact_bytes_and_resolves_pinned_identity(self):
        source = self.bundle()
        original = (source / "agent.json").read_bytes()
        result = self.publish(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        dest = self.root / "data/bundles/test-agent/1.0.0"
        self.assertEqual((dest / "agent.json").read_bytes(), original)
        self.assertEqual(list(dest.iterdir()), [dest / "agent.json"])
        resolved = self.cli(
            "bundle", "resolve", "--agent", "test-agent", "--version", "1.0.0"
        )
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        data = json.loads(resolved.stdout)
        self.assertEqual(data["capability_bundle_sha256"], "a" * 64)
        self.assertEqual(data["agent_snapshot_sha256"], "b" * 64)

    def test_version_overwrite_rejected_even_if_content_identical(self):
        self.assertEqual(self.publish().returncode, 0)
        again = self.publish()
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already", again.stderr)

    def test_versions_and_agent_ids_cannot_escape_or_be_mutable(self):
        for value in ("../escape", "/absolute", "a/b", "..", "latest", "current"):
            with self.subTest(value=value):
                self.assertNotEqual(self.publish(version=value).returncode, 0)
        self.assertNotEqual(self.publish(agent="../escape").returncode, 0)
        self.assertFalse((self.root / "escape").exists())

    def test_agent_id_must_match_validated_document(self):
        self.assertNotEqual(self.publish(agent="other-agent").returncode, 0)

    def test_published_byte_tampering_rejected(self):
        self.assertEqual(self.publish().returncode, 0)
        (self.root / "data/bundles/test-agent/1.0.0/agent.json").write_text("{}")
        result = self.cli(
            "bundle", "resolve", "--agent", "test-agent", "--version", "1.0.0"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tamper", result.stderr.lower())

    def test_index_path_tampering_rejected(self):
        self.assertEqual(self.publish().returncode, 0)
        index = self.root / "data/bundle-index.json"
        payload = json.loads(index.read_text())
        payload["bundles"]["test-agent"]["1.0.0"]["path"] = "../input"
        index.write_text(json.dumps(payload))
        result = self.cli(
            "bundle", "resolve", "--agent", "test-agent", "--version", "1.0.0"
        )
        self.assertNotEqual(result.returncode, 0)

    def test_changed_index_hash_is_rejected(self):
        self.assertEqual(self.publish().returncode, 0)
        index = self.root / "data/bundle-index.json"
        payload = json.loads(index.read_text())
        payload["bundles"]["test-agent"]["1.0.0"]["agent_snapshot_sha256"] = "c" * 64
        index.write_text(json.dumps(payload))
        result = self.cli(
            "bundle", "resolve", "--agent", "test-agent", "--version", "1.0.0"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("agent_snapshot_sha256 mismatch", result.stderr)

    def test_registry_directory_symlink_rejected(self):
        external = self.root / "outside"
        external.mkdir()
        (self.root / "data").symlink_to(external, target_is_directory=True)
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((external / "bundle-index.json").exists())

    def test_upstream_failure_exit_code_is_preserved(self):
        self.runtime.write_text(f"#!{sys.executable}\nraise SystemExit(7)\n")
        result = self.cli("dataset", "freeze", "--suite", "s")
        self.assertEqual(result.returncode, 7)

    def test_no_fabricated_build_shorthand(self):
        result = self.cli("dataset", "build")
        self.assertNotEqual(result.returncode, 0)

    def test_symlink_in_source_rejected(self):
        source = self.bundle()
        (source / "escape").symlink_to(self.root)
        self.assertNotEqual(self.publish(source).returncode, 0)


if __name__ == "__main__":
    unittest.main()
