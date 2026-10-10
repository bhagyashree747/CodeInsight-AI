"""Unit tests for OpenAICompatLLMClient retry with exponential backoff."""

import time
import httpx
import pytest

from app.review.llm_client import OpenAICompatLLMClient


def test_openai_compat_retry_503_twice_then_succeeds(monkeypatch, capsys):
    """Test that a client encountering 503 twice retries and succeeds on attempt 3 without sleeping in real time."""
    call_count = 0
    sleep_calls: list[float] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return httpx.Response(503, text="Service Unavailable", request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"findings": []}'}}]},
            request=request,
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    monkeypatch.setattr(time, "sleep", lambda seconds: sleep_calls.append(seconds))

    client = OpenAICompatLLMClient(
        api_key="sk-test-super-secret-key-12345",
        http_client=mock_client,
    )

    result = client.complete(system="You are a reviewer", user="def foo(): pass")

    # Verify response content
    assert result == '{"findings": []}'
    # Total calls: initial attempt + 2 retries = 3 calls
    assert call_count == 3
    # Two backoff sleeps occurred
    assert len(sleep_calls) == 2
    # First backoff: 2.0s + jitter (0.1..0.5)
    assert 2.0 <= sleep_calls[0] <= 3.0
    # Second backoff: 4.0s + jitter (0.1..0.5)
    assert 4.0 <= sleep_calls[1] <= 5.0

    # Verify stdout retry message and ensure API key was NEVER leaked
    captured = capsys.readouterr()
    assert "[Retry 1/4] HTTP 503" in captured.out
    assert "[Retry 2/4] HTTP 503" in captured.out
    assert "sk-test-super-secret-key-12345" not in captured.out
    assert "sk-test-super-secret-key-12345" not in captured.err


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_openai_compat_permanent_errors_do_not_retry(status_code, monkeypatch, capsys):
    """Permanent HTTP error status codes (400, 401, 403, 404) must fail immediately without retry."""
    call_count = 0
    sleep_calls: list[float] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(status_code, text=f"Error {status_code}", request=request)

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    monkeypatch.setattr(time, "sleep", lambda seconds: sleep_calls.append(seconds))

    client = OpenAICompatLLMClient(
        api_key="secret-api-token-999",
        http_client=mock_client,
    )

    with pytest.raises(RuntimeError, match=f"HTTP {status_code}"):
        client.complete(system="sys", user="user")

    # Immediate failure: exactly 1 call and 0 retries/sleeps
    assert call_count == 1
    assert len(sleep_calls) == 0

    captured = capsys.readouterr()
    assert "secret-api-token-999" not in captured.out
    assert "secret-api-token-999" not in captured.err


def test_openai_compat_retryable_exhaustion(monkeypatch, capsys):
    """Retryable status codes retry up to 4 times and raise RuntimeError upon exhaustion."""
    call_count = 0
    sleep_calls: list[float] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, text="Internal Server Error", request=request)

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    monkeypatch.setattr(time, "sleep", lambda seconds: sleep_calls.append(seconds))

    client = OpenAICompatLLMClient(
        api_key="test-api-key",
        http_client=mock_client,
    )

    with pytest.raises(RuntimeError, match="HTTP 500 after 4 retries"):
        client.complete(system="sys", user="user")

    # 1 initial try + 4 retries = 5 attempts
    assert call_count == 5
    # 4 backoff delays: 2, 4, 8, 16 (+ jitter)
    assert len(sleep_calls) == 4
    assert 2.0 <= sleep_calls[0] <= 3.0
    assert 4.0 <= sleep_calls[1] <= 5.0
    assert 8.0 <= sleep_calls[2] <= 9.0
    assert 16.0 <= sleep_calls[3] <= 17.0

    captured = capsys.readouterr()
    assert "[Retry 1/4] HTTP 500" in captured.out
    assert "[Retry 2/4] HTTP 500" in captured.out
    assert "[Retry 3/4] HTTP 500" in captured.out
    assert "[Retry 4/4] HTTP 500" in captured.out


def test_openai_compat_network_timeout_retry_and_recovery(monkeypatch, capsys):
    """Network timeouts (httpx.TimeoutException) should be retried with backoff."""
    call_count = 0
    sleep_calls: list[float] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadTimeout("Request timed out", request=request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=request,
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    monkeypatch.setattr(time, "sleep", lambda seconds: sleep_calls.append(seconds))

    client = OpenAICompatLLMClient(
        api_key="test-api-key",
        http_client=mock_client,
    )

    result = client.complete(system="sys", user="user")
    assert result == "ok"
    assert call_count == 2
    assert len(sleep_calls) == 1
    assert 2.0 <= sleep_calls[0] <= 3.0

    captured = capsys.readouterr()
    assert "[Retry 1/4] Request timed out" in captured.out


def test_openai_compat_timeout_exhaustion(monkeypatch):
    """Persistent network timeouts should retry 4 times and raise RuntimeError."""
    call_count = 0
    sleep_calls: list[float] = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectTimeout("Connection timed out", request=request)

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    monkeypatch.setattr(time, "sleep", lambda seconds: sleep_calls.append(seconds))

    client = OpenAICompatLLMClient(
        api_key="test-api-key",
        http_client=mock_client,
    )

    with pytest.raises(RuntimeError, match="timed out after 4 retries"):
        client.complete(system="sys", user="user")

    assert call_count == 5
    assert len(sleep_calls) == 4


def test_openai_compat_sanitizes_api_key_in_error_payload():
    """Ensure error messages and responses echoing the API key are sanitized."""
    raw_secret = "super-secret-password-key"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            text=f"Unauthorized: provided token {raw_secret} is invalid.",
            request=request,
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))

    client = OpenAICompatLLMClient(
        api_key=raw_secret,
        http_client=mock_client,
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.complete(system="sys", user="user")

    error_msg = str(exc_info.value)
    assert raw_secret not in error_msg
    assert "***" in error_msg
