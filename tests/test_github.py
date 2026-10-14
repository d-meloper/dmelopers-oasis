import json
import subprocess
import unittest
from unittest.mock import patch
from oasis_harness.common import HarnessError
from oasis_harness.github import GitHub, anonymous_download, repository_slug


def reply(stdout, code=0):
    return subprocess.CompletedProcess([],code,stdout,"")


class GitHubTransportContracts(unittest.TestCase):
    def test_authenticated_asset_stream_hashes_and_bounds_owned_child(self):
        import sys
        import hashlib
        real_popen = subprocess.Popen
        def fixture_child(argv, **kwargs):
            return real_popen([sys.executable, "-B", "-c", "import sys; sys.stdout.buffer.write(b'1234')"], **kwargs)
        provider = GitHub()
        with patch.object(provider, "assert_stored_oauth"), patch("oasis_harness.github.subprocess.Popen", side_effect=fixture_child):
            self.assertEqual(provider.asset_digest("fixture/repo", {"id": 1, "size": 4}), hashlib.sha256(b"1234").hexdigest())
            with self.assertRaisesRegex(HarnessError, "exceeds"):
                provider.asset_digest("fixture/repo", {"id": 1, "size": 3})
            with self.assertRaisesRegex(HarnessError, "incomplete"):
                provider.asset_digest("fixture/repo", {"id": 1, "size": 5})

    def test_chunk_limits_reject_oversize_and_truncated_reads(self):
        import io
        class Response(io.BytesIO):
            headers = {}
        for data, expected, message in ((b"12345", 4, "exceeds"), (b"123", 4, "before")):
            response = Response(data)
            opener = unittest.mock.Mock()
            opener.open.return_value = response
            with self.subTest(data=data), patch("oasis_harness.github.urllib.request.build_opener", return_value=opener):
                with self.assertRaisesRegex(HarnessError, message):
                    anonymous_download("https://raw.githubusercontent.com/fixture/repo/file", max_bytes=expected, expected_size=expected)
        response = Response(b"1234")
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        with patch("oasis_harness.github.urllib.request.build_opener", return_value=opener):
            self.assertEqual(anonymous_download("https://raw.githubusercontent.com/fixture/repo/file", max_bytes=4, expected_size=4), b"1234")

    def test_stored_oauth_and_isolated_git_environment(self):
        status=json.dumps({"hosts":{"github.com":[{"active":True,"state":"success","tokenSource":"keyring","login":"fixture"}]}})
        with patch("oasis_harness.github.run",side_effect=[reply(status),reply("gho_"+"x"*30)]):
            env=GitHub().git_environment()
        self.assertEqual(env["GIT_CONFIG_NOSYSTEM"],"1")
        self.assertEqual(env["GIT_CONFIG_VALUE_2"],"false")
        self.assertNotIn("GH_TOKEN",env)

    def test_plaintext_or_pat_never_accepted_or_echoed(self):
        for store,token in (("file","gho_"+"x"*30),("keyring","ghp_"+"s"*30)):
            status=json.dumps({"hosts":{"github.com":[{"active":True,"state":"success","tokenSource":store}]}})
            with patch("oasis_harness.github.run",side_effect=[reply(status),reply(token)]):
                with self.assertRaises(HarnessError) as error:GitHub().assert_stored_oauth()
                self.assertNotIn(token,str(error.exception))

    def test_arbitrary_hosts_and_credentials_not_followed(self):
        for url in ("http://github.com/a", "https://" + "user:secret" + "@github.com/a", "https://example.invalid/a"):
            with self.assertRaises(HarnessError):anonymous_download(url)
        for slug in ("https://github.com/a/b","a/..","a/b/escape"):
            with self.assertRaises(HarnessError):repository_slug(slug)
