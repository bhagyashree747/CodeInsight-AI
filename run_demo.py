"""CodeInsight AI - Interactive Demo Script.

Demonstrates automated code review and relevance filtering across 4 scenarios:
1. SQL Injection vulnerability (Security)
2. Division by zero on empty collection (Bug)
3. Mutable default argument (Bug / Logic)
4. Clean code (No demonstrable defects)
"""

import json
import os
from pathlib import Path

# Call load_dotenv() first to respect whatever provider is configured in .env
try:
    from dotenv import load_dotenv
    _env_file = Path(__file__).resolve().parent / ".env"
    if _env_file.is_file():
        load_dotenv(dotenv_path=_env_file, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass

from app.relevance.filter import filter_findings
from app.review.llm_client import LLMClient, get_client
from app.review.reviewer import review


class TrackingClient(LLMClient):
    """Wrapper around LLMClient that records the last error if complete() fails."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.last_error: str | None = None

    def complete(self, system: str, user: str) -> str:
        try:
            return self.inner.complete(system=system, user=user)
        except Exception as err:
            self.last_error = str(err)
            raise


def print_banner(title: str) -> None:
    border = "=" * 80
    print(f"\n{border}")
    print(f"  {title.upper()}")
    print(f"{border}\n")


def display_code(code: str) -> None:
    print("Source Code:")
    for idx, line in enumerate(code.splitlines(), start=1):
        print(f"  {idx:2d} | {line}")
    print()


def run_snippet_demo(
    name: str,
    filename: str,
    code: str,
    changed_lines: set[int] | None = None,
) -> bool:
    print_banner(f"Demo Case: {name} ({filename})")
    display_code(code)

    if changed_lines:
        print(f"PR Changed Lines: {sorted(changed_lines)}")
    else:
        print("PR Changed Lines: All lines (new file)")

    print("\n[Step 1] Running LLM Reviewer...")
    tracker = TrackingClient(get_client())
    try:
        raw_findings = review(context=code, file=filename, changed_lines=changed_lines, client=tracker)
    except Exception as err:
        print(f"\nFAILED: {err}")
        return False

    if tracker.last_error is not None:
        print(f"\nFAILED: {tracker.last_error}")
        return False

    print(f"-> Generated {len(raw_findings)} raw finding(s) from code analysis.")

    print("\n[Step 2] Running Relevance & Noise Filter...")
    filter_result = filter_findings(findings=raw_findings, changed_lines=changed_lines)

    # Format kept findings for display
    kept_data = [
        {
            "file": k.file,
            "line": k.line,
            "category": k.category.value if hasattr(k.category, "value") else str(k.category),
            "severity": k.severity.value if hasattr(k.severity, "value") else str(k.severity),
            "confidence": k.confidence,
            "score": k.score,
            "description": k.description,
            "suggested_fix_hint": k.suggested_fix_hint,
            "actionable": k.actionable,
        }
        for k in filter_result.kept
    ]

    # Format discarded findings with reasons
    discarded_data = [
        {
            "file": d.file,
            "line": d.line,
            "category": d.category.value if hasattr(d.category, "value") else str(d.category),
            "reason": d.reason,
            "description": d.description,
        }
        for d in filter_result.discarded
    ]

    print("\n[Step 3] Kept Findings (Useful - Sorted by Relevance Score Descending):")
    print(json.dumps(kept_data, indent=2))

    print("\n[Step 4] Discarded Findings (Filtered as Noise with Explanations):")
    print(json.dumps(discarded_data, indent=2))

    print(f"\n[Result Summary] {filter_result.summary} (Total evaluated: {filter_result.total_count})")
    return True


def main() -> None:
    try:
        from dotenv import load_dotenv
        _env = Path(__file__).resolve().parent / ".env"
        if _env.is_file():
            load_dotenv(dotenv_path=_env, override=True)
        else:
            load_dotenv(override=True)
    except ImportError:
        pass

    raw_provider = os.getenv("LLM_PROVIDER")
    active_provider = raw_provider.strip().lower() if raw_provider else "mock"

    print("=" * 80)
    print("  CODEINSIGHT AI - AUTOMATED PR CODE REVIEWER DEMO")
    print(f"  Active LLM Provider: {active_provider}")
    print("=" * 80)

    # Snippet 1: SQL Injection
    snippet_sql = '''def fetch_user_record(cursor, username: str):
    # Query constructed via direct string interpolation (vulnerable to SQLi)
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()
'''

    # Snippet 2: Division by Zero on Empty List
    snippet_div_zero = '''def compute_average_latency(measurements: list[float]) -> float:
    # Unchecked division by collection length
    total = sum(measurements)
    return total / len(measurements)
'''

    # Snippet 3: Mutable Default Argument
    snippet_mutable_default = '''def register_event(event_name: str, tags: list = []):
    # Mutable default argument retains state across multiple function calls
    tags.append(event_name)
    return tags
'''

    # Snippet 4: Clean Snippet
    snippet_clean = '''def calculate_discounted_price(price: float, discount_percent: float) -> float:
    """Calculate discounted price with defensive bounds checks."""
    if not (0.0 <= discount_percent <= 100.0):
        raise ValueError("discount_percent must be between 0 and 100")
    if price < 0:
        raise ValueError("price cannot be negative")
    factor = 1.0 - (discount_percent / 100.0)
    return round(price * factor, 2)
'''

    cases = [
        ("SQL Injection Vulnerability", "app/db/users.py", snippet_sql, {1, 2, 3, 4}),
        ("Division by Zero on Empty Input", "app/metrics/latency.py", snippet_div_zero, {2, 3, 4}),
        ("Mutable Default Argument", "app/events/logger.py", snippet_mutable_default, {1, 2, 3}),
        ("Clean & Defensive Implementation", "app/billing/pricing.py", snippet_clean, {1, 2, 3, 4, 5, 6, 7, 8}),
    ]

    all_succeeded = True
    for name, filename, code, changed_lines in cases:
        ok = run_snippet_demo(
            name=name,
            filename=filename,
            code=code,
            changed_lines=changed_lines,
        )
        if not ok:
            all_succeeded = False

    print("\n" + "=" * 80)
    if all_succeeded:
        print("  DEMO COMPLETE - ALL 4 TEST CASES EXECUTED SUCCESSFULLY")
    else:
        print("  DEMO FINISHED WITH FAILURES")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
