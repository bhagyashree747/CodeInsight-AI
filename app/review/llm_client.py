"""Provider-agnostic LLM client interface and implementations."""

from abc import ABC, abstractmethod
import json
import logging
import os
import random
import re
import time
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

        # Check if this is a repair prompt (contains "fixing ONE issue")
        if "fixing ONE issue" in system or "fixing ONE issue" in user:
            return self._generate_realistic_repair(user)

        # Realistic canned response generation based on the code in the prompt
        return self._generate_realistic_response(user)

    def _generate_realistic_repair(self, user_prompt: str) -> str:
        """Inspect the repair user prompt and return realistic fixed code and explanation."""
        # 1. SQL Injection Case (parameterized query)
        if (
            "sql" in user_prompt.lower()
            or "injection" in user_prompt.lower()
            or "select" in user_prompt.lower()
        ):
            if "fetch_user_record" in user_prompt:
                fixed_code = '''def fetch_user_record(cursor, username: str):
    # Parameterized query to prevent SQL injection
    query = "SELECT * FROM users WHERE username = %s"
    cursor.execute(query, (username,))
    return cursor.fetchone()
'''
            else:
                code_match = re.search(
                    r"Original code to fix \(line numbers prefixed\):\s*\n(.*?)\n\s*Issue to fix:",
                    user_prompt,
                    re.DOTALL,
                )
                if code_match:
                    raw_lines = [
                        re.sub(r"^\s*\d+:\s*", "", l)
                        for l in code_match.group(1).splitlines()
                    ]
                    cleaned = "\n".join(raw_lines)
                    fixed_code = re.sub(
                        r'f"SELECT\s+([^"]*?)\{([^}]+)\}([^"]*?)"',
                        r'"SELECT \1%s\3"',
                        cleaned,
                    )
                    fixed_code = re.sub(
                        r'cursor\.execute\(([^,)]+)\)',
                        r'cursor.execute(\1, (username,))',
                        fixed_code,
                    )
                    if not fixed_code.endswith("\n"):
                        fixed_code += "\n"
                else:
                    fixed_code = '''def get_user(cursor, username: str):
    query = "SELECT * FROM users WHERE username = %s"
    cursor.execute(query, (username,))
    return cursor.fetchone()
'''
            explanation = "Replaced string-interpolated query with parameterized SQL query placeholders to prevent SQL injection."
            return json.dumps({"fixed_code": fixed_code, "explanation": explanation}, indent=2)

        # 2. Division by Zero Case (empty-list guard)
        if (
            "division" in user_prompt.lower()
            or "zerodivision" in user_prompt.lower()
            or "len(" in user_prompt
        ):
            has_failure_feedback = (
                "your last fix failed" in user_prompt.lower()
                or "[previous attempt failed]" in user_prompt.lower()
                or "failure reason" in user_prompt.lower()
                or "failure feedback" in user_prompt.lower()
                or "syntaxerror" in user_prompt.lower()
            )

            # On attempt 1 with no feedback, return a deliberately broken patch (syntax error) for demo retry testing
            if not has_failure_feedback:
                if "compute_average_latency" in user_prompt:
                    broken_code = '''def compute_average_latency(measurements: list[float]) -> float:
    # Deliberate syntax error: missing colon
    if not measurements return 0.0
    total = sum(measurements)
    return total / len(measurements)
'''
                elif "calculate_average" in user_prompt:
                    broken_code = '''def calculate_average(scores: list[float]) -> float:
    if not scores return 0.0
    total = sum(scores)
    return total / len(scores)
'''
                else:
                    broken_code = '''def compute_average(items: list[float]) -> float:
    if not items return 0.0
    total = sum(items)
    return total / len(items)
'''
                explanation = "Attempted empty-collection guard with syntax error for verification retry testing."
                return json.dumps({"fixed_code": broken_code, "explanation": explanation}, indent=2)

            # On retry with feedback, return valid corrected code
            if "compute_average_latency" in user_prompt:
                fixed_code = '''def compute_average_latency(measurements: list[float]) -> float:
    # Guard against division by zero on empty collection
    if not measurements:
        return 0.0
    total = sum(measurements)
    return total / len(measurements)
'''
            elif "calculate_average" in user_prompt:
                fixed_code = '''def calculate_average(scores: list[float]) -> float:
    if not scores:
        return 0.0
    total = sum(scores)
    return total / len(scores)
'''
            else:
                code_match = re.search(
                    r"Original code to fix \(line numbers prefixed\):\s*\n(.*?)\n\s*Issue to fix:",
                    user_prompt,
                    re.DOTALL,
                )
                if code_match:
                    raw_lines = [
                        re.sub(r"^\s*\d+:\s*", "", l)
                        for l in code_match.group(1).splitlines()
                    ]
                    lines = []
                    inserted = False
                    for line in raw_lines:
                        if ("total = sum(" in line or "return total / len(" in line) and not inserted:
                            indent = " " * (len(line) - len(line.lstrip()))
                            lines.append(f"{indent}if not items:")
                            lines.append(f"{indent}    return 0.0")
                            inserted = True
                        lines.append(line)
                    fixed_code = "\n".join(lines) + "\n"
                else:
                    fixed_code = '''def compute_average(items: list[float]) -> float:
    if not items:
        return 0.0
    total = sum(items)
    return total / len(items)
'''
            explanation = "Added an empty-collection guard before division to prevent ZeroDivisionError."
            return json.dumps({"fixed_code": fixed_code, "explanation": explanation}, indent=2)

        # 3. Mutable Default Argument Case (None default)
        if (
            "mutable" in user_prompt.lower()
            or "default" in user_prompt.lower()
            or "= []" in user_prompt
            or "=[]" in user_prompt
        ):
            if "register_event" in user_prompt:
                fixed_code = '''def register_event(event_name: str, tags: list | None = None):
    # Safe default handling with None
    if tags is None:
        tags = []
    tags.append(event_name)
    return tags
'''
            elif "add_item" in user_prompt:
                fixed_code = '''def add_item(item, items: list | None = None):
    if items is None:
        items = []
    items.append(item)
    return items
'''
            else:
                code_match = re.search(
                    r"Original code to fix \(line numbers prefixed\):\s*\n(.*?)\n\s*Issue to fix:",
                    user_prompt,
                    re.DOTALL,
                )
                if code_match:
                    raw_lines = [
                        re.sub(r"^\s*\d+:\s*", "", l)
                        for l in code_match.group(1).splitlines()
                    ]
                    lines = []
                    for line in raw_lines:
                        if "def " in line and "= []" in line:
                            lines.append(line.replace("= []", "= None"))
                            lines.append("    if tags is None:")
                            lines.append("        tags = []")
                        else:
                            lines.append(line)
                    fixed_code = "\n".join(lines) + "\n"
                else:
                    fixed_code = '''def func(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items
'''
            explanation = "Replaced mutable default argument with None and initialized a new list within function body."
            return json.dumps({"fixed_code": fixed_code, "explanation": explanation}, indent=2)

        # Default fallback
        return json.dumps(
            {
                "fixed_code": "# Default fix\n",
                "explanation": "Applied automated repair.",
            }
        )

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
        http_client: httpx.Client | None = None,
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

        self._http_client = http_client
        self.last_error: str | None = None

    def _resolve_endpoint(self) -> str:
        clean_url = self.base_url.rstrip("/")
        if clean_url.endswith("/chat/completions"):
            return clean_url
        return f"{clean_url}/chat/completions"

    def _sanitize(self, text: str) -> str:
        """Strip any accidental occurrence of api_key from error text or log messages."""
        if self.api_key and self.api_key in text:
            return text.replace(self.api_key, "***")
        return text

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

        max_retries = 4
        delays = [2.0, 4.0, 8.0, 16.0]
        retryable_status_codes = {429, 500, 502, 503, 504}

        for attempt in range(max_retries + 1):
            try:
                if self._http_client is not None:
                    response = self._http_client.post(endpoint, json=payload, headers=headers)
                else:
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
                error_text = self._sanitize(err.response.text)
                logger.error("HTTP error %s from LLM endpoint %s", status_code, endpoint)

                # Do not retry on permanent errors (400, 401, 403, 404) or any non-retryable status
                if status_code not in retryable_status_codes:
                    self.last_error = f"LLM API request failed with HTTP {status_code}: {error_text}"
                    raise RuntimeError(self.last_error) from None

                if attempt >= max_retries:
                    self.last_error = f"LLM API request failed with HTTP {status_code} after {max_retries} retries: {error_text}"
                    raise RuntimeError(self.last_error) from None

                jitter = random.uniform(0.1, 0.5)
                delay = delays[attempt] + jitter
                retry_msg = f"[Retry {attempt + 1}/{max_retries}] HTTP {status_code} received from LLM endpoint. Retrying in {delay:.2f}s..."
                print(retry_msg, flush=True)
                logger.warning(
                    "[Retry %d/%d] HTTP %s from LLM endpoint. Retrying in %.2fs...",
                    attempt + 1,
                    max_retries,
                    status_code,
                    delay,
                )
                time.sleep(delay)

            except httpx.TimeoutException as err:
                sanitized_err = self._sanitize(str(err))
                logger.error("Timeout connecting to LLM endpoint %s: %s", endpoint, sanitized_err)

                if attempt >= max_retries:
                    self.last_error = f"LLM request timed out after {max_retries} retries: {sanitized_err}"
                    raise RuntimeError(self.last_error) from None

                jitter = random.uniform(0.1, 0.5)
                delay = delays[attempt] + jitter
                retry_msg = f"[Retry {attempt + 1}/{max_retries}] Request timed out for LLM endpoint. Retrying in {delay:.2f}s..."
                print(retry_msg, flush=True)
                logger.warning(
                    "[Retry %d/%d] Request timed out for LLM endpoint. Retrying in %.2fs...",
                    attempt + 1,
                    max_retries,
                    delay,
                )
                time.sleep(delay)

            except httpx.RequestError as err:
                sanitized_err = self._sanitize(str(err))
                logger.error("Network error when connecting to LLM endpoint %s: %s", endpoint, sanitized_err)
                self.last_error = f"LLM network error: {sanitized_err}"
                raise RuntimeError(self.last_error) from None


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
        from pathlib import Path
        from dotenv import load_dotenv
        _env = Path(__file__).resolve().parent.parent.parent / ".env"
        if _env.is_file():
            load_dotenv(dotenv_path=_env)
        else:
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
