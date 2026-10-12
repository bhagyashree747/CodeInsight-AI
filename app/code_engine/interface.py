from app.code_engine.context_builder import build_context, LEVELS, DEFAULT_MAX_FILES
from app.github.client import GitHubClient
from app.github.pull_request import fetch_pull_request


def get_context(pr_url, level="function", max_files=DEFAULT_MAX_FILES, client=None):
    """THE function Member 1 calls.

    pr_url : a GitHub PR link, e.g. https://github.com/psf/requests/pull/6700
    level  : "diff" | "function" | "file"
    Returns a plain dict (see docs/context_format.md). ctx["text"] goes in the prompt.
    """
    client = client or GitHubClient()
    pr = fetch_pull_request(client, pr_url)
    return build_context(pr, level=level, client=client, max_files=max_files)


def get_all_levels(pr_url, max_files=DEFAULT_MAX_FILES, client=None):
    """For Member 3's evaluation: fetch the PR once, build all three levels.
    Returns {"diff": ctx, "function": ctx, "file": ctx}."""
    client = client or GitHubClient()
    pr = fetch_pull_request(client, pr_url)
    return {
        level: build_context(pr, level=level, client=client, max_files=max_files)
        for level in LEVELS
    }