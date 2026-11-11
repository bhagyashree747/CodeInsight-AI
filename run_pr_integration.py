"""Integration runner connecting Member 2 (Code Engine), Member 1 (Pipeline), and Member 3 (Verifier)."""

from __future__ import annotations

import logging
from typing import Any

from app.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def run_pr_review_and_repair(
    pr_url_or_files: str | list[dict[str, Any]],
    client: Any = None,
    verifier: Any = None,
    max_attempts: int = 3,
    context_level: str | None = None,
) -> list[dict[str, Any]]:
    """Run review and repair across all changed files in a PR.

    Args:
        pr_url_or_files: Either a PR URL string or pre-extracted files list from Member 2.
        client: LLMClient instance (defaults to get_client() if None).
        verifier: Member 3 Verifier instance (defaults to LocalVerifier if None).
        max_attempts: Maximum repair iterations per finding.
        context_level: Metadata string for context scope ("diff", "function", "file").

    Returns:
        List of pipeline result dicts, one per reviewed file.
    """
    # 1. Obtain files from Member 2's interface if a URL is provided
    if isinstance(pr_url_or_files, str):
        try:
            from app.code_engine.interface import get_review_inputs
            files = get_review_inputs(pr_url_or_files)
        except ImportError:
            logger.warning(
                "Member 2 code_engine not found on this branch yet. "
                "Provide mock files list or test fixtures."
            )
            return []
    else:
        files = pr_url_or_files

    results: list[dict[str, Any]] = []

    # 2. Process each file through Member 1 pipeline
    for f in files:
        file_path = f.get("file", "snippet.py")
        file_text = f.get("text", "")
        changed_lines = f.get("changed_lines")
        functions = f.get("functions")

        # Convert changed_lines to set if passed as list
        if isinstance(changed_lines, list):
            changed_lines = set(changed_lines)

        file_result = run_pipeline(
            code=file_text,
            file=file_path,
            changed_lines=changed_lines,
            functions=functions,
            client=client,
            verifier=verifier,
            max_attempts=max_attempts,
            context_level=context_level,
        )
        results.append(file_result)

    return results


if __name__ == "__main__":
    # Smoke-test run with mock files
    mock_files = [
        {
            "file": "requests/models.py",
            "text": "def prepare_url(url, params):\n    return url\n",
            "changed_lines": {2},
            "language": "python",
            "functions": [
                {
                    "name": "prepare_url",
                    "start_line": 1,
                    "end_line": 2,
                    "text": "def prepare_url(url, params):\n    return url\n",
                    "class": None,
                    "changed_lines": {2},
                }
            ],
        }
    ]

    print("Running smoke test on PR integration runner...")
    out = run_pr_review_and_repair(mock_files)
    print(f"Successfully processed {len(out)} file(s).")
    print(f"Result summary: {out[0].get('summary')}")
