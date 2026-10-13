"""GitHub transport using the caller's stored CLI OAuth, never copied credentials."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse, quote
import urllib.request

from .common import HarnessError, clean_environment, run


def repository_slug(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+", value):
        raise HarnessError("Expected exact owner/repository; URLs and inferred destinations are not accepted")
    if value.split("/")[1] in (".", ".."):
        raise HarnessError("Invalid repository name")
    return value


class GitHub:
    def __init__(self, host="github.com"):
        if host != "github.com":
            raise HarnessError("This release supports github.com only; no implicit Enterprise fallback")
        self.host = host

    def assert_stored_oauth(self):
        response = run(["gh", "auth", "status", "--hostname", self.host, "--json", "hosts"], check=False)
        try:
            rows = json.loads(response.stdout)["hosts"][self.host]
            active = [row for row in rows if row.get("active")]
        except (ValueError, KeyError, TypeError):
            raise HarnessError("Cannot establish stored GitHub authentication; inspect gh auth status") from None
        if response.returncode or len(active) != 1 or active[0].get("state") != "success":
            raise HarnessError("One successful active stored GitHub account is required")
        if active[0].get("tokenSource", "").lower() != "keyring":
            raise HarnessError("Stored OAuth must use the OS credential store; plaintext/environment fallback is not accepted")
        # Never log token output, including on error. An OS-stored PAT is not OAuth.
        token = run(["gh", "auth", "token", "--hostname", self.host], check=False)
        if token.returncode or not token.stdout.strip().startswith("gho_"):
            raise HarnessError("Stored credential is not a supported browser OAuth token; no credential is copied or replaced")
        return {key: active[0].get(key) for key in ("host", "login", "state", "tokenSource")}

    def git_environment(self):
        self.assert_stored_oauth()
        return clean_environment({
            "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "4", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": "",
            "GIT_CONFIG_KEY_1": "credential.https://github.com.helper", "GIT_CONFIG_VALUE_1": "!gh auth git-credential",
            "GIT_CONFIG_KEY_2": "http.followRedirects", "GIT_CONFIG_VALUE_2": "false",
            "GIT_CONFIG_KEY_3": "core.hooksPath", "GIT_CONFIG_VALUE_3": os.devnull,
            "GH_HOST": self.host})

    def request(self, method, path, payload=None, allow_404=False):
        if not path.startswith("/") or path.startswith("//") or ".." in path.split("/") or ":" in path:
            raise HarnessError("GitHub API paths must be relative to the fixed approved host")
        self.assert_stored_oauth()
        argv = ["gh", "api", "--hostname", self.host, "--method", method,
                "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2026-03-10", path]
        if payload is not None:
            argv.extend(["--input", "-"])
        result = run(argv, input_text=json.dumps(payload) if payload is not None else None, check=False)
        if result.returncode:
            if allow_404 and "HTTP 404" in result.stderr:
                return None
            # Do not print server bodies which can contain request/private values.
            status = re.search(r"HTTP (\d+)", result.stderr)
            raise HarnessError(f"GitHub {method} rejected or uncertain: {status.group(0) if status else 'transport failure'}; inspect retained operation before retry")
        if not result.stdout.strip():
            return None
        try:
            return json.loads(result.stdout)
        except ValueError:
            raise HarnessError("GitHub response was not valid JSON; outcome uncertain") from None

    def pages(self, path):
        separator = "&" if "?" in path else "?"
        for page in range(1, 10001):
            rows = self.request("GET", f"{path}{separator}per_page=100&page={page}")
            if not isinstance(rows, list):
                raise HarnessError("Expected a complete GitHub list response")
            yield from rows
            if len(rows) < 100:
                return
        raise HarnessError("GitHub pagination limit reached; collection is incomplete")

    def authenticated_user(self):
        return self.request("GET", "/user")

    def read_repository(self, slug):
        return self.request("GET", "/repos/" + repository_slug(slug))

    def upload_asset(self, slug, release_id, name, path, content_type):
        self.assert_stored_oauth()
        # CLI upload has a supported authenticated transport; never --clobber.
        release = self.request("GET", f"/repos/{repository_slug(slug)}/releases/{int(release_id)}")
        if not release.get("draft"):
            raise HarnessError("Assets may only be uploaded to the retained draft")
        if Path(path).name != name:
            raise HarnessError("Retained asset basename differs from approved name")
        result = run(["gh", "release", "upload", release["tag_name"], str(path), "--repo", slug], env={"GH_HOST": self.host}, check=False, timeout=600)
        if result.returncode:
            raise HarnessError("Asset upload failed or is uncertain; reconcile the draft by exact asset identity")

    def download_asset(self, slug, asset, *, anonymous=False):
        if anonymous:
            return anonymous_download(asset["browser_download_url"])
        self.assert_stored_oauth()
        result = subprocess.run(["gh", "api", "--hostname", self.host, "-H", "Accept: application/octet-stream",
                                 f"/repos/{repository_slug(slug)}/releases/assets/{int(asset['id'])}"],
                                capture_output=True, env=clean_environment(), timeout=600)
        if result.returncode:
            raise HarnessError("Authenticated asset readback failed")
        return result.stdout

    def download_source(self, slug, commit, path):
        from .common import safe_relative
        safe_relative(path)
        return anonymous_download(f"https://raw.githubusercontent.com/{repository_slug(slug)}/{quote(commit, safe='')}/{quote(path, safe='/')}")


def anonymous_download(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"github.com", "raw.githubusercontent.com"} or parsed.username or parsed.password:
        raise HarnessError("Expected an anonymous HTTPS GitHub release asset URL")
    class SafeRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target = urlparse(newurl)
            allowed = {"github.com", "raw.githubusercontent.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}
            if target.scheme != "https" or target.hostname not in allowed or target.username or target.password:
                raise HarnessError("Unexpected release download redirect")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    with urllib.request.build_opener(SafeRedirect()).open(url, timeout=120) as response:
        return response.read()
