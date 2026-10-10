"""Tests for the review module (schema, prompts, llm_client, and reviewer)."""

import pytest
from pydantic import ValidationError

from app.review.llm_client import (
    LLMClient,
    MockLLMClient,
    OpenAICompatLLMClient,
    get_client,
)
from app.review.prompts import SYSTEM_PROMPT, build_user_prompt
from app.review.reviewer import review
from app.review.schema import Category, Finding, ReviewResult, Severity


class FakeLLMClient(LLMClient):
    """A controllable fake LLM client for testing retry logic and responses."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.call_count = 0
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.call_count += 1
        self.calls.append((system, user))
        if self.responses:
            return self.responses.pop(0)
        return '{"findings": []}'


# --- Schema Tests ---

def test_finding_valid_creation():
    finding = Finding(
        file="app/main.py",
        line=10,
        category="bug",
        severity="high",
        confidence=0.9,
        description="Unhandled exception",
        suggested_fix_hint="Add try/except",
        actionable=True,
    )
    assert finding.file == "app/main.py"
    assert finding.line == 10
    assert finding.category == Category.BUG
    assert finding.severity == Severity.HIGH
    assert finding.confidence == 0.9
    assert finding.description == "Unhandled exception"
    assert finding.suggested_fix_hint == "Add try/except"
    assert finding.actionable is True


def test_finding_whitespace_stripped():
    finding = Finding(
        file="  module.py  ",
        line=5,
        category="security",
        severity="medium",
        confidence=0.8,
        description="  SQL injection flaw   ",
        suggested_fix_hint="  Use params  ",
    )
    assert finding.file == "module.py"
    assert finding.description == "SQL injection flaw"
    assert finding.suggested_fix_hint == "Use params"


def test_finding_confidence_clamping():
    # Clamps > 1.0 to 1.0
    f_high = Finding(
        file="m.py",
        line=1,
        category="logic",
        severity="low",
        confidence=1.75,
        description="Logic flaw",
    )
    assert f_high.confidence == 1.0

    # Clamps < 0.0 to 0.0
    f_low = Finding(
        file="m.py",
        line=1,
        category="logic",
        severity="low",
        confidence=-0.5,
        description="Logic flaw",
    )
    assert f_low.confidence == 0.0


def test_finding_empty_description_rejected():
    with pytest.raises(ValidationError):
        Finding(
            file="m.py",
            line=1,
            category="bug",
            severity="high",
            confidence=0.8,
            description="   ",
        )


def test_finding_line_ge_1_enforced():
    with pytest.raises(ValidationError):
        Finding(
            file="m.py",
            line=0,
            category="bug",
            severity="high",
            confidence=0.8,
            description="Bad line",
        )


# --- Prompts Tests ---

def test_build_user_prompt_adds_line_numbers():
    code = "def foo():\n    return 42"
    prompt = build_user_prompt(code, file="test.py", changed_lines={2})
    assert "File: test.py" in prompt
    assert "1: def foo():" in prompt
    assert "2:     return 42" in prompt
    assert "Changed lines in PR diff: 2" in prompt


# --- Reviewer Tests ---

def test_valid_json_parses():
    code = "def add(a, b):\n    return a + b"
    json_response = """{
      "findings": [
        {
          "file": "calc.py",
          "line": 2,
          "category": "bug",
          "severity": "high",
          "confidence": 0.95,
          "description": "Possible type error",
          "suggested_fix_hint": "Validate input types",
          "actionable": true
        }
      ]
    }"""
    client = FakeLLMClient([json_response])
    findings = review(code, file="calc.py", client=client)

    assert len(findings) == 1
    assert findings[0].file == "calc.py"
    assert findings[0].line == 2
    assert findings[0].category == Category.BUG
    assert findings[0].severity == Severity.HIGH
    assert findings[0].confidence == 0.95
    assert client.call_count == 1


def test_json_wrapped_in_markdown_fences_parses():
    code = "x = 1\ny = 2\n"
    fenced_response = """Here is your review:
```json
{
  "findings": [
    {
      "file": "snippet.py",
      "line": 1,
      "category": "performance",
      "severity": "low",
      "confidence": 0.7,
      "description": "Unused variable assignment",
      "suggested_fix_hint": "Remove unused variable",
      "actionable": true
    }
  ]
}
```
Let me know if you need more details!"""
    client = FakeLLMClient([fenced_response])
    findings = review(code, file="snippet.py", client=client)

    assert len(findings) == 1
    assert findings[0].line == 1
    assert findings[0].category == Category.PERFORMANCE
    assert client.call_count == 1


def test_invalid_json_triggers_exactly_one_retry():
    code = "x = 1\ny = 2\n"
    invalid_response = "I am not returning valid JSON at all."
    valid_retry_response = """{
      "findings": [
        {
          "file": "snippet.py",
          "line": 1,
          "category": "bug",
          "severity": "medium",
          "confidence": 0.85,
          "description": "Fixed after retry",
          "suggested_fix_hint": "Good fix",
          "actionable": true
        }
      ]
    }"""
    client = FakeLLMClient([invalid_response, valid_retry_response])
    findings = review(code, file="snippet.py", client=client)

    assert len(findings) == 1
    assert findings[0].description == "Fixed after retry"
    assert client.call_count == 2
    # Verify retry prompt includes failure notice
    retry_prompt = client.calls[1][1]
    assert "[RETRY NOTICE]" in retry_prompt


def test_persistent_garbage_returns_empty_list():
    code = "x = 1\ny = 2\n"
    client = FakeLLMClient(["Garbage response 1", "Garbage response 2"])
    findings = review(code, file="snippet.py", client=client)

    assert findings == []
    assert client.call_count == 2


def test_out_of_range_line_numbers_are_dropped():
    # Code has 3 lines (lines 1, 2, 3)
    code = "line1 = 1\nline2 = 2\nline3 = 3"
    response = """{
      "findings": [
        {
          "file": "test.py",
          "line": 1,
          "category": "bug",
          "severity": "high",
          "confidence": 0.9,
          "description": "Valid line 1",
          "suggested_fix_hint": "fix",
          "actionable": true
        },
        {
          "file": "test.py",
          "line": 3,
          "category": "logic",
          "severity": "medium",
          "confidence": 0.8,
          "description": "Valid line 3",
          "suggested_fix_hint": "fix",
          "actionable": true
        },
        {
          "file": "test.py",
          "line": 4,
          "category": "security",
          "severity": "high",
          "confidence": 0.95,
          "description": "Out of range line 4",
          "suggested_fix_hint": "fix",
          "actionable": true
        },
        {
          "file": "test.py",
          "line": 100,
          "category": "bug",
          "severity": "low",
          "confidence": 0.6,
          "description": "Out of range line 100",
          "suggested_fix_hint": "fix",
          "actionable": true
        }
      ]
    }"""
    client = FakeLLMClient([response])
    findings = review(code, file="test.py", client=client)

    assert len(findings) == 2
    assert [f.line for f in findings] == [1, 3]


# --- LLM Client Tests ---

def test_get_client_mock_default(monkeypatch):
    # Verify that get_client defaults to MockLLMClient when LLM_PROVIDER is unset in the environment
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    client = get_client()
    assert isinstance(client, MockLLMClient)

    # Verify that get_client returns MockLLMClient when LLM_PROVIDER is explicitly 'mock'
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    client_explicit = get_client()
    assert isinstance(client_explicit, MockLLMClient)


def test_openai_compat_missing_key_raises(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    client = OpenAICompatLLMClient(api_key="")
    with pytest.raises(ValueError, match="API key is missing"):
        client.complete("sys", "user")


def test_mock_client_detects_canned_bug():
    code = "def get_user(db, name):\n    query = f\"SELECT * FROM users WHERE name = '{name}'\"\n    return db.execute(query)"
    client = MockLLMClient()
    findings = review(code, file="users.py", client=client)

    assert len(findings) >= 1
    assert any(f.category == Category.SECURITY for f in findings)
    assert any("SQL" in f.description for f in findings)
