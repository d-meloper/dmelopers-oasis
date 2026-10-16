import os
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from oasis_harness.common import clean_environment

PACKAGE = Path(__file__).resolve().parents[1]


class CommitVersionTests(unittest.TestCase):
    def test_private_delta_output_preserves_source_and_refuses_overwrite(self):
        (self.root / ".gitignore").write_text("/.oasis/local/\n", encoding="utf-8")
        self.stage_work()
        before = (self.git("rev-parse", "HEAD").stdout, self.git("write-tree").stdout)
        command = ["python", "-B", "-X", "utf8", "tools/bump_commit_version.py", "--delta-draft", "--output", ".oasis/local/draft.json"]
        result = subprocess.run(command, cwd=self.root, env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.root / ".oasis/local/draft.json"
        draft = path.read_bytes()
        self.assertEqual(json.loads(draft)["files"], ["work.txt"])
        self.assertNotEqual(subprocess.run(command, cwd=self.root, env=self.env, capture_output=True).returncode, 0)
        self.assertEqual(path.read_bytes(), draft)
        self.assertEqual(before, (self.git("rev-parse", "HEAD").stdout, self.git("write-tree").stdout))

    def test_delta_draft_preserves_index_version_and_head(self):
        self.stage_work()
        before = (self.git("rev-parse", "HEAD").stdout, self.git("write-tree").stdout, (self.root / "oasis_harness/__init__.py").read_bytes())
        result = subprocess.run(["python", "-B", "-X", "utf8", "tools/bump_commit_version.py", "--delta-draft"], cwd=self.root, env=self.env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        draft = json.loads(result.stdout)
        self.assertEqual((draft["previous"], draft["version"]), ("1.2.3", "1.2.4"))
        self.assertEqual(draft["files"], ["work.txt"])
        self.assertEqual(draft["summary"], [])
        self.assertEqual(before, (self.git("rev-parse", "HEAD").stdout, self.git("write-tree").stdout, (self.root / "oasis_harness/__init__.py").read_bytes()))

    def test_persistent_version_base_is_refused_without_replacement(self):
        self.stage_work()
        self.git("config", "oasis.versionBase", "2.0.0")
        before = self.committed()
        failed = self.git("commit", "-m", "fixture persistent base", check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn(b"command-local", failed.stderr)
        self.assertEqual(self.committed(), before)
        self.assertEqual(self.git("config", "--get", "oasis.versionBase").stdout.strip(), b"2.0.0")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oasis-version-")
        self.root = Path(self.temp.name).resolve() / "source 한글 😀"
        self.root.mkdir()
        self.env = clean_environment({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_COUNT": "0"})
        for directory in ("tools", "oasis_harness", ".githooks", ".oasis"):
            (self.root / directory).mkdir()
        for relative in ("tools/bump_commit_version.py", "oasis_harness/common.py", "oasis_harness/build.py", ".githooks/pre-commit"):
            shutil.copyfile(PACKAGE / relative, self.root / relative)
        os.chmod(self.root / ".githooks/pre-commit", 0o755)
        (self.root / "oasis_harness/__init__.py").write_bytes(b'"""Fixture."""\n__version__ = "1.2.3"\n')
        (self.root / ".oasis/core.json").write_bytes(b'{"core_version":"1.0.0"}\n')
        (self.root / "work.txt").write_bytes(b"base\n")
        self.git("init", "--template=", "--initial-branch=main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("add", ".")
        self.git("commit", "-m", "Fixture base")
        self.git("config", "core.hooksPath", ".githooks")

    def tearDown(self):
        parent = self.root.parent
        self.assertTrue(parent.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertTrue(parent.name.startswith("oasis-version-"))
        self.temp.cleanup()

    def git(self, *arguments, check=True):
        result = subprocess.run(["git", "-C", str(self.root), *arguments], capture_output=True, env=self.env)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return result

    def committed(self):
        return self.git("show", "HEAD:oasis_harness/__init__.py").stdout

    def stage_work(self):
        (self.root / "work.txt").write_bytes(b"changed\n")
        self.git("add", "--", "work.txt")

    def test_real_hook_increments_every_commit_and_leaves_core_untouched(self):
        before = (self.root / ".oasis/core.json").read_bytes()
        self.stage_work()
        self.git("commit", "-m", "First")
        self.assertIn(b'__version__ = "1.2.4"', self.committed())
        self.git("commit", "--allow-empty", "-m", "Version-only commit")
        self.assertIn(b'__version__ = "1.2.5"', self.committed())
        self.assertEqual((self.root / ".oasis/core.json").read_bytes(), before)

    def test_failed_commit_retry_does_not_increment_twice(self):
        blocker = self.root / ".githooks/commit-msg"
        blocker.write_bytes(b"#!/bin/sh\nexit 1\n")
        os.chmod(blocker, 0o755)
        self.stage_work()
        result = self.git("commit", "-m", "Rejected", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'__version__ = "1.2.3"', self.committed())
        self.assertIn(b'__version__ = "1.2.4"', (self.root / "oasis_harness/__init__.py").read_bytes())
        blocker.unlink()
        self.git("commit", "-m", "Retry")
        self.assertIn(b'__version__ = "1.2.4"', self.committed())

    def test_unstaged_edits_in_version_file_are_not_swept_into_commit(self):
        path = self.root / "oasis_harness/__init__.py"
        path.write_bytes(path.read_bytes() + b"# staged note\n")
        self.git("add", "--", "oasis_harness/__init__.py")
        path.write_bytes(path.read_bytes() + b"# unfinished private note\n")
        self.stage_work()
        self.git("commit", "-m", "Scoped")
        self.assertIn(b"staged note", self.committed())
        self.assertNotIn(b"unfinished private note", self.committed())
        self.assertIn(b"unfinished private note", path.read_bytes())
        self.assertIn(b'__version__ = "1.2.4"', path.read_bytes())

    def test_major_minor_need_an_explicit_owner_base(self):
        path = self.root / "oasis_harness/__init__.py"
        path.write_bytes(path.read_bytes().replace(b"1.2.3", b"1.3.0"))
        self.git("add", "--", "oasis_harness/__init__.py")
        before = path.read_bytes()
        self.assertNotEqual(self.git("commit", "-m", "Unselected", check=False).returncode, 0)
        self.assertEqual(path.read_bytes(), before)
        self.git("-c", "oasis.versionBase=1.3.0", "commit", "-m", "Owner-selected minor")
        self.assertIn(b'__version__ = "1.3.1"', self.committed())

    def test_unstaged_conflicting_version_is_preserved(self):
        path = self.root / "oasis_harness/__init__.py"
        path.write_bytes(path.read_bytes().replace(b"1.2.3", b"9.9.9"))
        self.stage_work()
        before = path.read_bytes()
        staged = self.git("show", ":oasis_harness/__init__.py").stdout
        self.assertNotEqual(self.git("commit", "-m", "Conflicting version", check=False).returncode, 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.git("show", ":oasis_harness/__init__.py").stdout, staged)

    def stage_exact_version(self, version="1.0.0"):
        path = self.root / "oasis_harness/__init__.py"
        path.write_bytes(path.read_bytes().replace(b"1.2.3", version.encode("ascii")))
        self.git("add", "--", "oasis_harness/__init__.py")

    def stage_delta(self, version="1.2.4", previous="1.2.3", files=None, *, summary=None, areas=None, source_only=None):
        path = self.root / "docs/upgrade-index.json"
        path.parent.mkdir(exist_ok=True)
        history = json.loads(path.read_text(encoding="utf-8"))["releases"] if path.exists() else []
        entry = {"version":version,"previous":previous,
            "summary":[] if summary is None else summary,"areas":[] if areas is None else areas,
            "source_only":[] if source_only is None else source_only,
            "files":["work.txt"] if files is None else files}
        if history and history[-1]["version"] == version and history[-1]["previous"] == previous:
            history[-1] = entry
        else:
            history.append(entry)
        path.write_text(json.dumps({"schema_version":1,"releases":history}),encoding="utf-8")
        self.git("add", "--", "docs/upgrade-index.json")

    def test_source_maintenance_keeps_only_predecessor_and_scope_metadata(self):
        self.stage_work()
        self.stage_delta()
        self.git("commit", "-m", "Source maintenance")
        history = json.loads(self.git("show", "HEAD:docs/upgrade-index.json").stdout)["releases"]
        self.assertEqual(history[0], {"version":"1.2.4", "previous":"1.2.3",
                                    "summary":[], "areas":[], "source_only":[], "files":["work.txt"]})

    def test_source_notes_cannot_be_published_as_release_summaries(self):
        self.stage_work()
        before = (self.root / "oasis_harness/__init__.py").read_bytes()
        for notes in ({"source_only":["Moved test builds into a local folder"]},
                      {"summary":["Moved test builds into a local folder"]}):
            self.stage_delta(**notes)
            rejected = self.git("commit", "-m", "Source notes in public index", check=False)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn(b"source-only", rejected.stderr)
            self.assertEqual((self.root / "oasis_harness/__init__.py").read_bytes(), before)

    def test_adopter_changes_need_both_summary_and_application_area(self):
        self.stage_work()
        area = {"name":"Guide", "change":"Clarify supported setup",
                "apply":"Review the updated guide", "paths":["work.txt"], "checks":[]}
        self.stage_delta(areas=[area])
        self.assertNotEqual(self.git("commit", "-m", "Missing public summary", check=False).returncode, 0)
        self.stage_delta(summary=["Clarify supported setup"], areas=[area])
        self.git("commit", "-m", "Document supported setup")
        self.assertIn(b'__version__ = "1.2.4"', self.committed())

    def test_version_notes_cover_exact_staged_scope_before_version_writes(self):
        self.stage_work()
        self.stage_delta(files=[])
        before = (self.root / "oasis_harness/__init__.py").read_bytes()
        rejected = self.git("commit", "-m", "Missing file delta", check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(b"exactly cover", rejected.stderr)
        self.assertEqual((self.root / "oasis_harness/__init__.py").read_bytes(), before)
        self.stage_delta()
        self.git("commit", "-m", "Reviewed predecessor delta")
        self.assertIn(b'__version__ = "1.2.4"', self.committed())
        self.assertNotEqual(self.git("commit", "--allow-empty", "-m", "Missing next delta", check=False).returncode, 0)
        self.stage_delta(version="1.2.5", previous="1.2.4", files=[])
        self.git("commit", "-m", "Explicit version-only delta")
        self.assertIn(b'__version__ = "1.2.5"', self.committed())

    def test_tracked_version_index_cannot_be_removed_to_skip_note_gate(self):
        self.stage_work(); self.stage_delta()
        self.git("commit", "-m", "Introduce version delta")
        self.git("rm", "--cached", "docs/upgrade-index.json")
        before = (self.root / "oasis_harness/__init__.py").read_bytes()
        rejected = self.git("commit", "-m", "Remove delta gate", check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn(b"Keep the tracked version delta", rejected.stderr)
        self.assertEqual((self.root / "oasis_harness/__init__.py").read_bytes(), before)

    def test_exact_reset_reuses_a_label_without_losing_chronological_history(self):
        self.stage_work(); self.stage_delta()
        self.git("commit", "-m", "First indexed patch")
        self.stage_delta(version="1.2.5", previous="1.2.4", files=[])
        self.git("commit", "-m", "Second indexed patch")
        path=self.root/"oasis_harness/__init__.py"
        path.write_bytes(path.read_bytes().replace(b"1.2.5",b"1.2.4"))
        self.git("add","--","oasis_harness/__init__.py")
        self.stage_delta(version="1.2.4", previous="1.2.5", files=[])
        self.git("-c","oasis.versionTarget=1.2.4","commit","-m","Explicit indexed reset")
        history=json.loads((self.root/"docs/upgrade-index.json").read_text())["releases"]
        self.assertEqual([r["version"] for r in history],["1.2.4","1.2.5","1.2.4"])
        self.stage_delta(version="1.2.5", previous="1.2.4", files=[])
        self.git("commit","-m","Ordinary patch after indexed reset")
        self.assertIn(b'__version__ = "1.2.5"',self.committed())

    def test_earlier_delta_cannot_be_dropped_by_a_normal_next_patch(self):
        self.stage_work(); self.stage_delta()
        self.git("commit","-m","Indexed patch")
        self.stage_delta(version="1.2.5",previous="1.2.4",files=[])
        path=self.root/"docs/upgrade-index.json"
        value=json.loads(path.read_text());value["releases"]=value["releases"][-1:]
        path.write_text(json.dumps(value),encoding="utf-8");self.git("add","--","docs/upgrade-index.json")
        result=self.git("commit","-m","Dropped history",check=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn(b"Retain prior chronological",result.stderr)

    def test_command_local_exact_reset_then_normal_patch(self):
        before = (self.root / ".oasis/core.json").read_bytes()
        self.stage_exact_version()
        self.git("-c", "oasis.versionTarget=1.0.0", "commit", "-m", "Owner-selected exact reset")
        self.assertIn(b'__version__ = "1.0.0"', self.committed())
        self.git("commit", "--allow-empty", "-m", "Normal patch resumes")
        self.assertIn(b'__version__ = "1.0.1"', self.committed())
        self.assertEqual((self.root / ".oasis/core.json").read_bytes(), before)

    def test_exact_reset_failed_retry_keeps_same_target(self):
        blocker = self.root / ".githooks/commit-msg"
        blocker.write_bytes(b"#!/bin/sh\nexit 1\n")
        os.chmod(blocker, 0o755)
        self.stage_exact_version()
        result = self.git("-c", "oasis.versionTarget=1.0.0", "commit", "-m", "Rejected exact reset", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'__version__ = "1.2.3"', self.committed())
        self.assertIn(b'__version__ = "1.0.0"', (self.root / "oasis_harness/__init__.py").read_bytes())
        blocker.unlink()
        self.git("-c", "oasis.versionTarget=1.0.0", "commit", "-m", "Retry exact reset")
        self.assertIn(b'__version__ = "1.0.0"', self.committed())

    def test_exact_target_refuses_persistent_conflicting_or_unstaged_selection(self):
        self.stage_work()
        before = (self.root / "oasis_harness/__init__.py").read_bytes()
        staged = self.git("show", ":oasis_harness/__init__.py").stdout
        self.assertNotEqual(self.git("-c", "oasis.versionTarget=1.0.0", "commit", "-m", "Target not staged", check=False).returncode, 0)
        self.assertEqual((self.root / "oasis_harness/__init__.py").read_bytes(), before)
        self.assertEqual(self.git("show", ":oasis_harness/__init__.py").stdout, staged)
        self.stage_exact_version()
        self.git("config", "oasis.versionTarget", "1.0.0")
        self.assertNotEqual(self.git("commit", "-m", "Persistent target", check=False).returncode, 0)
        self.git("config", "--unset", "oasis.versionTarget")
        self.assertNotEqual(self.git("-c", "oasis.versionTarget=1.0.0", "-c", "oasis.versionBase=1.0.0", "commit", "-m", "Ambiguous version", check=False).returncode, 0)
        self.git("-c", "oasis.versionTarget=1.0.0", "commit", "-m", "Exact selected target")
        self.assertNotEqual(self.git("-c", "oasis.versionTarget=1.0.0", "commit", "--allow-empty", "-m", "Target already committed", check=False).returncode, 0)

    def test_partial_path_commit_refuses_before_version_mutation(self):
        self.stage_work()
        before = (self.root / "oasis_harness/__init__.py").read_bytes()
        head = self.git("rev-parse", "HEAD").stdout
        result = self.git("commit", "--only", "work.txt", "-m", "Partial", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.git("rev-parse", "HEAD").stdout, head)
        self.assertEqual((self.root / "oasis_harness/__init__.py").read_bytes(), before)

    def test_amend_creates_one_new_patch_version(self):
        self.stage_work()
        self.git("commit", "-m", "First")
        self.git("commit", "--amend", "--no-edit")
        self.assertIn(b'__version__ = "1.2.5"', self.committed())


if __name__ == "__main__":
    unittest.main()
