"""Explicit Git source resolution uses a local repository, never a network service."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class SourceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "suite"
        self.root.mkdir()
        self.origin = Path(self.tmp.name) / "origin"
        self.origin.mkdir()
        self.git("init", "-q")
        (self.origin / "agent.py").write_text("print('original')\n")
        self.git("add", "agent.py")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "initial",
        )
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.origin, capture_output=True, text=True, check=True
        )

    def cli(self, *args):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "agent_eval_suite",
                "--root",
                str(self.root),
                "agent",
                *args,
            ],
            env=dict(os.environ, PYTHONPATH=str(REPO / "src")),
            capture_output=True,
            text=True,
            check=False,
        )

    def sync(self, ref=None):
        return self.cli(
            "sync",
            "--name",
            "external",
            "--repository",
            str(self.origin),
            "--ref",
            ref or self.commit,
        )

    def test_sync_records_commit_and_resolve_never_fetches(self):
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["commit"], self.commit)
        checkout = Path(record["resolved_path"])
        self.assertEqual(
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=checkout,
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip(),
            self.commit,
        )
        self.origin.rename(self.origin.with_name("unavailable"))
        resolved = self.cli("resolve", "--name", "external", "--commit", self.commit)
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertEqual(json.loads(resolved.stdout)["commit"], self.commit)

    def test_mutable_ref_is_resolved_once_and_not_used_as_identity(self):
        initial = self.sync("HEAD")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        (self.origin / "agent.py").write_text("print('changed')\n")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qam",
            "change",
        )
        resolved = self.cli("resolve", "--name", "external", "--commit", self.commit)
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        self.assertEqual(json.loads(resolved.stdout)["commit"], self.commit)
        self.assertNotEqual(
            self.cli("resolve", "--name", "external", "--commit", "HEAD").returncode, 0
        )
        newer = self.sync("HEAD")
        self.assertEqual(newer.returncode, 0, newer.stderr)
        self.assertNotEqual(json.loads(newer.stdout)["commit"], self.commit)

    def test_dirty_checkout_cannot_claim_pinned_identity(self):
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = Path(json.loads(result.stdout)["resolved_path"])
        (checkout / "agent.py").write_text("print('tampered')\n")
        resolved = self.cli("resolve", "--name", "external", "--commit", self.commit)
        self.assertNotEqual(resolved.returncode, 0)
        self.assertIn("modified", resolved.stderr)

    def assert_index_flag_cannot_hide_modified_source(self, flag):
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = Path(json.loads(result.stdout)["resolved_path"])
        subprocess.run(
            ["git", "update-index", flag, "agent.py"], cwd=checkout, check=True
        )
        source = checkout / "agent.py"
        original_stat = source.stat()
        source.write_text("print('tampered')\n")  # Same size as the original.
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(status.stdout, "")
        resolved = self.cli("resolve", "--name", "external", "--commit", self.commit)
        self.assertNotEqual(resolved.returncode, 0)
        self.assertIn("modified", resolved.stderr)

    def test_assume_unchanged_cannot_hide_modified_source(self):
        self.assert_index_flag_cannot_hide_modified_source("--assume-unchanged")

    def test_skip_worktree_cannot_hide_modified_source(self):
        self.assert_index_flag_cannot_hide_modified_source("--skip-worktree")

    def test_executable_mode_checked_even_when_git_ignores_filemode(self):
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = Path(json.loads(result.stdout)["resolved_path"])
        subprocess.run(
            ["git", "config", "core.filemode", "false"], cwd=checkout, check=True
        )
        source = checkout / "agent.py"
        source.chmod(source.stat().st_mode | 0o100)
        resolved = self.cli("resolve", "--name", "external", "--commit", self.commit)
        self.assertNotEqual(resolved.returncode, 0)
        self.assertIn("modified", resolved.stderr)

    def test_unmodified_files_with_index_flags_remain_valid(self):
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = Path(json.loads(result.stdout)["resolved_path"])
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag):
                subprocess.run(
                    ["git", "update-index", flag, "agent.py"], cwd=checkout, check=True
                )
                resolved = self.cli(
                    "resolve", "--name", "external", "--commit", self.commit
                )
                self.assertEqual(resolved.returncode, 0, resolved.stderr)

    def commit_origin_changes(self):
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "test tracked sources",
        )
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()

    def test_symlink_target_bytes_verified_without_following_link(self):
        (self.origin / "alias").symlink_to("agent.py")
        self.commit_origin_changes()
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = Path(json.loads(result.stdout)["resolved_path"])
        subprocess.run(
            ["git", "update-index", "--assume-unchanged", "alias"],
            cwd=checkout,
            check=True,
        )
        (checkout / "alias").unlink()
        (checkout / "alias").symlink_to("elsewhere")
        resolved = self.cli("resolve", "--name", "external", "--commit", self.commit)
        self.assertNotEqual(resolved.returncode, 0)
        self.assertIn("modified", resolved.stderr)

    def test_binary_files_with_unusual_names_are_verified(self):
        name = "worker\tname\n.py"
        (self.origin / name).write_bytes(b"\x00\xff")
        self.commit_origin_changes()
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = Path(json.loads(result.stdout)["resolved_path"])
        subprocess.run(
            ["git", "update-index", "--skip-worktree", name], cwd=checkout, check=True
        )
        (checkout / name).write_bytes(b"\x00\xfe")
        resolved = self.cli("resolve", "--name", "external", "--commit", self.commit)
        self.assertNotEqual(resolved.returncode, 0)
        self.assertIn("modified", resolved.stderr)

    def test_gitlink_is_not_fetched_and_populated_submodule_is_not_claimed_verified(
        self,
    ):
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.commit},module")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "add gitlink",
        )
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = Path(json.loads(result.stdout)["resolved_path"])
        module = checkout / "module"
        self.assertFalse((module / ".git").exists())
        module.mkdir(exist_ok=True)
        (module / "unverified.py").write_text("print('external code')\n")
        resolved = self.cli("resolve", "--name", "external", "--commit", self.commit)
        self.assertNotEqual(resolved.returncode, 0)
        self.assertIn("populated submodules", resolved.stderr)

    def test_path_traversal_rejected_before_sync(self):
        result = self.cli(
            "sync",
            "--name",
            "../escape",
            "--repository",
            str(self.origin),
            "--ref",
            self.commit,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "escape").exists())


if __name__ == "__main__":
    unittest.main()
