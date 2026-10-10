"""Pytest configuration and test isolation fixtures."""

import pytest


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch):
    """Ensure tests run completely isolated and offline without loading real .env files or hitting APIs."""
    # Prevent python-dotenv from loading any local .env file
    try:
        import dotenv
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
        import dotenv.main
        monkeypatch.setattr(dotenv.main, "load_dotenv", lambda *args, **kwargs: False)
    except ImportError:
        pass

    # Default provider for all tests is 'mock'
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    # Clear any API secrets or external endpoint URLs so tests remain strictly offline
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
