"""Unit tests for extra_context and context_level across review, repair, and run_pipeline."""

from __future__ import annotations

import pytest
from typing import Any

from app.pipeline import run_pipeline, _error_result
from app.review.prompts import build_user_prompt
from app.review.reviewer import review
from app.repair.prompts import build_repair_prompt, build_function_repair_prompt
from app.repair.verifier_interface import VerificationResult
from app.review.llm_client import MockLLMClient
from app.review.schema import Finding, Category, Severity


class _RecordingMockClient(MockLLMClient):
    """Mock client that records all prompts it receives."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return super().complete(system=system, user=user)


class _AlwaysPassVerifier:
    """Verifier that always reports passed at 'syntax' stage."""

    def verify(self, patched_code: str, file_path: str) -> VerificationResult:
        return VerificationResult(passed=True, stage="syntax", error="", output="")


SQL_SNIPPET = """\
import sqlite3

def get_user(username: str) -> dict | None:
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
"""

DIV_ZERO_SNIPPET = """\
def compute_average(values: list[float]) -> float:
    total = sum(values)
    return total / len(values)
"""


# ---------------------------------------------------------------------------
# 1. extra_context in Review Prompts
# ---------------------------------------------------------------------------

def test_extra_context_appears_in_review_prompt_builder():
    """Verify build_user_prompt includes extra_context placed after the code."""
    code = "def foo(): pass"
    extra_ctx = "class Helper:\n    VALUE = 10"

    prompt = build_user_prompt(context=code, file="test.py", extra_context=extra_ctx)

    assert "Additional context (read-only, do not report issues in it):" in prompt
    assert extra_ctx in prompt
    # Ensure it comes after the code block
    code_pos = prompt.find(code)
    context_pos = prompt.find("Additional context (read-only, do not report issues in it):")
    assert code_pos != -1
    assert context_pos != -1
    assert context_pos > code_pos


def test_extra_context_in_review_call():
    """Verify review() passes extra_context to the LLM client prompt."""
    client = _RecordingMockClient()
    extra_ctx = "# Supplementary module notes\nVALID_MODES = ['read', 'write']"

    findings = review(
        context=DIV_ZERO_SNIPPET,
        file="math_util.py",
        client=client,
        extra_context=extra_ctx,
    )

    assert len(client.calls) >= 1
    first_call_user_prompt = client.calls[0]["user"]
    assert "Additional context (read-only, do not report issues in it):" in first_call_user_prompt
    assert extra_ctx in first_call_user_prompt
    assert len(findings) > 0


def test_extra_context_in_function_level_review_pipeline():
    """Verify run_pipeline with functions passes extra_context to each function review call."""
    client = _RecordingMockClient()
    verifier = _AlwaysPassVerifier()

    functions = [
        {
            "name": "compute_average",
            "start_line": 1,
            "end_line": 3,
            "text": DIV_ZERO_SNIPPET.strip(),
            "too_large": False,
        }
    ]
    extra_ctx = "# Schema definition: values must not be empty"

    result = run_pipeline(
        code=DIV_ZERO_SNIPPET,
        file="avg.py",
        functions=functions,
        client=client,
        verifier=verifier,
        extra_context=extra_ctx,
        context_level="function",
    )

    assert result["context_level"] == "function"
    # Inspect review call prompts
    review_calls = [
        c for c in client.calls
        if "automated code reviewer" in c["system"].lower()
    ]
    assert len(review_calls) >= 1
    for call in review_calls:
        assert "Additional context (read-only, do not report issues in it):" in call["user"]
        assert extra_ctx in call["user"]


# ---------------------------------------------------------------------------
# 2. extra_context in Repair Prompts
# ---------------------------------------------------------------------------

def test_extra_context_in_repair_prompts():
    """Verify build_repair_prompt and build_function_repair_prompt include Related context."""
    finding = Finding(
        file="test.py",
        line=2,
        category=Category.BUG,
        severity=Severity.HIGH,
        confidence=0.9,
        description="Zero division risk",
        suggested_fix_hint="Check length",
        actionable=True,
    )
    extra_ctx = "MAX_RETRIES = 5\nDEFAULT_TIMEOUT = 30"

    # Full repair prompt
    repair_prompt = build_repair_prompt(
        code="def foo(x):\n    return 10 / x",
        finding=finding,
        extra_context=extra_ctx,
    )
    assert "Related context:" in repair_prompt
    assert extra_ctx in repair_prompt

    # Function repair prompt
    func_prompt = build_function_repair_prompt(
        function_text="def foo(x):\n    return 10 / x",
        finding=finding,
        extra_context=extra_ctx,
    )
    assert "Related context:" in func_prompt
    assert extra_ctx in func_prompt


def test_extra_context_in_pipeline_repair_stage():
    """Verify run_pipeline forwards extra_context into the repair stage prompts."""
    client = _RecordingMockClient()
    verifier = _AlwaysPassVerifier()
    extra_ctx = "# Global database connection settings"

    result = run_pipeline(
        code=SQL_SNIPPET,
        file="db.py",
        client=client,
        verifier=verifier,
        extra_context=extra_ctx,
        context_level="module",
    )

    assert result["summary"]["verified"] >= 1
    # Check that repair calls included Related context
    repair_calls = [
        c for c in client.calls
        if "fixing one issue" in c["system"].lower()
    ]
    assert len(repair_calls) >= 1
    for call in repair_calls:
        assert "Related context:" in call["user"]
        assert extra_ctx in call["user"]


# ---------------------------------------------------------------------------
# 3. Default Behaviour Unchanged When extra_context is None
# ---------------------------------------------------------------------------

def test_default_behaviour_unchanged_when_extra_context_omitted():
    """When extra_context is None, neither review nor repair prompts contain extra context sections."""
    client = _RecordingMockClient()
    verifier = _AlwaysPassVerifier()

    result = run_pipeline(
        code=DIV_ZERO_SNIPPET,
        file="math_util.py",
        client=client,
        verifier=verifier,
    )

    # 1. context_level defaults to None
    assert result["context_level"] is None
    assert result["summary"]["verified"] >= 1

    # 2. Prompts do not contain additional context or related context headers
    for call in client.calls:
        assert "Additional context (read-only, do not report issues in it):" not in call["user"]
        assert "Related context:" not in call["user"]

    # 3. Prompt builder with None or empty whitespace returns clean prompt
    clean_user_prompt = build_user_prompt(context="def f(): pass", file="clean.py", extra_context=None)
    assert "Additional context" not in clean_user_prompt

    whitespace_user_prompt = build_user_prompt(context="def f(): pass", file="clean.py", extra_context="   \n  ")
    assert "Additional context" not in whitespace_user_prompt

    clean_repair_prompt = build_repair_prompt(
        code="def f(): pass",
        finding=Finding(
            file="clean.py",
            line=1,
            category=Category.BUG,
            severity=Severity.LOW,
            confidence=0.8,
            description="Sample",
            actionable=True,
        ),
        extra_context=None,
    )
    assert "Related context:" not in clean_repair_prompt


# ---------------------------------------------------------------------------
# 4. context_level Returned in Result Dictionary
# ---------------------------------------------------------------------------

def test_context_level_returned_in_pipeline_result():
    """context_level is explicitly reflected in the result dictionary."""
    verifier = _AlwaysPassVerifier()

    # Case 1: Custom string "file"
    res_file = run_pipeline(
        code=DIV_ZERO_SNIPPET,
        file="snippet.py",
        verifier=verifier,
        context_level="file",
    )
    assert res_file["context_level"] == "file"

    # Case 2: Custom string "repo_imports"
    res_repo = run_pipeline(
        code=DIV_ZERO_SNIPPET,
        file="snippet.py",
        verifier=verifier,
        context_level="repo_imports",
    )
    assert res_repo["context_level"] == "repo_imports"

    # Case 3: None by default
    res_none = run_pipeline(
        code=DIV_ZERO_SNIPPET,
        file="snippet.py",
        verifier=verifier,
    )
    assert res_none["context_level"] is None

    # Case 4: _error_result helper also preserves context_level
    err_res = _error_result(file="error.py", error="Failure", context_level="global")
    assert err_res["context_level"] == "global"
    assert err_res["pipeline_errors"] == ["Failure"]
