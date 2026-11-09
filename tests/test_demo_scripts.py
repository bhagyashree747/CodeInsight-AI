"""Unit tests verifying demo scripts behavior with mock and real providers."""

import httpx
import pytest

from app.review.llm_client import OpenAICompatLLMClient
import run_demo_patch
import run_demo_repair


def test_run_demo_repair_mock_mode_scripted_failures(monkeypatch, capsys):
    """When provider is unset or 'mock', run_demo_repair should execute scripted-failure scenarios."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    run_demo_repair.main()

    captured = capsys.readouterr().out
    assert "Active LLM Provider: mock" in captured
    assert "SCENARIO 1: SQL INJECTION (IMMEDIATE VERIFICATION)" in captured
    assert "SCENARIO 2: DIVISION BY ZERO (SYNTAX SELF-HEALING LOOP)" in captured
    assert "SCENARIO 3: MUTABLE DEFAULT (REGRESSION TEST FAILURE EXHAUSTED)" in captured
    assert "Fix #1 verified" in captured
    assert "Fix #2 2 attempts -> verified" in captured
    assert "Fix #3 failed" in captured
    assert "PER-FIX STATUS REPORT" in captured


def test_run_demo_repair_real_provider_pipeline(monkeypatch, capsys):
    """When a real provider is active, run_demo_repair runs the real pipeline without scripted test failure."""
    monkeypatch.setenv("LLM_PROVIDER", "openai_compat")
    monkeypatch.setenv("LLM_API_KEY", "test-key-12345")

    # Mock responses for the 3 snippets:
    # Snippet 1: SQL Injection
    review_json_1 = '{"findings": [{"file": "app/db/users.py", "line": 3, "category": "security", "severity": "high", "confidence": 0.95, "description": "SQL injection", "suggested_fix_hint": "parameterize", "actionable": true}]}'
    repair_json_1 = '{"fixed_code": "def fetch_user_record(cursor, username: str):\\n    query = \\"SELECT * FROM users WHERE username = %s\\"\\n    cursor.execute(query, (username,))\\n    return cursor.fetchone()\\n", "explanation": "Parameterized query"}'

    # Snippet 2: Division by zero
    review_json_2 = '{"findings": [{"file": "app/metrics/latency.py", "line": 4, "category": "bug", "severity": "high", "confidence": 0.95, "description": "Div zero", "suggested_fix_hint": "guard", "actionable": true}]}'
    repair_json_2 = '{"fixed_code": "def compute_average_latency(measurements: list[float]) -> float:\\n    if not measurements:\\n        return 0.0\\n    total = sum(measurements)\\n    return total / len(measurements)\\n", "explanation": "Guarded empty list"}'

    # Snippet 3: Mutable default
    review_json_3 = '{"findings": [{"file": "app/events/logger.py", "line": 1, "category": "bug", "severity": "medium", "confidence": 0.95, "description": "Mutable default", "suggested_fix_hint": "use None", "actionable": true}]}'
    repair_json_3 = '{"fixed_code": "def register_event(event_name: str, tags: list = None):\\n    if tags is None:\\n        tags = []\\n    tags.append(event_name)\\n    return tags\\n", "explanation": "Safe default"}'

    responses = [
        review_json_1,
        repair_json_1,
        review_json_2,
        repair_json_2,
        review_json_3,
        repair_json_3,
    ]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        content = responses.pop(0) if responses else '{"findings": []}'
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
            request=request,
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    openai_client = OpenAICompatLLMClient(
        api_key="test-key-12345",
        http_client=mock_client,
    )
    monkeypatch.setattr(run_demo_repair, "get_client", lambda *args, **kwargs: openai_client)

    run_demo_repair.main()

    captured = capsys.readouterr().out
    assert "Active LLM Provider: openai_compat" in captured
    assert "REAL PROVIDER PIPELINE" in captured
    assert "Fix #1 verified (1 attempt)" in captured
    assert "Fix #2 verified (1 attempt)" in captured
    assert "Fix #3 verified (1 attempt)" in captured
    assert "REPAIR DEMO COMPLETE - ALL CASES EXECUTED SUCCESSFULLY" in captured


def test_run_demo_patch_respects_provider(monkeypatch, capsys):
    """run_demo_patch respects configured provider and executes patch workflow."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    run_demo_patch.main()

    captured = capsys.readouterr().out
    assert "Active LLM Provider: mock" in captured
    assert "PATCH DEMO COMPLETE" in captured
