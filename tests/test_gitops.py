from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from oasis_harness.common import HarnessError, git, read_json, run, write_json
from oasis_harness import gitops, installation


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oasis-git-")
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "space ' 한글 中文 😀"
        self.root.mkdir()
        run(["git", "init", "--initial-branch=main", str(self.root)])
        git(self.root, "config", "user.name", "Oasis Fixture")
        git(self.root, "config", "user.email", "fixture@oasis.invalid")
        git(self.root, "config", "core.autocrlf", "false")
        (self.root / ".gitignore").write_text("/.oasis/local/\nignored.bin\n", encoding="utf-8")
        (self.root / "data.txt").write_text("baseline\n", encoding="utf-8")
        write_json(self.root / ".oasis/project.json", {"git": {"profile": "single-main"}})
        git(self.root, "add", ".gitignore", "data.txt", ".oasis/project.json")
        git(self.root, "commit", "-m", "baseline")
        self.baseline = gitops.head(self.root)

    def tearDown(self):
        self.assertTrue(self.base.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertTrue(self.base.name.startswith("oasis-git-"))
        self.temporary.cleanup()

    def activate(self, profile="single-main"):
        if gitops.desired_profile(self.root) != profile:
            self.baseline = self.select_profile(profile)
        return gitops.activate(self.root, profile, gitops.head(self.root))

    def select_profile(self, profile):
        write_json(self.root / ".oasis/project.json", {"git": {"profile": profile}})
        git(self.root, "add", ".oasis/project.json")
        git(self.root, "commit", "-m", "Select " + profile)
        return gitops.head(self.root)

    def commit(self, text="changed"):
        (self.root / "data.txt").write_text(text + "\n", encoding="utf-8")
        git(self.root, "add", "data.txt")
        git(self.root, "commit", "-m", text)
        return gitops.head(self.root)


class GitProfileTests(GitFixture):
    def test_harness_only_initialization_preserves_foreign_index_and_files(self):
        target = self.base / "unborn"
        target.mkdir()
        package = self.base / "tiny package"
        for name in ("seed", "library", "oasis_harness", "docs"):
            (package / name).mkdir(parents=True)
        (package / "seed/.gitignore").write_text("/.oasis/local/\n", encoding="utf-8")
        (package / "oasis_harness/__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
        installation.apply(installation.plan(target, package), state_root=self.base / "install journals")
        run(["git", "init", "--initial-branch=main", str(target)])
        git(target, "config", "user.name", "Oasis Fixture")
        git(target, "config", "user.email", "fixture@oasis.invalid")
        (target / "private-note.txt").write_bytes(b"private user bytes")
        git(target, "add", "private-note.txt")
        index = (target / ".git/index").read_bytes()
        with self.assertRaisesRegex(HarnessError, "Foreign staged"):
            gitops.initialize(target)
        self.assertEqual((target / ".git/index").read_bytes(), index)
        git(target, "rm", "--cached", "private-note.txt")
        result = gitops.initialize(target)
        self.assertEqual(result["state"], "committed")
        self.assertNotIn("private-note.txt", git(target, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
        self.assertEqual((target / "private-note.txt").read_bytes(), b"private user bytes")
        with self.assertRaisesRegex(HarnessError, "already has history"):
            gitops.initialize(target)

    def test_real_hooks_commit_profile_transition_and_retained_test(self):
        self.activate()
        self.commit()
        new = self.select_profile("main-test")
        gitops.transition(self.root, "main-test", new)
        self.assertEqual(git(self.root, "rev-parse", "test"), new)
        git(self.root, "switch", "test")
        self.select_profile("single-main")
        feature = self.commit("feature")
        git(self.root, "switch", "main")
        with self.assertRaisesRegex(HarnessError, "Divergent"):
            gitops.transition(self.root, "main-test", new, feature)
        self.assertEqual(gitops.head(self.root), new)
        # Real fast-forward integration, then downgrade retains the old test ref.
        git(self.root, "merge", "--ff-only", "test")
        gitops.transition(self.root, "single-main", feature, feature)
        with self.assertRaises(HarnessError):
            git(self.root, "update-ref", "-d", "refs/heads/test", feature)
        self.assertEqual(git(self.root, "rev-parse", "test"), feature)

    def test_dirty_staged_ignored_and_remote_are_preserved(self):
        (self.root / "untracked.txt").write_bytes(b"owned by peer")
        (self.root / "ignored.bin").write_bytes(b"keep ignored")
        (self.root / "data.txt").write_bytes(b"staged peer")
        git(self.root, "add", "data.txt")
        index = (self.root / ".git/index").read_bytes()
        with self.assertRaises(HarnessError):
            self.activate()
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        self.assertEqual((self.root / "ignored.bin").read_bytes(), b"keep ignored")
        git(self.root, "remote", "add", "existing", "https://example.invalid/source.git")
        with self.assertRaisesRegex(HarnessError, "no remotes"):
            self.activate()
        self.assertEqual(git(self.root, "remote"), "existing")

    def test_old_worktree_uses_canonical_engine_and_cannot_write(self):
        git(self.root, "branch", "legacy")
        linked = self.base / "old worktree"
        git(self.root, "worktree", "add", str(linked), "legacy")
        self.activate()
        (linked / "peer.txt").write_bytes(b"peer owned")
        git(linked, "add", "peer.txt")
        result = run(["git", "-C", str(linked), "commit", "-m", "forbidden"], check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(gitops.head(linked), self.baseline)
        self.assertEqual((linked / "peer.txt").read_bytes(), b"peer owned")
        with self.assertRaises(HarnessError):
            git(self.root, "branch", "-D", "legacy")

    def test_copy_inactive_engine_tamper_and_nonff_denied(self):
        self.activate()
        new = self.commit()
        with self.assertRaises(HarnessError):
            git(self.root, "update-ref", "refs/heads/main", self.baseline, new)
        copy = self.base / "copied"
        shutil.copytree(self.root, copy)
        self.assertFalse(gitops.status(copy)["active"])
        gitops.activate(copy, "single-main", new, rebind=True)
        self.assertTrue(gitops.status(copy)["active"])
        binding = read_json(gitops.state_dir(self.root) / "binding.json")
        (Path(binding["engine"]) / "oasis_harness/gitops.py").write_text("# changed\n", encoding="utf-8")
        self.assertFalse(gitops.status(self.root)["active"])
        self.assertTrue(gitops.status(copy)["active"])

    def test_tags_immutable_upstream_and_push_denied(self):
        self.activate("main-test")
        git(self.root, "tag", "source-v1")
        run(["git", "-C", str(self.root), "tag", "-d", "source-v1"], check=False)
        self.assertEqual(git(self.root, "rev-parse", "source-v1"), self.baseline)
        git(self.root, "config", "branch.test.remote", ".")
        git(self.root, "config", "branch.test.merge", "refs/heads/main")
        self.assertFalse(gitops.status(self.root)["active"])
        git(self.root, "config", "--unset", "branch.test.remote")
        git(self.root, "config", "--unset", "branch.test.merge")
        remote = self.base / "remote.git"
        run(["git", "init", "--bare", str(remote)])
        with self.assertRaises(HarnessError):
            git(self.root, "push", str(remote), "main")

    def test_desired_profile_and_interrupted_activation_transition(self):
        with self.assertRaisesRegex(HarnessError, "Commit the requested"):
            gitops.activate(self.root, "main-test", self.baseline)
        real_write = gitops.write_json
        def interrupt_binding(path, value):
            real_write(path, value)
            if Path(path).name == "binding.json":
                raise HarnessError("fixture interruption after binding")
        with mock.patch.object(gitops, "write_json", side_effect=interrupt_binding):
            with self.assertRaisesRegex(HarnessError, "fixture interruption"):
                self.activate()
        self.assertFalse(gitops.status(self.root)["active"])
        gitops.recover(self.root, self.baseline)
        self.assertTrue(gitops.status(self.root)["active"])
        selected = self.select_profile("main-test")
        self.assertFalse(gitops.status(self.root)["profile_matches_desired"])
        with mock.patch.object(gitops, "write_json", side_effect=interrupt_binding):
            with self.assertRaisesRegex(HarnessError, "fixture interruption"):
                gitops.transition(self.root, "main-test", selected)
        self.assertFalse(gitops.status(self.root)["active"])
        gitops.recover(self.root, selected)
        self.assertTrue(gitops.status(self.root)["profile_matches_desired"])
        self.assertTrue(gitops.status(self.root)["active"])

    def test_real_post_commit_backup_failure_preserves_source_commit(self):
        self.activate()
        write_json(gitops.state_dir(self.root) / "backup.json", {
            "schema_version": 1, "automatic_enabled": True,
            "primary": str(self.base / "former location"),
            "common_dir": str(gitops.common_dir(self.root))})
        (self.root / "data.txt").write_bytes(b"new committed work\n")
        git(self.root, "add", "data.txt")
        result = run(["git", "-C", str(self.root), "commit", "-m", "preserve successful source commit"], check=False)
        self.assertEqual(result.returncode, 0)
        self.assertNotEqual(gitops.head(self.root), self.baseline)
        self.assertIn("source commit remains intact", result.stderr)
        self.assertEqual(git(self.root, "show", "HEAD:data.txt"), "new committed work")


if __name__ == "__main__":
    unittest.main()
