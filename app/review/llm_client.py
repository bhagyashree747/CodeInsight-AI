"""Provider-agnostic LLM client interface and implementations."""

from abc import ABC, abstractmethod
import logging
import os
import re
from typing import Any
import httpx

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Send a prompt with system and user messages and return the LLM response text."""
        pass


class MockLLMClient(LLMClient):
    """Mock LLM client returning realistic canned JSON findings without network access."""

    def __init__(
        self,
        canned_responses: list[str] | None = None,
        default_response: str | None = None,
    ) -> None:
        self.canned_responses = list(canned_responses) if canned_responses else []
        self.default_response = default_response
        self.call_count = 0

    def complete(self, system: str, user: str) -> str:
        self.call_count += 1
        logger.debug("MockLLMClient called (call #%d)", self.call_count)

        if self.canned_responses:
            return self.canned_responses.pop(0)

        if self.default_response is not None:
            return self.default_response

        # Realistic canned response generation based on the code in the prompt
        return self._generate_realistic_response(user)

    def _generate_realistic_response(self, user_prompt: str) -> str:
        """Inspect the user prompt to detect known buggy patterns and return realistic findings."""
        # Extract filename if available
        file_match = re.search(r"File:\s*([^\r\n]+)", user_prompt)
        filename = file_match.group(1).strip() if file_match else "snippet.py"

        # Check for SQL injection pattern
        sql_match = re.search(
            r"(\d+):\s*.*?(SELECT|INSERT|UPDATE|DELETE|query\s*=\s*f?[\"'].*?\{|\bcursor\.execute\()",
            user_prompt,
            re.IGNORECASE,
        )
        if "select" in user_prompt.lower() and ("%" in user_prompt or "{" in user_prompt or "+" in user_prompt):
            line_no = int(sql_match.group(1)) if sql_match else 3
            return f"""{{
  "findings": [
    {{
      "file": "{filename}",
      "line": {line_no},
      "category": "security",
      "severity": "high",
      "confidence": 0.95,
      "description": "SQL injection vulnerability: SQL query is dynamically constructed with unsanitized user inputs.",
      "suggested_fix_hint": "Use parameterized queries with placeholders instead of string interpolation.",
      "actionable": true
    }},
    {{
      "file": "{filename}",
      "line": 1,
      "category": "logic",
      "severity": "low",
      "confidence": 0.65,
      "description": "Variable naming style and docstring formatting preference.",
      "suggested_fix_hint": "Refactor names to conform to team style conventions.",
      "actionable": true
    }}
  ]
}}"""

        # Check for division by zero pattern
        div_match = re.search(r"(\d+):\s*.*?/\s*len\(", user_prompt)
        if div_match or ("len(" in user_prompt and "/" in user_prompt):
            line_no = int(div_match.group(1)) if div_match else 3
            return f"""{{
  "findings": [
    {{
      "file": "{filename}",
      "line": {line_no},
      "category": "bug",
      "severity": "high",
      "confidence": 0.92,
      "description": "Potential ZeroDivisionError: calculation divides by len(...) without verifying the collection is non-empty.",
      "suggested_fix_hint": "Guard against empty collection before division: if not items: return 0.0",
      "actionable": true
    }},
    {{
      "file": "{filename}",
      "line": 1,
      "category": "logic",
      "severity": "low",
      "confidence": 0.70,
      "description": "Precondition check observation on upstream input arguments.",
      "suggested_fix_hint": "Add caller-side validation.",
      "actionable": true
    }}
  ]
}}"""

        # Check for mutable default argument pattern
        def_match = re.search(r"(\d+):\s*def\s+\w+\([^)]*=\s*(\[\]|\{\}|set\(\))", user_prompt)
        if def_match or "= []" in user_prompt or "=[]" in user_prompt:
            line_no = int(def_match.group(1)) if def_match else 1
            return f"""{{
  "findings": [
    {{
      "file": "{filename}",
      "line": {line_no},
      "category": "bug",
      "severity": "medium",
      "confidence": 0.88,
      "description": "Mutable default argument in function signature retains mutated state across repeated calls.",
      "suggested_fix_hint": "Use None as default parameter value and initialize the collection inside the function body.",
      "actionable": true
    }},
    {{
      "file": "{filename}",
      "line": {line_no},
      "category": "bug",
      "severity": "medium",
      "confidence": 0.88,
      "description": "Duplicate detection: mutable default argument retains mutated state.",
      "suggested_fix_hint": "Use None as default parameter value.",
      "actionable": true
    }}
  ]
}}"""

        # Default clean or unrecognized code
        return '{"findings": []}'


class OpenAICompatLLMClient(LLMClient):
    """LLM client for any OpenAI-compatible HTTP API using httpx."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")).strip()
        self.api_key = (api_key or os.getenv("LLM_API_KEY", "")).strip()
        self.model = (model or os.getenv("LLM_MODEL", "gemini-2.5-flash")).strip()

        env_timeout = os.getenv("LLM_TIMEOUT")
        if timeout is not None:
            self.timeout = timeout
        elif env_timeout:
            try:
                self.timeout = float(env_timeout)
            except ValueError:
                self.timeout = 30.0
        else:
            self.timeout = 30.0

    def _resolve_endpoint(self) -> str:
        clean_url = self.base_url.rstrip("/")
        if clean_url.endswith("/chat/completions"):
            return clean_url
        return f"{clean_url}/chat/completions"

    def complete(self, system: str, user: str) -> str:
        if not self.api_key:
            raise ValueError(
                "API key is missing for openai_compat LLM provider. "
                "Set the LLM_API_KEY environment variable or pass api_key to the client."
            )

        endpoint = self._resolve_endpoint()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
        }

        # Safe logging without leaking secrets or full keys
        masked_key = f"{self.api_key[:4]}...{self.api_key[-4:]}" if len(self.api_key) > 8 else "***"
        logger.info(
            "Calling OpenAI-compatible endpoint %s (model: %s, auth: %s)",
            endpoint,
            self.model,
            masked_key,
        )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    content = str(content)
                return content
        except httpx.HTTPStatusError as err:
            status_code = err.response.status_code
            # Sanitize error message to avoid echoing headers or tokens
            error_text = err.response.text
            logger.error("HTTP error %s from LLM endpoint %s", status_code, endpoint)
            raise RuntimeError(
                f"LLM API request failed with HTTP {status_code}: {error_text}"
            ) from None
        except httpx.RequestError as err:
            logger.error("Network error when connecting to LLM endpoint %s: %s", endpoint, err)
            raise RuntimeError(f"LLM network error: {err}") from None


class OllamaLLMClient(LLMClient):
    """LLM client using local Ollama instance, imported lazily."""

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.model = (model or os.getenv("LLM_MODEL", "qwen2.5-coder:7b")).strip()
        self.host = (host or os.getenv("LLM_BASE_URL", "")).strip() or None
        self.timeout = timeout

    def complete(self, system: str, user: str) -> str:
        try:
            import ollama  # type: ignore[import-untyped]
        except ImportError as err:
            raise ImportError(
                "The 'ollama' package is required for the ollama provider but is not installed. "
                "Install it with 'pip install ollama' or switch to LLM_PROVIDER=mock or openai_compat."
            ) from err

        logger.info("Calling Ollama (model: %s, host: %s)", self.model, self.host or "default")
        try:
            client = ollama.Client(host=self.host, timeout=self.timeout) if self.host else ollama
            response = client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return response["message"]["content"]
        except Exception as err:
            logger.error("Error communicating with Ollama: %s", err)
            raise RuntimeError(f"Ollama request failed: {err}") from err


def get_client(provider: str | None = None) -> LLMClient:
    """Factory creating an LLMClient instance based on environment variables or explicit provider."""
    # Attempt to load .env file if python-dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    selected_provider = (provider or os.getenv("LLM_PROVIDER", "mock")).strip().lower()

    if selected_provider == "mock":
        return MockLLMClient()
    elif selected_provider in ("openai_compat", "openai"):
        return OpenAICompatLLMClient()
    elif selected_provider == "ollama":
        return OllamaLLMClient()
    else:
        raise ValueError(
            f"Unknown LLM provider '{selected_provider}'. Valid options: 'mock', 'openai_compat', 'ollama'."
        )
