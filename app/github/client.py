import os
import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Small wrapper around the GitHub REST API."""

    def __init__(self, token=None):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

    def get(self, path, params=None):
        """GET a single API endpoint and return the JSON."""
        response = self.session.get(
            f"{GITHUB_API}{path}", params=params, timeout=30
        )

        if response.status_code == 401:
            raise PermissionError("Bad GitHub token. Check GITHUB_TOKEN in .env")
        if response.status_code == 404:
            raise ValueError("Not found. Check the PR URL (or the repo is private).")
        if (response.status_code == 403
                and response.headers.get("X-RateLimit-Remaining") == "0"):
            raise RuntimeError("GitHub rate limit hit. Wait, or use a token.")

        response.raise_for_status()
        return response.json()

    def get_paginated(self, path, per_page=100):
        """GET an endpoint that returns a list across many pages."""
        results = []
        page = 1
        while True:
            data = self.get(path, params={"per_page": per_page, "page": page})
            results.extend(data)
            if len(data) < per_page:
                break
            page += 1
        return results

    def get_file_text(self, owner, repo, path, ref):
        """Fetch a file's raw text at a given commit. Returns None if not found."""
        response = self.session.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref},
            headers={"Accept": "application/vnd.github.raw+json"},
            timeout=30,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.content.decode("utf-8", errors="replace")