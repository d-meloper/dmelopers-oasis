import json
import subprocess
import unittest
from unittest.mock import patch
from oasis_harness.common import HarnessError
from oasis_harness.github import GitHub, anonymous_download, repository_slug


def reply(stdout, code=0):
    return subprocess.CompletedProcess([],code,stdout,"")


class GitHubTransportContracts(unittest.TestCase):
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
