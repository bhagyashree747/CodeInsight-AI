"""Tests for app/pipeline.py using the mock provider (conftest enforces isolation)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.pipeline import run_pipeline, _error_result
from app.review.llm_client import MockLLMClient
from app.repair.verifier_interface import VerificationResult
from app.review.schema import Finding, Category, Severity


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

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

MUTABLE_DEFAULT_SNIPPET = """\
def append_item(item: str, collection: list[str] = []) -> list[str]:
    collection.append(item)
    return collection
"""


class _AlwaysPassVerifier:
    """Verifier that always reports passed at 'syntax' stage."""

    def verify(self, patched_code: str, file_path: str) -> VerificationResult:
        return VerificationResult(passed=True, stage="syntax", error="", output="")


class _AlwaysFailVerifier:
    """Verifier that always reports failure at 'syntax' stage."""

    def verify(self, patched_code: str, file_path: str) -> VerificationResult:
        return VerificationResult(
            passed=False, stage="syntax", error="SyntaxError: bad code", output=""
        )


# ---------------------------------------------------------------------------
# Basic structure tests
# ---------------------------------------------------------------------------

def test_result_has_required_keys():
    """run_pipeline must return a dict with all documented top-level keys."""
    result = run_pipeline(code=SQL_SNIPPET, file="db_query.py", client=MockLLMClient())
    for key in ("file", "counts", "findings", "discarded", "repairs", "summary"):
        assert key in result, f"Missing key: {key}"


def test_result_is_json_serialisable():
    """The pipeline result must serialise to JSON without error."""
    result = run_pipeline(code=SQL_SNIPPET, file="db_query.py", client=MockLLMClient())
    # Should not raise
    dumped = json.dumps(result)
    assert isinstance(dumped, str)


def test_counts_structure():
    """counts dict must have expected sub-keys."""
    result = run_pipeline(code=SQL_SNIPPET, file="db_query.py", client=MockLLMClient())
    counts = result["counts"]
    for key in ("issues_detected", "kept", "filtered_as_noise", "by_severity"):
        assert key in counts, f"Missing counts key: {key}"


def test_summary_structure():
    """summary dict must have verified, failed, retried keys."""
    result = run_pipeline(code=SQL_SNIPPET, file="db_query.py", client=MockLLMClient())
    summary = result["summary"]
    for key in ("verified", "failed", "retried"):
        assert key in summary, f"Missing summary key: {key}"


def test_findings_have_score():
    """Each kept finding in results['findings'] must include a 'score' field."""
    result = run_pipeline(code=SQL_SNIPPET, file="db_query.py", client=MockLLMClient())
    for finding in result["findings"]:
        assert "score" in finding, "Finding missing 'score'"
        assert 0.0 <= finding["score"] <= 1.0


def test_discarded_have_reason():
    """Each discarded finding must include a 'reason' field."""
    result = run_pipeline(code=SQL_SNIPPET, file="db_query.py", client=MockLLMClient())
    for disc in result["discarded"]:
        assert "reason" in disc, "Discarded finding missing 'reason'"
        assert isinstance(disc["reason"], str) and disc["reason"]


def test_repairs_structure():
    """Each repair entry must have the documented fields."""
    result = run_pipeline(
        code=SQL_SNIPPET,
        file="db_query.py",
        client=MockLLMClient(),
        verifier=_AlwaysPassVerifier(),
    )
    for rep in result["repairs"]:
        for key in ("finding", "status", "attempts", "diff", "explanation", "verification_stage"):
            assert key in rep, f"Repair entry missing key: {key}"
        assert rep["status"] in ("verified", "failed")
        assert isinstance(rep["attempts"], int) and rep["attempts"] >= 1


# ---------------------------------------------------------------------------
# Mock provider functional tests
# ---------------------------------------------------------------------------

def test_sql_injection_detected_and_repaired():
    """SQL injection snippet must be detected, kept, and verified with mock client."""
    result = run_pipeline(
        code=SQL_SNIPPET,
        file="db_query.py",
        client=MockLLMClient(),
        verifier=_AlwaysPassVerifier(),
    )
    assert result["counts"]["issues_detected"] > 0
    assert result["counts"]["kept"] > 0
    # At least one repair should be verified
    assert result["summary"]["verified"] >= 1


def test_div_zero_detected():
    """Division-by-zero snippet must yield at least one finding."""
    result = run_pipeline(
        code=DIV_ZERO_SNIPPET,
        file="statistics.py",
        client=MockLLMClient(),
        verifier=_AlwaysPassVerifier(),
    )
    assert result["counts"]["issues_detected"] > 0


def test_mutable_default_detected():
    """Mutable default argument snippet must yield at least one finding."""
    result = run_pipeline(
        code=MUTABLE_DEFAULT_SNIPPET,
        file="utils.py",
        client=MockLLMClient(),
        verifier=_AlwaysPassVerifier(),
    )
    assert result["counts"]["issues_detected"] > 0


def test_always_fail_verifier_leads_to_failed_status():
    """When every verification fails, all repairs must have status 'failed'."""
    result = run_pipeline(
        code=SQL_SNIPPET,
        file="db_query.py",
        client=MockLLMClient(),
        verifier=_AlwaysFailVerifier(),
        max_attempts=1,
    )
    for rep in result["repairs"]:
        assert rep["status"] == "failed"
    if result["repairs"]:
        assert result["summary"]["failed"] == len(result["repairs"])


def test_retried_count_gt_zero_when_multi_attempt():
    """When max_attempts > 1 and verifier always fails, retried count reflects it."""
    result = run_pipeline(
        code=SQL_SNIPPET,
        file="db_query.py",
        client=MockLLMClient(),
        verifier=_AlwaysFailVerifier(),
        max_attempts=2,
    )
    if result["repairs"]:
        # All repairs took 2 attempts → retried > 0
        assert result["summary"]["retried"] >= 1


# ---------------------------------------------------------------------------
# Resilience / error-capture tests
# ---------------------------------------------------------------------------

def test_pipeline_survives_crashing_client():
    """If the LLM client raises on every call, pipeline must return gracefully."""

    class _BombClient:
        def complete(self, system: str, user: str) -> str:
            raise RuntimeError("simulated network failure")

    result = run_pipeline(code=SQL_SNIPPET, file="db_query.py", client=_BombClient())
    # Should not raise — reviewer.py swallows errors and returns []
    assert result["counts"]["issues_detected"] == 0
    assert result["findings"] == []
    assert result["repairs"] == []


def test_pipeline_with_empty_code():
    """Passing an empty string must not crash and should return zero findings."""
    result = run_pipeline(code="", file="empty.py", client=MockLLMClient())
    # No valid findings on an empty file
    assert isinstance(result, dict)
    assert result["counts"]["issues_detected"] == 0


def test_pipeline_no_findings_means_no_repairs():
    """A snippet with no detectable issues must have an empty repairs list."""

    class _NoFindingsClient:
        def complete(self, system: str, user: str) -> str:
            return '{"findings": []}'

    result = run_pipeline(code="x = 1\n", file="clean.py", client=_NoFindingsClient())
    assert result["repairs"] == []
    assert result["summary"]["verified"] == 0
    assert result["summary"]["failed"] == 0


def test_error_result_helper():
    """_error_result must return a well-formed, JSON-serialisable dict."""
    result = _error_result("foo.py", "Some catastrophic error")
    assert result["file"] == "foo.py"
    assert "pipeline_errors" in result
    assert result["pipeline_errors"][0] == "Some catastrophic error"
    # Must be JSON-serialisable
    json.dumps(result)


# ---------------------------------------------------------------------------
# File name propagation
# ---------------------------------------------------------------------------

def test_file_name_in_result():
    """result['file'] must match the supplied file argument."""
    result = run_pipeline(code=SQL_SNIPPET, file="my_module.py", client=MockLLMClient())
    assert result["file"] == "my_module.py"


# ---------------------------------------------------------------------------
# changed_lines filtering
# ---------------------------------------------------------------------------

def test_changed_lines_filters_out_of_range_findings():
    """When changed_lines excludes all finding lines, kept count must be 0."""
    # Line 999 is not in the short SQL snippet → all findings should be filtered
    result = run_pipeline(
        code=SQL_SNIPPET,
        file="db_query.py",
        changed_lines={999},
        client=MockLLMClient(),
    )
    # The relevance filter should discard everything
    assert result["counts"]["kept"] == 0
    assert result["repairs"] == []


def test_changed_lines_none_keeps_all_valid_findings():
    """With changed_lines=None, the filter should not drop findings for being off-diff."""
    result_no_filter = run_pipeline(
        code=SQL_SNIPPET,
        file="db_query.py",
        changed_lines=None,
        client=MockLLMClient(),
    )
    result_with_filter = run_pipeline(
        code=SQL_SNIPPET,
        file="db_query.py",
        changed_lines={999},
        client=MockLLMClient(),
    )
    assert result_no_filter["counts"]["kept"] >= result_with_filter["counts"]["kept"]
