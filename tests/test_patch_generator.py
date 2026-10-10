"""Tests for the repair module and patch generator."""

import json
from pathlib import Path
import pytest

from app.repair.patch_generator import (
    PatchGenerationError,
    apply_patch,
    generate_patch,
)
from app.repair.prompts import build_repair_prompt
from app.repair.schema import Patch
from app.review.llm_client import LLMClient, MockLLMClient
from app.review.schema import Category, Finding, Severity


class FakeLLMClient(LLMClient):
    """Controllable fake LLM client for testing retry and error handling."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.call_count = 0
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.call_count += 1
        self.calls.append((system, user))
        if self.responses:
            return self.responses.pop(0)
        return json.dumps({"fixed_code": "# Default\n", "explanation": "Default explanation"})


# --- Test fixtures and snippets ---

SQL_SNIPPET = '''def fetch_user_record(cursor, username: str):
    # Query constructed via direct string interpolation (vulnerable to SQLi)
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()
'''

DIV_ZERO_SNIPPET = '''def compute_average_latency(measurements: list[float]) -> float:
    # Unchecked division by collection length
    total = sum(measurements)
    return total / len(measurements)
'''

MUTABLE_DEFAULT_SNIPPET = '''def register_event(event_name: str, tags: list = []):
    # Mutable default argument retains state across multiple function calls
    tags.append(event_name)
    return tags
'''


def make_finding(
    file: str = "snippet.py",
    line: int = 1,
    category: str = "bug",
    severity: str = "high",
    description: str = "Defect description",
    suggested_fix_hint: str = "Fix hint",
) -> Finding:
    return Finding(
        file=file,
        line=line,
        category=category,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        confidence=0.9,
        description=description,
        suggested_fix_hint=suggested_fix_hint,
        actionable=True,
    )


# --- Tests for Valid Patch Generation for 3 Cases ---

def test_valid_patch_produced_sql_injection():
    finding = make_finding(
        file="app/db/users.py",
        line=3,
        category="security",
        severity="high",
        description="SQL injection vulnerability with unescaped user parameter",
        suggested_fix_hint="Use parameterized queries with placeholder",
    )
    patch = generate_patch(SQL_SNIPPET, finding)

    assert isinstance(patch, Patch)
    assert patch.fixed_code != SQL_SNIPPET
    assert "%s" in patch.fixed_code
    assert "(username,)" in patch.fixed_code
    assert len(patch.diff.strip()) > 0
    assert "--- a/app/db/users.py" in patch.diff
    assert "+++ b/app/db/users.py" in patch.diff
    assert patch.explanation != ""
    assert patch.attempt == 1


def test_valid_patch_produced_division_by_zero():
    finding = make_finding(
        file="app/metrics/latency.py",
        line=4,
        category="bug",
        severity="high",
        description="ZeroDivisionError when measurements is empty",
        suggested_fix_hint="Check if measurements is empty before division",
    )
    patch = generate_patch(DIV_ZERO_SNIPPET, finding, failure_feedback="Fix syntax")

    assert isinstance(patch, Patch)
    assert patch.fixed_code != DIV_ZERO_SNIPPET
    assert "if not measurements:" in patch.fixed_code
    assert "return 0.0" in patch.fixed_code
    assert len(patch.diff.strip()) > 0
    assert "--- a/app/metrics/latency.py" in patch.diff
    assert "+++ b/app/metrics/latency.py" in patch.diff
    assert patch.explanation != ""


def test_valid_patch_produced_mutable_default():
    finding = make_finding(
        file="app/events/logger.py",
        line=1,
        category="bug",
        severity="medium",
        description="Mutable default argument retains state across calls",
        suggested_fix_hint="Default to None and create list inside body",
    )
    patch = generate_patch(MUTABLE_DEFAULT_SNIPPET, finding)

    assert isinstance(patch, Patch)
    assert patch.fixed_code != MUTABLE_DEFAULT_SNIPPET
    assert "tags: list | None = None" in patch.fixed_code or "None" in patch.fixed_code
    assert "if tags is None:" in patch.fixed_code
    assert len(patch.diff.strip()) > 0
    assert "--- a/app/events/logger.py" in patch.diff
    assert "+++ b/app/events/logger.py" in patch.diff
    assert patch.explanation != ""


def test_diff_is_non_empty_and_valid_unified_format():
    finding = make_finding(file="test.py", line=3)
    patch = generate_patch(SQL_SNIPPET, finding)

    assert patch.diff != ""
    assert "@@" in patch.diff
    assert any(line.startswith("+") for line in patch.diff.splitlines())
    assert any(line.startswith("-") for line in patch.diff.splitlines())


# --- Test apply_patch Never Modifies Original File ---

def test_apply_patch_leaves_original_file_unchanged(tmp_path: Path):
    orig_file = tmp_path / "service.py"
    orig_file.write_text(SQL_SNIPPET, encoding="utf-8")
    content_before = orig_file.read_text(encoding="utf-8")

    finding = make_finding(file="service.py", line=3)
    patch = generate_patch(SQL_SNIPPET, finding)

    result = apply_patch(patch, str(orig_file), work_dir=str(tmp_path / "temp"))

    assert result.success is True
    assert result.error is None
    assert result.patched_path is not None
    assert Path(result.patched_path).exists()
    assert Path(result.patched_path).read_text(encoding="utf-8") == patch.fixed_code

    # CRUCIAL ASSERTION: Original file content must be 100% identical
    content_after = orig_file.read_text(encoding="utf-8")
    assert content_after == content_before


# --- Test Invalid JSON Retries Once ---

def test_invalid_json_retries_once():
    finding = make_finding(line=1)
    invalid_json = "I am not JSON at all."
    valid_json = json.dumps({
        "fixed_code": "def fixed():\n    return 42\n",
        "explanation": "Fixed after retry.",
    })

    client = FakeLLMClient(responses=[invalid_json, valid_json])
    patch = generate_patch(SQL_SNIPPET, finding, client=client)

    assert client.call_count == 2
    assert "[RETRY NOTICE]" in client.calls[1][1]
    assert patch.fixed_code == "def fixed():\n    return 42\n"
    assert patch.explanation == "Fixed after retry."


def test_persistent_invalid_json_raises_patch_generation_error():
    finding = make_finding(line=1)
    client = FakeLLMClient(responses=["garbage 1", "garbage 2"])

    with pytest.raises(PatchGenerationError, match="Failed to generate valid patch JSON"):
        generate_patch(SQL_SNIPPET, finding, client=client)

    assert client.call_count == 2


# --- Test Identical or Empty Output Raises PatchGenerationError ---

def test_identical_output_raises_patch_generation_error():
    finding = make_finding(line=1)
    client = FakeLLMClient(responses=[
        json.dumps({
            "fixed_code": SQL_SNIPPET,
            "explanation": "No changes made",
        })
    ])

    with pytest.raises(PatchGenerationError, match="identical"):
        generate_patch(SQL_SNIPPET, finding, client=client)


def test_empty_output_raises_patch_generation_error():
    finding = make_finding(line=1)
    client = FakeLLMClient(responses=[
        json.dumps({
            "fixed_code": "   \n\t  ",
            "explanation": "Empty output",
        })
    ])

    with pytest.raises(PatchGenerationError, match="empty"):
        generate_patch(SQL_SNIPPET, finding, client=client)


# --- Test Retry Feedback and Prompt Construction ---

def test_build_repair_prompt_includes_previous_failure_and_instruction():
    finding = make_finding(line=2, category="bug", description="Bad division")
    prev_patch = Patch(
        finding=finding,
        original_code=DIV_ZERO_SNIPPET,
        fixed_code="def broken(): return 0",
        explanation="Attempt 1",
        diff="--- a\n+++ b",
        attempt=1,
    )
    feedback = "ZeroDivisionError: division by zero in unit tests"

    prompt = build_repair_prompt(
        code=DIV_ZERO_SNIPPET,
        finding=finding,
        previous_patch=prev_patch,
        failure_feedback=feedback,
    )

    assert "Your last fix failed, correct it." in prompt
    assert "Previous failed fixed code:" in prompt
    assert "def broken(): return 0" in prompt
    assert feedback in prompt
