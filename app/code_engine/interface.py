from app.code_engine.context_builder import build_context, LEVELS, DEFAULT_MAX_FILES
from app.code_engine.review_input import (
    build_review_inputs,
    DEFAULT_MAX_CHARS as REVIEW_MAX_CHARS,
    DEFAULT_MAX_FILES as REVIEW_MAX_FILES,
)
from app.github.client import GitHubClient
from app.github.pull_request import fetch_pull_request


def get_review_inputs(pr_url, max_chars=REVIEW_MAX_CHARS, max_files=REVIEW_MAX_FILES, client=None):
    """FOR MEMBER 1. Returns a list with one dict per changed file:
    {file, text, changed_lines, language, truncated, + extras}.
    text = whole file (new version), no line numbers. See docs/context_format.md."""
    client = client or GitHubClient()
    pr = fetch_pull_request(client, pr_url)
    return build_review_inputs(pr, client, max_chars=max_chars, max_files=max_files)


def get_context(pr_url, level="function", max_files=DEFAULT_MAX_FILES, client=None):
    """Context text at "diff" | "function" | "file" level (for the evaluation).
    Returns a plain dict (see docs/context_format.md). ctx["text"] goes in the prompt."""
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