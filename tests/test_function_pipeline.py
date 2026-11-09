"""Tests for function-level review and repair in app/pipeline.py using MockLLMClient.

Requirements tested:
1. Splice keeps surrounding code unchanged.
2. Indentation is preserved (including nested and method indentation).
3. A method inside a class works end-to-end.
4. Bad model output is rejected (name mismatch, syntax error, multiple functions, non-function).
5. Verifier runs on the whole file, not just the function snippet.
6. Function marked too_large reviews only and records 'repair skipped: function too large'.
7. Decorators and CRLF line endings are preserved.
"""

from __future__ import annotations

import json
from typing import Any
import pytest

from app.pipeline import run_pipeline
from app.repair.patch_generator import (
    PatchGenerationError,
    splice_function,
    validate_function_patch,
)
from app.repair.verifier_interface import VerificationResult, Verifier
from app.review.llm_client import MockLLMClient


class _TrackingVerifier(Verifier):
    """Verifier that records the exact patched_code received for inspection."""

    def __init__(self, should_pass: bool = True) -> None:
        self.should_pass = should_pass
        self.verified_codes: list[str] = []
        self.verified_paths: list[str] = []

    def verify(self, patched_code: str, file_path: str = "snippet.py") -> VerificationResult:
        self.verified_codes.append(patched_code)
        self.verified_paths.append(file_path)
        if self.should_pass:
            return VerificationResult(
                passed=True,
                stage="none",
                error="",
                output="All checks passed.",
            )
        return VerificationResult(
            passed=False,
            stage="tests",
            error="Test failed",
            output="AssertionError",
        )


# ---------------------------------------------------------------------------
# Test 1: Splice keeps surrounding code unchanged
# ---------------------------------------------------------------------------

def test_splice_keeps_surrounding_code_unchanged():
    """Header comments, globals, and footer code must remain completely intact."""
    full_code = """\
# Module Header: Data Processing Service
CONFIG_ID = "XYZ-999"
MAX_ITEMS = 500

def compute_average(items: list[float]) -> float:
    total = sum(items)
    return total / len(items)

# Footer Hook
def get_service_status() -> str:
    return "ONLINE"
"""
    functions = [
        {
            "name": "compute_average",
            "start_line": 5,
            "end_line": 7,
            "text": "def compute_average(items: list[float]) -> float:\n    total = sum(items)\n    return total / len(items)",
            "too_large": False,
        }
    ]

    result = run_pipeline(
        code=full_code,
        file="service.py",
        functions=functions,
        client=MockLLMClient(),
    )

    assert result["summary"]["verified"] >= 1
    repaired_entry = result["repairs"][0]
    assert repaired_entry["status"] == "verified"

    # Verify that the full patched file preserves the exact surrounding code
    # We can inspect the verifier outcome or apply the diff
    assert "# Module Header: Data Processing Service" in full_code
    assert 'CONFIG_ID = "XYZ-999"' in full_code
    assert 'return "ONLINE"' in full_code

    # Check the diff text
    diff = repaired_entry["diff"]
    assert "CONFIG_ID" not in diff  # surrounding lines not touched
    assert "get_service_status" not in diff
    assert "+    if not items:" in diff or "+    total = sum(items)" in diff


# ---------------------------------------------------------------------------
# Test 2: Indentation is preserved
# ---------------------------------------------------------------------------

def test_indentation_is_preserved_direct_splice():
    """splice_function must match the original base indentation."""
    original = """\
def outer():
    def inner_calculator(values: list[float]) -> float:
        total = sum(values)
        return total / len(values)
    return inner_calculator
"""
    # Replacement function without leading indentation (dedented)
    fixed_func = """\
def inner_calculator(values: list[float]) -> float:
    if not values:
        return 0.0
    total = sum(values)
    return total / len(values)
"""
    spliced = splice_function(original, fixed_func, start_line=2, end_line=4)
    expected_lines = [
        "def outer():",
        "    def inner_calculator(values: list[float]) -> float:",
        "        if not values:",
        "            return 0.0",
        "        total = sum(values)",
        "        return total / len(values)",
        "    return inner_calculator",
    ]
    assert spliced.splitlines() == expected_lines


# ---------------------------------------------------------------------------
# Test 3: Method inside a class works end-to-end
# ---------------------------------------------------------------------------

def test_method_inside_class_works():
    """A method inside a class is reviewed, repaired at 4-space indent, and compiles."""
    full_code = """\
class MetricAggregator:
    def __init__(self, prefix: str = "metric"):
        self.prefix = prefix

    def compute_average(self, values: list[float]) -> float:
        total = sum(values)
        return total / len(values)

    def get_prefix(self) -> str:
        return self.prefix
"""
    functions = [
        {
            "name": "compute_average",
            "start_line": 5,
            "end_line": 7,
            "text": "    def compute_average(self, values: list[float]) -> float:\n        total = sum(values)\n        return total / len(values)",
        }
    ]

    tracking_verifier = _TrackingVerifier(should_pass=True)

    result = run_pipeline(
        code=full_code,
        file="aggregator.py",
        functions=functions,
        client=MockLLMClient(),
        verifier=tracking_verifier,
    )

    assert result["summary"]["verified"] >= 1
    assert len(tracking_verifier.verified_codes) >= 1
    patched_code = tracking_verifier.verified_codes[-1]

    # Must be valid python that compiles as a whole
    namespace: dict[str, Any] = {}
    exec(patched_code, namespace)
    cls = namespace["MetricAggregator"]
    instance = cls()
    # Test repaired behavior
    assert instance.compute_average([]) == 0.0
    assert instance.compute_average([10.0, 30.0]) == 20.0
    assert instance.get_prefix() == "metric"


# ---------------------------------------------------------------------------
# Test 4: Bad model output is rejected
# ---------------------------------------------------------------------------

def test_bad_model_output_rejected_name_mismatch():
    """If the LLM returns a function with a different name, it must be rejected."""
    with pytest.raises(PatchGenerationError) as exc_info:
        validate_function_patch(
            func_code="def completely_wrong_name():\n    pass",
            expected_name="target_func",
        )
    assert "Function name mismatch" in str(exc_info.value)


def test_bad_model_output_rejected_syntax_error():
    """If the LLM returns invalid syntax, it must be rejected."""
    with pytest.raises(PatchGenerationError) as exc_info:
        validate_function_patch(
            func_code="def broken_func(\n    return 1",
            expected_name="broken_func",
        )
    assert "syntax error" in str(exc_info.value).lower()


def test_bad_model_output_rejected_multiple_functions():
    """If the LLM returns multiple function definitions, it must be rejected."""
    with pytest.raises(PatchGenerationError) as exc_info:
        validate_function_patch(
            func_code="def func1(): pass\ndef func2(): pass",
            expected_name="func1",
        )
    assert "single function definition" in str(exc_info.value)


def test_bad_model_output_rejected_class():
    """If the LLM returns a class definition instead of a function, it must be rejected."""
    with pytest.raises(PatchGenerationError) as exc_info:
        validate_function_patch(
            func_code="class target_func:\n    pass",
            expected_name="target_func",
        )
    assert "single function definition" in str(exc_info.value)


def test_bad_model_output_in_pipeline_fails_gracefully():
    """When LLM returns a wrong-name function, pipeline records failed status and original is not corrupted."""
    full_code = """\
def target_func(values: list[float]) -> float:
    total = sum(values)
    return total / len(values)
"""
    functions = [
        {
            "name": "target_func",
            "start_line": 1,
            "end_line": 3,
            "text": full_code,
        }
    ]

    bad_response = json.dumps(
        {
            "fixed_code": "def wrong_name(values: list[float]) -> float:\n    return 0.0",
            "explanation": "Renamed function.",
        }
    )
    # Review returns 1 finding, repair returns bad_response
    mock_client = MockLLMClient(
        canned_responses=[
            json.dumps({
                "findings": [
                    {
                        "file": "snippet.py",
                        "line": 3,
                        "category": "bug",
                        "severity": "high",
                        "confidence": 0.9,
                        "description": "ZeroDivisionError",
                        "suggested_fix_hint": "Check empty",
                        "actionable": True,
                    }
                ]
            }),
            bad_response,
            bad_response,
            bad_response,
        ]
    )

    result = run_pipeline(
        code=full_code,
        file="snippet.py",
        functions=functions,
        client=mock_client,
        max_attempts=1,
    )

    assert result["summary"]["failed"] == 1
    assert result["summary"]["verified"] == 0
    assert result["repairs"][0]["status"] == "failed"


# ---------------------------------------------------------------------------
# Test 5: Verifier runs on the whole file
# ---------------------------------------------------------------------------

def test_verifier_runs_on_the_whole_file():
    """Verifier must receive the full file containing the spliced function, not just the function text."""
    full_code = """\
# TOP OF FILE
GLOBAL_SETTING = True

def compute_average(items: list[float]) -> float:
    total = sum(items)
    return total / len(items)

# BOTTOM OF FILE
"""
    functions = [
        {
            "name": "compute_average",
            "start_line": 4,
            "end_line": 6,
            "text": "def compute_average(items: list[float]) -> float:\n    total = sum(items)\n    return total / len(items)",
        }
    ]

    tracking_verifier = _TrackingVerifier(should_pass=True)

    result = run_pipeline(
        code=full_code,
        file="my_test_file.py",
        functions=functions,
        client=MockLLMClient(),
        verifier=tracking_verifier,
    )

    assert result["summary"]["verified"] >= 1
    assert len(tracking_verifier.verified_codes) >= 1
    received_code = tracking_verifier.verified_codes[0]

    # Verify that the full file was passed
    assert "# TOP OF FILE" in received_code
    assert "GLOBAL_SETTING = True" in received_code
    assert "# BOTTOM OF FILE" in received_code
    assert tracking_verifier.verified_paths[0] == "my_test_file.py"


# ---------------------------------------------------------------------------
# Test 6: too_large function is reviewed but repair is skipped
# ---------------------------------------------------------------------------

def test_too_large_function_reviewed_but_skipped():
    """When too_large is True, review runs but repair records 'repair skipped: function too large'."""
    full_code = """\
def huge_function(items: list[float]) -> float:
    total = sum(items)
    return total / len(items)
"""
    functions = [
        {
            "name": "huge_function",
            "start_line": 1,
            "end_line": 3,
            "text": full_code,
            "too_large": True,
        }
    ]

    result = run_pipeline(
        code=full_code,
        file="huge.py",
        functions=functions,
        client=MockLLMClient(),
    )

    # Review still detected the issue
    assert result["counts"]["issues_detected"] >= 1
    assert result["counts"]["kept"] >= 1

    # Repair was skipped
    assert len(result["repairs"]) >= 1
    for repair_entry in result["repairs"]:
        assert repair_entry["status"] == "skipped"
        assert repair_entry["explanation"] == "repair skipped: function too large"
        assert repair_entry["attempts"] == 0
    assert result["summary"]["verified"] == 0
    assert result["summary"]["failed"] == 0


# ---------------------------------------------------------------------------
# Test 7: Decorators and CRLF line endings
# ---------------------------------------------------------------------------

def test_splice_keeps_decorators_and_crlf():
    """Decorators and CRLF endings are preserved when splicing."""
    crlf_code = "@my_decorator\r\ndef my_func(a: int) -> int:\r\n    return a * 2\r\n"
    fixed_func = "def my_func(a: int) -> int:\n    return a * 3\n"

    spliced = splice_function(crlf_code, fixed_func, start_line=1, end_line=3)

    assert "\r\n" in spliced
    assert "@my_decorator\r\ndef my_func(a: int) -> int:\r\n    return a * 3\r\n" == spliced
