from pathlib import Path
import os
import shutil
from unittest import mock
import unittest

from oasis_harness import backup, gitops
from oasis_harness.common import HarnessError, file_hash, git, operation_lock, read_json, run, write_json
from tests.test_gitops import GitFixture


class LocalProvider:
    def __init__(self, remote):
        self.remote = remote
        self.metadata = {"id": 123, "full_name": "fixture/private", "private": True, "fork": False, "archived": False}
        self.queries = 0

    def assert_stored_oauth(self):
        return {"tokenSource": "keyring"}

    def authenticated_user(self):
        return {"id": 456, "login": "fixture"}

    def read_repository(self, slug):
        self.queries += 1
        return dict(self.metadata)

    def fixture_git_url(self, slug):
        return self.remote

    def git_environment(self):
        return backup._plumbing_environment()


class BackupTests(GitFixture):
    def test_new_binding_export_preserves_existing_evidence(self):
        output = self.root.parent / "binding.json"
        backup.export_binding(self.root, output)
        before = output.read_bytes()
        with self.assertRaises(HarnessError):
            backup.export_binding(self.root, output)
        self.assertEqual(output.read_bytes(), before)

    def setUp(self):
        super().setUp()
        self.activate("main-test")
        self.remote = self.base / "private-remote.git"
        run(["git", "init", "--bare", str(self.remote)])
        self.provider = LocalProvider(self.remote)
        self.relay = self.base / "external-relay/relay.git"
        backup.configure(self.root, "fixture/private", self.relay, 123, 456, provider=self.provider)

    def test_run_covers_ref_trigger_and_keeps_dirty_index(self):
        first = backup.run_backup(self.root, provider=self.provider, triggering_commit=self.baseline)
        (self.root / "data.txt").write_bytes(b"staged user bytes")
        git(self.root, "add", "data.txt")
        (self.root / "data.txt").write_bytes(b"unstaged user bytes")
        (self.root / "unknown.txt").write_bytes(b"untracked")
        (self.root / "ignored.bin").write_bytes(b"ignored")
        index = (self.root / ".git/index").read_bytes()
        second = backup.run_backup(self.root, provider=self.provider, triggering_commit=self.baseline)
        self.assertEqual(first["catalog"], second["catalog"])
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        self.assertEqual((self.root / "data.txt").read_bytes(), b"unstaged user bytes")
        self.assertFalse(second["working_files_backed_up"])
        self.assertEqual(git(self.root, "remote"), "")
        self.assertTrue(backup.status(self.root, provider=self.provider)["source_refs_match"])

    def test_remote_only_restore_and_copied_source_inactive(self):
        result = backup.run_backup(self.root, provider=self.provider)
        config = backup._config(self.root)
        # Prove restore never needs relay objects; only the remote provider.
        config["relay"] = str(self.base / "lost-relay.git")
        restored = self.base / "remote-only restore"
        proof = backup.restore(config, restored, provider=self.provider)
        self.assertEqual(proof["catalog"], result["catalog"])
        self.assertFalse(proof["active"])
        self.assertEqual(git(restored, "rev-parse", "main"), self.baseline)
        self.assertFalse(gitops.status(restored)["active"])
        self.assertEqual(git(restored, "remote"), "")
        self.assertEqual(git(restored, "config", "--get", "core.hooksPath"), os.devnull)
        gitops.activate(restored, "main-test", self.baseline, rebind=True)
        self.assertTrue(gitops.status(restored)["active"])
        copied = self.base / "copied source"
        shutil.copytree(self.root, copied)
        with self.assertRaisesRegex(HarnessError, "inherit"):
            backup.status(copied, provider=self.provider)

    def test_append_only_catalog_and_changed_identity_rejected(self):
        first = backup.run_backup(self.root, provider=self.provider)
        new = self.commit("new source")
        second = backup.run_backup(self.root, provider=self.provider, triggering_commit=new)
        self.assertNotEqual(first["catalog"], second["catalog"])
        git(self.remote, "merge-base", "--is-ancestor", first["catalog"], second["catalog"])
        self.provider.metadata["private"] = False
        with self.assertRaisesRegex(HarnessError, "visibility"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(gitops.head(self.root), new)

    def test_lock_contention_cannot_release_owner(self):
        lock = self.relay.parent / "oasis-backup.lock"
        with operation_lock(lock):
            token = read_json(lock)["token"]
            with self.assertRaises(HarnessError):
                backup.run_backup(self.root, provider=self.provider)
            self.assertEqual(read_json(lock)["token"], token)
            with self.assertRaises(HarnessError):
                with operation_lock(lock):
                    pass
        self.assertFalse(lock.exists())

    def test_relay_redirect_and_source_local_rewrite_cannot_change_destination(self):
        git(self.root, "config", "url.https://wrong.invalid/.insteadOf", str(self.remote))
        # ls-remote must not discover source local configuration even if the
        # invoking shell is inside that source checkout.
        with mock.patch("os.getcwd", return_value=str(self.root)):
            self.assertEqual(backup._remote_refs(backup._config(self.root), self.provider), {})
        git(self.relay, "config", "url.https://wrong.invalid/.insteadOf", str(self.remote))
        with self.assertRaisesRegex(HarnessError, "unapproved transport"):
            backup.run_backup(self.root, provider=self.provider)

    def test_enable_requires_real_restore_and_auto_exact_commit(self):
        self.assertTrue(backup.automatic(self.root, self.baseline, provider=self.provider)["inactive"])
        with mock.patch.object(backup, "restore", side_effect=HarnessError("restore failed")):
            with self.assertRaises(HarnessError):
                backup.enable_auto(self.root, self.base / "failed restore", provider=self.provider)
        self.assertFalse(backup._config(self.root)["automatic_enabled"])
        enabled = backup.enable_auto(self.root, self.base / "proof restore", provider=self.provider)
        self.assertTrue(enabled["automatic_enabled"])
        result = backup.automatic(self.root, self.baseline, provider=self.provider)
        self.assertEqual(result["triggering_commit"], self.baseline)

    def test_foreign_relay_record_and_restore_target_race_preserved(self):
        other = self.base / "unowned/empty.git"
        other.parent.mkdir()
        record = other.parent / "oasis-relay.json"
        record.write_bytes(b'{"foreign":true}\n')
        with self.assertRaisesRegex(HarnessError, "ownership record"):
            backup.configure(self.root, "fixture/private", other, 123, 456, provider=self.provider)
        self.assertEqual(record.read_bytes(), b'{"foreign":true}\n')
        self.assertFalse(other.exists())
        backup.run_backup(self.root, provider=self.provider)
        target = self.base / "raced restore"
        real_remote = backup._remote_refs
        calls = 0
        def foreign_write(config, provider):
            nonlocal calls
            values = real_remote(config, provider)
            calls += 1
            if calls == 2:
                target.mkdir()
                (target / "data.txt").write_bytes(b"foreign-new-work")
            return values
        with mock.patch.object(backup, "_remote_refs", side_effect=foreign_write):
            with self.assertRaisesRegex(HarnessError, "foreign bytes"):
                backup.restore(backup._config(self.root), target, provider=self.provider)
        self.assertEqual((target / "data.txt").read_bytes(), b"foreign-new-work")
        self.assertFalse((target / ".git").exists())

    def test_checkout_race_and_ambient_global_hooks_do_not_overwrite(self):
        backup.run_backup(self.root, provider=self.provider)
        target = self.base / "checkout race"
        real_git = backup._git_owned
        def late_writer(root, *args, **kwargs):
            if Path(root) == target and args[0] == "checkout-index":
                (target / "data.txt").write_bytes(b"late-owner-bytes")
            return real_git(root, *args, **kwargs)
        with mock.patch.object(backup, "_git_owned", side_effect=late_writer):
            with self.assertRaises(HarnessError):
                backup.restore(backup._config(self.root), target, provider=self.provider)
        self.assertEqual((target / "data.txt").read_bytes(), b"late-owner-bytes")
        self.assertTrue((target / ".git/oasis/restore-pending.json").exists())
        global_home = self.base / "malicious global"
        hooks = global_home / "hooks"; hooks.mkdir(parents=True)
        marker = self.base / "global-hook-ran"
        for name in ("reference-transaction", "post-checkout"):
            (hooks / name).write_text('#!/bin/sh\necho ran > "' + marker.as_posix() + '"\n', encoding="utf-8", newline="\n")
        run(["git", "config", "--file", str(global_home / ".gitconfig"), "core.hooksPath", str(hooks)])
        run(["git", "config", "--file", str(global_home / ".gitconfig"), "url.https://wrong.invalid/.insteadOf", str(self.remote)])
        with mock.patch.dict(os.environ, {"HOME": str(global_home), "USERPROFILE": str(global_home), "XDG_CONFIG_HOME": str(global_home)}):
            proof = backup.restore(backup._config(self.root), self.base / "isolated restore", provider=self.provider)
            self.assertFalse(proof["active"])
            backup.run_backup(self.root, provider=self.provider)
        self.assertFalse(marker.exists())

    def test_retained_history_external_objects_are_rejected(self):
        (self.root / ".gitattributes").write_text("*.bin filter=lfs\n", encoding="utf-8")
        git(self.root, "add", ".gitattributes")
        git(self.root, "commit", "-m", "historical LFS policy")
        git(self.root, "rm", ".gitattributes")
        git(self.root, "commit", "-m", "remove current policy")
        with self.assertRaisesRegex(HarnessError, "Retained Git LFS attributes"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(git(self.remote, "for-each-ref"), "")


class BackupScaleTests(GitFixture):
    def test_large_atomic_refset_and_lost_acknowledgement_reconcile(self):
        names = ["refs/tags/archive/" + str(index).zfill(3) + "-" + "r" * 90 for index in range(260)]
        git(self.root, "update-ref", "--stdin", input_text="\n".join(f"create {name} {self.baseline}" for name in names) + "\n")
        self.activate()
        remote = self.base / "private-remote.git"
        run(["git", "init", "--bare", str(remote)])
        provider = LocalProvider(remote)
        relay = self.base / "external/relay.git"
        backup.configure(self.root, "fixture/private", relay, 123, 456, provider=provider)
        real_run = backup.run
        observed = []
        def lost_acknowledgement(args, **kwargs):
            if "push" in args:
                observed.append(list(args))
                include = next(arg for arg in args if arg.startswith("include.path="))
                content = Path(include.split("=", 1)[1]).read_text(encoding="utf-8")
                self.assertGreater(len(content), 32767)
                self.assertIn("--atomic", args)
                self.assertFalse(any(arg in args for arg in ("--force", "--mirror", "--prune")))
                self.assertLess(sum(len(str(arg)) + 1 for arg in args), 4096)
                real_run(args, **kwargs)
                raise HarnessError("fixture lost acknowledgement after actual atomic push")
            return real_run(args, **kwargs)
        with mock.patch.object(backup, "run", side_effect=lost_acknowledgement):
            with self.assertRaisesRegex(HarnessError, "lost acknowledgement"):
                backup.run_backup(self.root, provider=provider)
        retained = read_json(relay.parent / "last-operation.json")
        self.assertEqual(retained["phase"], "push_intent")
        self.assertTrue(Path(retained["transport"]["path"]).is_file())
        remote_refs = backup._remote_refs(backup._config(self.root), provider)
        self.assertTrue(all(remote_refs.get(name) == oid for name, oid in retained["expected"].items()))
        with mock.patch.object(backup, "run", side_effect=lost_acknowledgement):
            reconciled = backup.run_backup(self.root, provider=provider)
        self.assertEqual(reconciled["status"], "verified")
        self.assertEqual(len(observed), 1)
        self.assertEqual(git(self.root, "remote"), "")
        self.assertEqual(git(relay, "remote"), "")


class IsolatedSourceBackupTests(GitFixture):
    """Explicit manual backup of a source checkout without an adopter manifest."""
    CAPTURE = "refs/codex/turn-diffs/captures/1234567890000/11111111-2222-4333-8444-555555555555/base"
    CHECKPOINT = "refs/codex/turn-diffs/checkpoints/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/1234567890001/66666666-7777-4888-8999-000000000000"

    def setUp(self):
        super().setUp()
        git(self.root, "rm", ".oasis/project.json")
        self.hook = self.root / ".githooks/pre-commit"
        self.hook.parent.mkdir()
        self.hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n")
        self.hook.chmod(self.hook.stat().st_mode | 0o111)
        git(self.root, "config", "--local", "core.hooksPath", ".githooks")
        git(self.root, "add", ".githooks/pre-commit")
        git(self.root, "commit", "-m", "Independent unmanaged source")
        self.baseline = gitops.head(self.root)
        self.remote = self.base / "isolated-private.git"
        run(["git", "init", "--bare", "--template=", str(self.remote)])
        self.provider = LocalProvider(self.remote)
        self.relay = self.base / "isolated-relay/relay.git"

    def configure(self):
        return backup.configure(self.root, "fixture/private", self.relay, 123, 456,
                                provider=self.provider, source_policy="isolated-unmanaged")

    def test_explicit_policy_preserves_source_hooks_and_dirty_index(self):
        with self.assertRaisesRegex(HarnessError, "inactive"):
            backup.configure(self.root, "fixture/private", self.relay, 123, 456, provider=self.provider)
        self.assertFalse(self.relay.exists())
        self.assertFalse((self.root / ".git/oasis/backup.json").exists())
        before_config = (self.root / ".git/config").read_bytes()
        before_hook = self.hook.read_bytes()
        self.configure()
        self.assertFalse((self.root / ".oasis/install-manifest.json").exists())
        self.assertFalse((self.root / ".oasis/project.json").exists())
        self.assertFalse(gitops.status(self.root)["active"])
        config = backup._config(self.root)
        self.assertEqual(config["source_policy"], "isolated-unmanaged")
        self.assertEqual(config["source_hooks"]["local_values"], [".githooks"])
        self.assertEqual(config["source_hooks"]["files"]["pre-commit"], file_hash(self.hook))
        (self.root / "data.txt").write_bytes(b"staged source work")
        git(self.root, "add", "data.txt")
        (self.root / "data.txt").write_bytes(b"unstaged source work")
        index = (self.root / ".git/index").read_bytes()
        result = backup.run_backup(self.root, provider=self.provider, triggering_commit=self.baseline)
        self.assertEqual(result["status"], "verified")
        self.assertEqual((self.root / ".git/index").read_bytes(), index)
        self.assertEqual((self.root / "data.txt").read_bytes(), b"unstaged source work")
        self.assertEqual((self.root / ".git/config").read_bytes(), before_config)
        self.assertEqual(self.hook.read_bytes(), before_hook)
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/source/main"), self.baseline)
        status = backup.status(self.root, provider=self.provider)
        self.assertTrue(status["source_refs_match"])
        self.assertTrue(status["source_main_match"])

    def test_hook_bytes_configuration_and_additions_block_without_replacement(self):
        self.configure()
        hook = self.hook.read_bytes()
        self.hook.write_bytes(hook + b"# changed by the owner\n")
        with self.assertRaisesRegex(HarnessError, "hooks changed"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(self.hook.read_bytes(), hook + b"# changed by the owner\n")
        self.hook.write_bytes(hook)
        git(self.root, "config", "--local", "core.hooksPath", ".other-hooks")
        with self.assertRaisesRegex(HarnessError, "hooks changed"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(git(self.root, "config", "--get", "core.hooksPath"), ".other-hooks")
        git(self.root, "config", "--local", "core.hooksPath", ".githooks")
        (self.hook.parent / "post-commit").write_bytes(b"#!/bin/sh\nexit 0\n")
        with self.assertRaisesRegex(HarnessError, "hooks changed"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(git(self.remote, "for-each-ref"), "")

    def test_added_remote_and_managed_policy_are_preserved_and_refused(self):
        self.configure()
        git(self.root, "remote", "add", "unexpected", str(self.remote))
        with self.assertRaisesRegex(HarnessError, "no remotes"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(git(self.root, "remote"), "unexpected")
        git(self.root, "remote", "remove", "unexpected")
        write_json(self.root / ".oasis/project.json", {"git": {"profile": "single-main"}})
        with self.assertRaisesRegex(HarnessError, "unmanaged project policy"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(read_json(self.root / ".oasis/project.json")["git"]["profile"], "single-main")
        self.assertEqual(git(self.remote, "for-each-ref"), "")

    def test_private_identity_checks_precede_new_binding(self):
        for key, value in (("id", 999), ("fork", True), ("private", False)):
            with self.subTest(key=key):
                before = dict(self.provider.metadata)
                self.provider.metadata[key] = value
                with self.assertRaisesRegex(HarnessError, "identity or visibility"):
                    self.configure()
                self.assertFalse(self.relay.exists())
                self.assertFalse((self.root / ".git/oasis/backup.json").exists())
                self.provider.metadata = before

    def test_no_automatic_activation_or_managed_binding_downgrade(self):
        self.configure()
        with self.assertRaisesRegex(HarnessError, "manual-only"):
            backup.enable_auto(self.root, self.base / "unapproved-auto-restore", provider=self.provider)
        self.assertFalse((self.base / "unapproved-auto-restore").exists())
        self.assertTrue(backup.automatic(self.root, self.baseline, provider=self.provider)["inactive"])
        self.assertFalse(backup._config(self.root)["automatic_enabled"])
        write_json(self.root / ".git/oasis/binding.json", {"schema_version": 1, "profile": "single-main"})
        with self.assertRaisesRegex(HarnessError, "does not deactivate"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertTrue((self.root / ".git/oasis/binding.json").exists())

    def test_capture_trees_are_private_immutable_refs_and_restore_exactly(self):
        main_tree = git(self.root, "rev-parse", "main^{tree}")
        private_blob = backup._git_owned(self.root, "hash-object", "-w", "--stdin", input_text="Private capture fixture\n")
        private_tree = backup._git_owned(self.root, "mktree", input_text=f"100644 blob {private_blob}\tcapture-only.txt\n")
        git(self.root, "update-ref", "--create-reflog", self.CAPTURE, main_tree)
        git(self.root, "update-ref", self.CHECKPOINT, private_tree)
        source_refs = gitops.refs(self.root)
        self.configure()
        result = backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(gitops.refs(self.root), source_refs)
        catalog = backup._read_catalog(self.relay, result["catalog"])
        self.assertEqual(catalog["source_policy"], "isolated-unmanaged")
        self.assertEqual(catalog["refs"][self.CAPTURE], main_tree)
        self.assertEqual(catalog["refs"][self.CHECKPOINT], private_tree)
        for name, oid in ((self.CAPTURE, main_tree), (self.CHECKPOINT, private_tree)):
            mapped = backup._map(name, oid)
            self.assertTrue(mapped.startswith("refs/tags/source-local-captures/"))
            self.assertEqual(git(self.remote, "rev-parse", mapped), oid)
            self.assertEqual(git(self.remote, "cat-file", "-t", mapped), "tree")
        added_capture = self.CAPTURE.replace("1234567890000", "1234567890002")
        git(self.root, "update-ref", added_capture, private_tree)
        source_refs = gitops.refs(self.root)
        status = backup.status(self.root, provider=self.provider)
        self.assertTrue(status["source_main_match"])
        self.assertFalse(status["source_refs_match"])
        self.assertFalse(status["source_auxiliary_refs_match"])
        # Restore resolves only the private remote; these original paths are absent.
        config = backup._config(self.root)
        config["primary"] = str(self.base / "lost-source")
        config["relay"] = str(self.base / "lost-relay.git")
        # Keep the destination short: the immutable checkpoint ref itself is long.
        restored = self.base / "r"
        proof = backup.restore(config, restored, provider=self.provider)
        self.assertEqual(proof["main"], self.baseline)
        self.assertEqual(proof["main_tree"], main_tree)
        self.assertEqual(git(restored, "rev-parse", self.CAPTURE), main_tree)
        self.assertEqual(git(restored, "rev-parse", self.CHECKPOINT), private_tree)
        self.assertEqual(gitops.refs(self.root), source_refs)
        self.assertEqual(git(restored, "remote"), "")
        self.assertEqual(git(restored, "config", "--get", "core.hooksPath"), os.devnull)
        self.assertFalse(proof["active"])
        self.assertFalse(backup.status(restored, provider=self.provider)["configured"])

    def test_primary_match_does_not_hide_unbacked_source_commit(self):
        self.configure()
        backup.run_backup(self.root, provider=self.provider)
        self.commit("new ordinary source commit")
        status = backup.status(self.root, provider=self.provider)
        self.assertFalse(status["source_main_match"])
        self.assertFalse(status["source_refs_match"])

    def test_unknown_codex_refs_and_non_tree_capture_remain_blocked(self):
        tree = git(self.root, "rev-parse", "main^{tree}")
        git(self.root, "update-ref", self.CAPTURE, tree)
        with self.assertRaisesRegex(HarnessError, "Unclassified source ref"):
            backup._selected(self.root)  # Original managed policy has no exception.
        self.configure()
        unknown = "refs/codex/turn-diffs/captures/not-a-supported-capture/base"
        git(self.root, "update-ref", unknown, tree)
        with self.assertRaisesRegex(HarnessError, "Unclassified source ref"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(git(self.root, "rev-parse", unknown), tree)
        self.assertEqual(git(self.remote, "for-each-ref"), "")
        git(self.root, "update-ref", "-d", unknown, tree)
        git(self.root, "update-ref", self.CAPTURE, self.baseline, tree)
        with self.assertRaisesRegex(HarnessError, "regular trees"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(git(self.root, "rev-parse", self.CAPTURE), self.baseline)
        link_blob = backup._git_owned(self.root, "hash-object", "-w", "--stdin", input_text="outside-project")
        linked_tree = backup._git_owned(self.root, "mktree", input_text=f"120000 blob {link_blob}\tlinked-entry\n")
        git(self.root, "update-ref", self.CAPTURE, linked_tree, self.baseline)
        with self.assertRaisesRegex(HarnessError, "links/submodules"):
            backup.run_backup(self.root, provider=self.provider)
        self.assertEqual(git(self.root, "rev-parse", self.CAPTURE), linked_tree)
        self.assertEqual(git(self.remote, "for-each-ref"), "")


if __name__ == "__main__":
    unittest.main()
