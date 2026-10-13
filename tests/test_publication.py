import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest

from oasis_harness.common import HarnessError, digest, read_json, write_json
from oasis_harness.publication import Publisher, blob_sha, load_candidate, public_scan, target_check, provision, scan_projection


MERGED_SHA = "f" * 40


class GitHubFixture:
    """In-memory remote with response-loss injection after a durable mutation."""
    def __init__(self):
        self.repo = {"id": 1, "full_name": "fixture/public", "private": False, "fork": False, "archived": False, "default_branch": "main"}
        existing = b"Existing public fixture README\n"
        self.blobs = {blob_sha(existing): existing}
        self.trees = {"base-tree": {"README.md": {"sha": blob_sha(existing), "mode": "100644"}}}
        self.commits = {"base": {"tree": {"sha": "base-tree"}, "parents": []}}
        self.refs = {"heads/main": "base"}
        self.prs, self.releases, self.assets_data = [], [], {}
        self.lost, self.mutations, self.anonymous = None, [], 0

    def authenticated_user(self):
        return {"id": 7, "login": "fixture"}

    def read_repository(self, slug):
        return self.repo

    def pages(self, path):
        if "/pulls?" in path:
            return copy.deepcopy(self.prs)
        if path.endswith("/releases"):
            return copy.deepcopy(self.releases)
        if path.endswith("/assets"):
            return copy.deepcopy(self.releases[0]["assets"])
        if path.endswith("/statuses"):
            return [{"context": "fixture-check", "state": "success"}]
        raise AssertionError(path)

    def request(self, method, path, payload=None, allow_404=False):
        from urllib.parse import unquote
        path = unquote(path.split("/repos/fixture/public")[-1])
        if method == "GET":
            if path == "": return self.repo
            if path == "/hash-algorithm": return {"hash_algorithm":"sha1"}
            if path == "/immutable-releases": return {"enabled": True}
            if path.startswith("/git/blobs/"):
                data = self.blobs[path.split("/git/blobs/")[1]]
                return {"encoding": "base64", "size": len(data), "content": base64.b64encode(data).decode()}
            if path.startswith("/git/commits/"): return copy.deepcopy(self.commits[path.split("/git/commits/")[1]])
            if path.startswith("/git/trees/"):
                key = path.split("/git/trees/")[1].split("?")[0]
                return {"truncated": False, "tree": [{"path": n, "type": "blob", **v} for n,v in self.trees[key].items()]}
            if path.startswith("/git/ref/"):
                key = path.split("/git/ref/")[1]
                return {"object": {"type": "commit", "sha": self.refs[key]}} if key in self.refs else None
            if path.startswith("/pulls/"): return copy.deepcopy(self.prs[0])
            if path == "/releases/latest": return copy.deepcopy(self.releases[0]) if self.releases and not self.releases[0]["draft"] else None
            if path.startswith("/releases/"): return copy.deepcopy(self.releases[0])
            raise AssertionError((method,path))
        self.mutations.append((method, path))
        if path == "/git/blobs":
            data = base64.b64decode(payload["content"]); sha = blob_sha(data); self.blobs[sha] = data; result = {"sha": sha}
        elif path == "/git/trees":
            tree = copy.deepcopy(self.trees[payload["base_tree"]])
            for row in payload["tree"]:
                if row["sha"] is None: del tree[row["path"]]
                else: tree[row["path"]] = {"sha": row["sha"], "mode": row["mode"]}
            key = digest(tree); self.trees[key] = tree; result = {"sha": key}
        elif path == "/git/commits":
            key = digest(payload); self.commits[key] = {"tree": {"sha": payload["tree"]}, "parents": [{"sha": p} for p in payload["parents"]]}; result = {"sha": key}
        elif path == "/git/refs":
            self.refs[payload["ref"].removeprefix("refs/")] = payload["sha"]; result = {"object": {"sha": payload["sha"]}}
        elif path == "/pulls":
            pr = {"number": 1, "html_url": "https://github.com/fixture/public/pull/1", "merged": False,
                  "head": {"repo": {"id": 1}, "ref": payload["head"], "sha": self.refs["heads/" + payload["head"]]},
                  "base": {"repo": {"id": 1}, "ref": "main", "sha": "base"}}
            self.prs.append(pr); result = copy.deepcopy(pr)
        elif path.endswith("/merge"):
            pr = self.prs[0]; self.commits[MERGED_SHA] = copy.deepcopy(self.commits[pr["head"]["sha"]]); self.refs["heads/main"] = MERGED_SHA; pr.update(merged=True, merge_commit_sha=MERGED_SHA); result = {"merged": True, "sha": MERGED_SHA}
        elif path == "/releases":
            release = {**payload, "id": 2, "html_url": "https://github.com/fixture/public/releases/tag/v1", "assets": []}; self.releases.append(release); result = copy.deepcopy(release)
        elif path == "/releases/2":
            self.releases[0].update(payload, immutable=True); self.refs["tags/v1"] = MERGED_SHA; result = copy.deepcopy(self.releases[0])
        else: raise AssertionError((method,path,payload))
        if path == self.lost:
            self.lost = None
            raise HarnessError("Injected lost response")
        return result

    def upload_asset(self, slug, release_id, name, path, content_type):
        data = Path(path).read_bytes()
        self.assets_data[name] = data
        self.releases[0]["assets"].append({"id": 3, "name": name, "size": len(data), "state": "uploaded"})
        if self.lost == "upload":
            self.lost = None
            raise HarnessError("Injected uploaded response loss")

    def download_asset(self, slug, asset, anonymous=False):
        self.anonymous += int(anonymous)
        return self.assets_data[asset["name"]]

    def download_source(self, slug, commit, path):
        self.anonymous += 1
        return self.blobs[self.trees[self.commits[commit]["tree"]["sha"]][path]["sha"]]


class GraphQLFixture(GitHubFixture):
    """Exact PR merge-identity reads, independently of the mutable main ref."""
    def __init__(self):
        super().__init__()
        self.graphql_reads = []
        self.graphql_response = None
        self.graphql_override = False
        self.graphql_error = False

    def merge_identity(self):
        return {"data": {"repository": {"databaseId": self.repo["id"],
                "pullRequest": {"number": self.prs[0]["number"], "merged": True,
                                "mergeCommit": {"oid": MERGED_SHA}}}}}

    def request(self, method, path, payload=None, allow_404=False):
        if (method, path) == ("POST", "/graphql"):
            self.graphql_reads.append(copy.deepcopy(payload))
            if self.graphql_error:
                raise HarnessError("GraphQL merge identity is unavailable")
            return copy.deepcopy(self.graphql_response if self.graphql_override else self.merge_identity())
        return super().request(method, path, payload, allow_404)


def fixture_candidate(root):
    root.mkdir()
    (root / "assets").mkdir()
    (root / "public").mkdir()
    data = b'Fixture release metadata\n'
    (root / "public/oasis-release.json").write_bytes(data)
    (root / "assets/fixture.txt").write_bytes(b"harmless fixture\n")
    (root / "notes.md").write_bytes(b"Fixture notes\n")
    row = {"sha": blob_sha(data), "mode": "100644", "sha256": digest(data), "file": "public/oasis-release.json"}
    spec = {"schema_version": 1, "config": {"repository": "fixture/public", "repository_id": 1, "base_branch": "main", "channel": "stable", "tag": "v1", "title": "Fixture", "make_latest": True, "required_checks": ["fixture-check"]},
            "repository_id": 1, "account_id": 7, "base_commit": "base", "base_tree": "base-tree", "created_at": "2026-01-01T00:00:00+00:00",
            "public_files": {"oasis-release.json": row}, "assets": {"fixture.txt": {"sha256": digest(b"harmless fixture\n"), "size": 17, "file": "assets/fixture.txt"}},
            "notes_sha256": digest(b"Fixture notes\n"), "projection": {"README.md": {"sha": blob_sha(b"Existing public fixture README\n"), "mode": "100644"}, "oasis-release.json": {"sha": row["sha"], "mode": row["mode"]}}}
    write_json(root / "candidate.json", spec)
    sha = digest(spec)
    write_json(root / "state.json", {"candidate_id": sha, "phase": "prepared", "events": []})
    return sha


class PublicationContracts(unittest.TestCase):
    def test_source_only_stops_after_verified_merge_without_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"candidate";fixture_candidate(root);provider=GitHubFixture()
            spec=read_json(root/"candidate.json");spec["config"].update(operation="source", tag=None, make_latest=False);spec["assets"]={};sha=digest(spec)
            write_json(root/"candidate.json",spec);write_json(root/"state.json",{"candidate_id":sha,"phase":"prepared","events":[]})
            result=Publisher(root,sha,provider).execute("actual caller")
            self.assertEqual(result["phase"],"source_verified")
            self.assertFalse(provider.releases)
            self.assertGreater(provider.anonymous,0)
    def test_crash_intent_without_visible_object_stays_unresolved(self):
        for operation in ("pull_request", "draft", "upload:fixture.txt"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)/"candidate";sha=fixture_candidate(root);provider=GitHubFixture()
                publisher=Publisher(root,sha,provider)
                if operation != "pull_request": publisher.merge()
                if operation == "upload:fixture.txt":
                    provider.request("POST","/repos/fixture/public/releases",{"tag_name":"v1","target_commitish":MERGED_SHA,"name":"Fixture","body":"Fixture notes\n","draft":True,"prerelease":False})
                state=read_json(root/"state.json");state["events"].append({"operation":operation,"status":"intent"});write_json(root/"state.json",state)
                with self.assertRaises(HarnessError):Publisher(root,sha,provider).execute("actual caller")
                self.assertFalse(provider.releases and not provider.releases[0]["draft"])
                self.assertFalse(any(row[0]=="DELETE" for row in provider.mutations))

    def test_setup_never_adopts_existing_repo_without_exact_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"plan.json";provider=GitHubFixture()
            plan={"schema_version":1,"repository":"fixture/public","account_id":7,"create":True,"repository_id":None,"base_branch":"main","bootstrap_readme":"Fixture public repository\n","protection":{}}
            write_json(path,plan)
            with self.assertRaises(HarnessError):provision(path,"actual caller",True,provider)
            self.assertFalse(provider.mutations)
    def test_publish_and_repeat_verifies_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "candidate"; sha = fixture_candidate(root); provider = GitHubFixture()
            result = Publisher(root, sha, provider).execute("actual test caller")
            self.assertEqual(result["phase"], "verified")
            self.assertGreater(provider.anonymous, 0)
            count = len(provider.mutations)
            Publisher(root, sha, provider).execute("same actual caller")
            self.assertEqual(count, len(provider.mutations))

    def test_response_loss_reconciles_without_duplicate(self):
        for operation in ("/pulls", "/pulls/1/merge", "/releases", "upload", "/releases/2"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "candidate"; sha = fixture_candidate(root); provider = GitHubFixture(); provider.lost = operation
                with self.assertRaises(HarnessError): Publisher(root, sha, provider).execute("actual test caller")
                result = Publisher(root, sha, provider).execute("actual test caller")
                self.assertEqual(result["phase"], "verified")
                self.assertEqual(len(provider.prs), 1)
                self.assertEqual(len(provider.releases), 1)
                self.assertEqual(len(provider.releases[0]["assets"]), 1)

    def test_merged_resume_uses_exact_parent_despite_base_metadata_advance(self):
        for wrong_parent in (False, True):
            with self.subTest(wrong_parent=wrong_parent), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "candidate"; sha = fixture_candidate(root); provider = GitHubFixture()
                provider.lost = "/pulls/1/merge"
                with self.assertRaises(HarnessError):
                    Publisher(root, sha, provider).execute("actual caller")
                provider.prs[0]["base"]["sha"] = "later-public-head"
                provider.refs["heads/main"] = "later-public-head"
                if wrong_parent:
                    provider.commits[MERGED_SHA]["parents"] = [{"sha": "unapproved-base"}]
                    count = len(provider.mutations)
                    with self.assertRaises(HarnessError):
                        Publisher(root, sha, provider).execute("actual caller")
                    self.assertEqual(count, len(provider.mutations))
                else:
                    result = Publisher(root, sha, provider).execute("actual caller")
                    self.assertEqual(result["phase"], "verified")
                    self.assertEqual(len(provider.prs), 1)

    def test_merged_resume_without_legacy_field_uses_retained_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "candidate"; sha = fixture_candidate(root); provider = GraphQLFixture()
            Publisher(root, sha, provider).execute("actual caller")
            del provider.prs[0]["merge_commit_sha"]
            provider.prs[0]["base"]["sha"] = "later-public-head"
            provider.refs["heads/main"] = "later-public-head"
            count = len(provider.mutations)
            result = Publisher(root, sha, provider).execute("same actual caller")
            self.assertEqual(result["merge_commit"], MERGED_SHA)
            self.assertEqual(result["phase"], "verified")
            self.assertEqual(len(provider.mutations), count)
            self.assertEqual(provider.graphql_reads, [])

    def test_lost_merge_response_without_legacy_field_reads_exact_pr_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "candidate"; sha = fixture_candidate(root); provider = GraphQLFixture()
            provider.lost = "/pulls/1/merge"
            with self.assertRaises(HarnessError):
                Publisher(root, sha, provider).execute("actual caller")
            self.assertNotIn("merge_commit", read_json(root / "state.json"))
            del provider.prs[0]["merge_commit_sha"]
            provider.prs[0]["base"]["sha"] = "later-public-head"
            provider.refs["heads/main"] = "later-public-head"
            result = Publisher(root, sha, provider).execute("same actual caller")
            self.assertEqual(result["merge_commit"], MERGED_SHA)
            self.assertEqual(result["phase"], "verified")
            self.assertEqual(provider.graphql_reads[0]["variables"], {"owner": "fixture", "name": "public", "number": 1})
            self.assertTrue(provider.graphql_reads[0]["query"].startswith("query("))
            self.assertEqual(sum(path.endswith("/merge") for method, path in provider.mutations), 1)
            count = len(provider.mutations)
            Publisher(root, sha, provider).execute("same actual caller")
            self.assertEqual(len(provider.mutations), count)
            self.assertEqual(len(provider.graphql_reads), 1)

    def test_merge_identity_conflicts_or_corrupt_saved_state_stop_without_writes(self):
        for fault in ("legacy_conflict", "saved_wrong_tree", "saved_invalid_oid", "saved_wrong_pr"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "candidate"; sha = fixture_candidate(root); provider = GraphQLFixture()
                Publisher(root, sha, provider).execute("actual caller")
                state = read_json(root / "state.json")
                if fault == "legacy_conflict":
                    provider.prs[0]["merge_commit_sha"] = "e" * 40
                else:
                    del provider.prs[0]["merge_commit_sha"]
                    if fault == "saved_wrong_tree":
                        state["merge_commit"] = "e" * 40
                        provider.commits["e" * 40] = {"tree": {"sha": "base-tree"}, "parents": [{"sha": "base"}]}
                    elif fault == "saved_invalid_oid":
                        state["merge_commit"] = "current-main-tip"
                    else:
                        state["pr_number"] = 2
                    write_json(root / "state.json", state)
                count = len(provider.mutations)
                with self.assertRaises(HarnessError):
                    Publisher(root, sha, provider).execute("same actual caller")
                self.assertEqual(len(provider.mutations), count)
                self.assertEqual(provider.graphql_reads, [])

    def test_incomplete_or_wrong_graphql_merge_identity_preserves_uncertain_state(self):
        faults = ("null_response", "errors", "partial_errors", "null_repo", "null_pr", "wrong_repo",
                  "wrong_pr", "not_merged", "null_commit", "invalid_oid", "wrong_oid", "wrong_parent", "wrong_tree", "transport")
        for fault in faults:
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "candidate"; sha = fixture_candidate(root); provider = GraphQLFixture()
                provider.lost = "/pulls/1/merge"
                with self.assertRaises(HarnessError):
                    Publisher(root, sha, provider).execute("actual caller")
                del provider.prs[0]["merge_commit_sha"]
                response = provider.merge_identity()
                remote_repo = response["data"]["repository"]
                remote_pr = remote_repo["pullRequest"]
                if fault == "null_response": response = None
                elif fault == "errors": response = {"errors": [{"message": "fixture detail must stay private"}]}
                elif fault == "partial_errors": response["errors"] = [{"message": "fixture detail must stay private"}]
                elif fault == "null_repo": response["data"]["repository"] = None
                elif fault == "null_pr": remote_repo["pullRequest"] = None
                elif fault == "wrong_repo": remote_repo["databaseId"] = 2
                elif fault == "wrong_pr": remote_pr["number"] = 2
                elif fault == "not_merged": remote_pr["merged"] = False
                elif fault == "null_commit": remote_pr["mergeCommit"] = None
                elif fault == "invalid_oid": remote_pr["mergeCommit"]["oid"] = "current-main-tip"
                elif fault == "wrong_oid":
                    remote_pr["mergeCommit"]["oid"] = "e" * 40
                    provider.commits["e" * 40] = {"tree": {"sha": "base-tree"}, "parents": [{"sha": "base"}]}
                elif fault == "wrong_parent": provider.commits[MERGED_SHA]["parents"] = [{"sha": "wrong-base"}]
                elif fault == "wrong_tree": provider.commits[MERGED_SHA]["tree"] = {"sha": "base-tree"}
                elif fault == "transport": provider.graphql_error = True
                provider.graphql_override, provider.graphql_response = True, response
                before = read_json(root / "state.json")
                count = len(provider.mutations)
                with self.assertRaises(HarnessError) as error:
                    Publisher(root, sha, provider).execute("actual caller")
                self.assertNotIn("fixture detail must stay private", str(error.exception))
                self.assertEqual(read_json(root / "state.json"), before)
                self.assertEqual(len(provider.mutations), count)
                self.assertEqual(len(provider.graphql_reads), 1)
                self.assertFalse(provider.releases)

    def test_wrong_repo_base_and_changed_candidate_stop_before_write(self):
        for fault in ("repo", "base", "bytes", "approval", "preview"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "candidate"; sha = fixture_candidate(root); provider = GitHubFixture()
                if fault == "repo": provider.repo["id"] = 99
                if fault == "base": provider.refs["heads/main"] = "other"
                if fault == "bytes": (root / "assets/fixture.txt").write_bytes(b"changed")
                if fault == "preview":
                    spec = read_json(root / "candidate.json"); spec["config"].update(channel="preview", production_repository_id=1); write_json(root / "candidate.json", spec); sha = digest(spec); write_json(root / "state.json", {"candidate_id": sha, "events": []})
                with self.assertRaises(HarnessError): Publisher(root, sha, provider).execute("" if fault == "approval" else "actual caller")
                self.assertFalse(provider.mutations)

    def test_unexpected_or_partial_assets_are_not_deleted(self):
        for fault in ("extra", "partial", "corrupt"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "candidate"; sha = fixture_candidate(root); provider = GitHubFixture(); provider.lost = "upload"
                with self.assertRaises(HarnessError): Publisher(root, sha, provider).execute("actual caller")
                if fault == "extra": provider.releases[0]["assets"].append({"name": "foreign.bin"})
                if fault == "partial": provider.releases[0]["assets"][0]["state"] = "starter"
                if fault == "corrupt": provider.assets_data["fixture.txt"] = b"corrupt"
                count = len(provider.mutations)
                with self.assertRaises(HarnessError): Publisher(root, sha, provider).execute("actual caller")
                self.assertEqual(count, len(provider.mutations))
                self.assertTrue(provider.releases[0]["draft"])

    def test_confidential_exports_and_similar_safe_text(self):
        for name,data in ((".oasis/local/a.json",b"x"),("README.md",b"C:" + b"\\Users\\person\\private"),("notes.md",b"-----BEGIN " + b"PRIVATE KEY-----")):
            with self.assertRaises(HarnessError): public_scan(name,data)
        public_scan("docs/permissions.md",b"Ask the owner before changing authority.")

    def test_complete_projection_is_scanned_before_any_remote_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "candidate"
            fixture_candidate(root)
            provider = GitHubFixture()
            private = b"C:" + b"\\Users\\fixture\\private.log"
            oid = blob_sha(private)
            provider.blobs[oid] = private
            provider.trees["base-tree"]["README.md"]["sha"] = oid
            spec = read_json(root / "candidate.json")
            spec["projection"]["README.md"]["sha"] = oid
            expected = digest(spec)
            write_json(root / "candidate.json", spec)
            write_json(root / "state.json", {"candidate_id": expected, "phase": "prepared", "events": []})
            with self.assertRaisesRegex(HarnessError, "private material"):
                Publisher(root, expected, provider).execute("reviewed fixture")
            self.assertEqual(provider.mutations, [])

    def test_in_memory_candidate_cannot_bypass_retained_hash_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "candidate"; expected = fixture_candidate(root)
            provider = GitHubFixture(); publisher = Publisher(root, expected, provider)
            publisher.spec["config"]["title"] = "Changed after loading"
            with self.assertRaisesRegex(HarnessError, "In-memory candidate drift"):
                publisher.execute("fixture request")
            self.assertEqual(provider.mutations, [])

    def test_email_and_url_credentials_are_not_public_text(self):
        for content in (b"owner@" + b"personal.test", b"https://" + b"user:pass" + b"@github.com/fixture"):
            with self.assertRaises(HarnessError):
                public_scan("notes.md", content)
        public_scan("notes.md", b"fixture@example.invalid")

    def test_inherited_blob_hash_and_directory_aliases_are_verified(self):
        provider = GitHubFixture()
        projection = dict(provider.trees["base-tree"])
        first = next(iter(provider.blobs))
        provider.blobs[first] = b"changed bytes"
        with self.assertRaisesRegex(HarnessError, "inherited public bytes"):
            scan_projection(provider, "fixture/public", projection, {}, {})
        local = {"Docs/one.txt": b"one", "docs/two.txt": b"two"}
        projection = {name: {"sha": blob_sha(data), "mode": "100644"} for name, data in local.items()}
        with self.assertRaisesRegex(HarnessError, "directory paths"):
            scan_projection(provider, "fixture/public", projection, {}, local)


if __name__ == "__main__": unittest.main()
