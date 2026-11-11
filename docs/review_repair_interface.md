# CodeInsight AI: Review & Repair Interface

This document specifies the public interface of the CodeInsight AI review, relevance filtering, and self-correcting repair pipeline.

---

## 1. Pipeline Entrypoint: `run_pipeline()`

The main orchestration entrypoint is `app.pipeline.run_pipeline()`. It executes the end-to-end pipeline:

1. **Review**: Identifies potential code bugs, security vulnerabilities, performance bottlenecks, and logic flaws via LLM.
2. **Relevance Filter**: Filters noisy, low-confidence, duplicate, or off-diff findings, scoring each issue.
3. **Repair Agent**: Generates fixes for kept findings and iteratively validates them using a `Verifier`, automatically retrying with diagnostic feedback if verification fails.

The pipeline is exception-safe: any internal error (LLM timeouts, malformed JSON, syntax parsing errors) is captured in the returned dictionary without crashing.

### Function Signature

```python
def run_pipeline(
    code: str,
    file: str = "snippet.py",
    changed_lines: set[int] | None = None,
    client: LLMClient | None = None,
    verifier: Verifier | None = None,
    max_attempts: int = 3,
    test_code: str | None = None,
    functions: list[dict[str, Any]] | list[Any] | None = None,
    extra_context: str | None = None,
    context_level: str | None = None,
) -> dict[str, Any]:
```

### Parameters

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `code` | `str` | *required* | Full source code of the file being reviewed and repaired. |
| `file` | `str` | `"snippet.py"` | Logical path/filename of the source file. |
| `changed_lines` | `set[int] \| None` | `None` | Optional set of 1-indexed line numbers modified in a PR diff. When provided, findings outside these lines are discarded as off-diff. |
| `client` | `LLMClient \| None` | `None` | Optional LLM client instance. If omitted, `get_client()` resolves the provider from the environment. |
| `verifier` | `Verifier \| None` | `None` | Verification engine implementing the `Verifier` protocol. If omitted, defaults to `LocalVerifier(test_code=test_code)`. |
| `max_attempts` | `int` | `3` | Maximum repair retry attempts per kept finding. |
| `test_code` | `str \| None` | `None` | Optional pytest test suite string used by `LocalVerifier` to ensure repairs pass functional tests. |
| `functions` | `list[dict \| Any] \| None` | `None` | Optional list of function metadata objects/dicts with keys `name`, `start_line`, `end_line`, `text`, and optional `too_large: bool`. When provided, review and repair operate at the function level, splicing validated fixes into the full file. |
| `extra_context` | `str \| None` | `None` | Supplementary read-only context (e.g. imports, related classes, callers/callees) supplied to the LLM during review and repair. |
| `context_level` | `str \| None` | `None` | Metadata describing the scope of `extra_context` (e.g. `"file"`, `"module"`, `"repo"`, `"imported_symbols"`). Included in the returned result. |

---

## 2. Usage Example: Function-Level Review and Repair

Below is a complete example demonstrating how to run the pipeline for a file with parsed function definitions:

```python
from app.pipeline import run_pipeline

file_code = '''\
import math

def calculate_average(numbers: list[float]) -> float:
    # Bug: ZeroDivisionError if numbers is empty
    return sum(numbers) / len(numbers)

def greet(name: str) -> str:
    return f"Hello, {name}!"
'''

# Extracted function definitions (e.g. from an AST parser or Tree-sitter)
functions = [
    {
        "name": "calculate_average",
        "start_line": 3,
        "end_line": 5,
        "text": 'def calculate_average(numbers: list[float]) -> float:\n    # Bug: ZeroDivisionError if numbers is empty\n    return sum(numbers) / len(numbers)',
        "too_large": False,
    },
    {
        "name": "greet",
        "start_line": 7,
        "end_line": 8,
        "text": 'def greet(name: str) -> str:\n    return f"Hello, {name}!"',
        "too_large": False,
    },
]

# Optional unit test ensuring the fix handles empty lists correctly
test_code = """
import pytest
from snippet import calculate_average

def test_average():
    assert calculate_average([2.0, 4.0]) == 3.0
    assert calculate_average([]) == 0.0
"""

# Optional supplementary context (read-only)
extra_context = "# Note: When numbers is empty, calculate_average should return 0.0"

result = run_pipeline(
    code=file_code,
    file="snippet.py",
    functions=functions,
    test_code=test_code,
    extra_context=extra_context,
    context_level="module",
    max_attempts=3,
)

print("Pipeline Status:", result["summary"])
print("Repairs:", result["repairs"])
```

---

## 3. Returned Dictionary Schema

`run_pipeline()` returns a JSON-serializable dictionary with the following schema:

```json
{
  "file": "snippet.py",
  "context_level": "module",
  "counts": {
    "issues_detected": 1,
    "kept": 1,
    "filtered_as_noise": 0,
    "by_severity": {
      "high": 1
    }
  },
  "findings": [
    {
      "file": "snippet.py",
      "line": 5,
      "category": "bug",
      "severity": "high",
      "confidence": 0.95,
      "description": "ZeroDivisionError when 'numbers' is empty.",
      "suggested_fix_hint": "Check if len(numbers) == 0 before dividing.",
      "actionable": true,
      "score": 0.95
    }
  ],
  "discarded": [
    {
      "file": "snippet.py",
      "line": 8,
      "category": "logic",
      "severity": "low",
      "confidence": 0.3,
      "description": "Style suggestion.",
      "suggested_fix_hint": "",
      "actionable": false,
      "reason": "Confidence 0.30 below threshold 0.50"
    }
  ],
  "repairs": [
    {
      "finding": {
        "file": "snippet.py",
        "line": 5,
        "category": "bug",
        "severity": "high",
        "confidence": 0.95,
        "description": "ZeroDivisionError when 'numbers' is empty.",
        "suggested_fix_hint": "Check if len(numbers) == 0 before dividing.",
        "actionable": true
      },
      "status": "verified",
      "attempts": 1,
      "diff": "--- snippet.py\n+++ snippet.py\n@@ -3,3 +3,4 @@\n def calculate_average(numbers: list[float]) -> float:\n+    if not numbers:\n+        return 0.0\n     return sum(numbers) / len(numbers)\n",
      "explanation": "Guarded against division by zero by returning 0.0 if numbers is empty.",
      "verification_stage": "tests"
    }
  ],
  "summary": {
    "verified": 1,
    "failed": 0,
    "retried": 0,
    "skipped": 0
  },
  "pipeline_errors": []
}
```

### Dictionary Keys Explained

- `file` (`str`): Target file path.
- `context_level` (`str | None`): The context level label passed into `run_pipeline`.
- `counts` (`dict`):
  - `issues_detected` (`int`): Total raw findings produced by the LLM reviewer.
  - `kept` (`int`): Number of findings that passed relevance and quality filters.
  - `filtered_as_noise` (`int`): Number of discarded findings.
  - `by_severity` (`dict[str, int]`): Count of kept findings grouped by severity (`"high"`, `"medium"`, `"low"`).
- `findings` (`list[dict]`): Kept findings sorted by relevance score descending. Each finding includes `score` (0.0 to 1.0).
- `discarded` (`list[dict]`): Findings rejected by the relevance filter, each including the specific `reason` string (e.g. low confidence, non-actionable, off-diff, duplicate).
- `repairs` (`list[dict]`): Per-finding repair details:
  - `finding` (`dict`): The finding being repaired.
  - `status` (`str`): `"verified"`, `"failed"`, or `"skipped"`.
  - `attempts` (`int`): Number of generation attempts executed.
  - `diff` (`str`): Unified diff of the final patch (or empty string if none).
  - `explanation` (`str`): Explanation of the change or skip reason.
  - `verification_stage` (`str`): Verification stage reached by the final attempt (`"syntax"`, `"lint"`, `"tests"`, or `"none"`).
- `summary` (`dict[str, int]`): High-level repair outcome counts:
  - `verified`: Number of repairs that passed verification.
  - `failed`: Number of repairs that failed after all retry attempts.
  - `retried`: Number of repairs that required more than 1 attempt.
  - `skipped` (optional): Number of repairs skipped (e.g. functions marked `too_large=True`).
- `pipeline_errors` (`list[str]`, optional): Tracebacks or error messages if any pipeline stage encountered an unexpected exception.

---

## 4. Environment Variables Configuration

The LLM client layer is configured via environment variables (loaded automatically from a `.env` file if present):

```bash
# Provider selection: "mock", "openai_compat", or "ollama"
# Default is "mock" if unset
LLM_PROVIDER=mock

# Base URL for openai_compat provider
# For Google Gemini (OpenAI-compatible):
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
# For Groq:
# LLM_BASE_URL=https://api.groq.com/openai/v1

# API key for the chosen provider (keep secret, never commit)
LLM_API_KEY=your_api_key_here

# Model name
# For Google Gemini: gemini-2.5-flash or gemini-1.5-flash
# For Groq: llama-3.3-70b-versatile
# For Ollama: qwen2.5-coder:7b
LLM_MODEL=gemini-2.5-flash

# Optional request timeout in seconds (default: 30)
LLM_TIMEOUT=30
```

> **Security Note:** Never hardcode or commit actual API keys to version control. Use `.env.example` as a template and ensure `.env` is listed in `.gitignore`.

---

## 5. Verifier Interface & Protocol

Verification decouples patch generation from patch validation, ensuring generated repairs do not break code syntax, conventions, or test suites.

### Protocol Definition (`app.repair.verifier_interface`)

```python
from dataclasses import dataclass
from typing import Literal, Protocol

@dataclass
class VerificationResult:
    passed: bool
    stage: Literal["syntax", "lint", "tests", "none"]
    error: str = ""
    output: str = ""

class Verifier(Protocol):
    def verify(self, patched_code: str, file_path: str) -> VerificationResult:
        """Verify the patched code.

        Args:
            patched_code: Full content of the file after applying the patch.
            file_path: Relative or absolute path of the target file.

        Returns:
            VerificationResult indicating success or stage-specific failure details.
        """
        ...
```

### `LocalVerifier` Implementation (`app.repair.local_verifier`)

`LocalVerifier` is the default 3-stage local verifier:

1. **Stage 1 (Syntax)**: Compiles `patched_code` in memory using Python's `compile(..., "exec")`. If a `SyntaxError` is raised, verification immediately halts with `stage="syntax"` and the line number and syntax error message.
2. **Stage 2 (Lint)**: Runs `ruff check` inside an isolated temporary directory. If `ruff` is not installed on the system (`shutil.which("ruff") is None`), this stage is silently skipped. If lint errors exist, returns `stage="lint"`.
3. **Stage 3 (Tests)**: If `test_code` was provided in the constructor, `LocalVerifier` writes the patched file and test file into a clean temporary directory and runs `pytest` with a 20-second timeout. If the test fails, returns `stage="tests"` with output truncated to 1500 characters.

All file operations in `LocalVerifier` take place in isolated temporary directories (`tempfile.TemporaryDirectory`), leaving the local project directory completely untouched.
