"""CodeInsight AI - Automated Repair & Multi-Stage Verification Demo.

Demonstrates:
- RepairAgent with LocalVerifier (Syntax, Lint, Tests)
- Autonomous self-healing retry loop with compiler feedback
- Per-fix outcome reporting:
  - Fix #1 verified (immediate syntax/lint verification on attempt 1)
  - Fix #2 2 attempts -> verified (syntax error on attempt 1 self-heals on attempt 2)
  - Fix #3 failed (verification fails across max attempts)
"""

import os
from app.relevance.filter import filter_findings
from app.repair.agent import RepairAgent
from app.repair.local_verifier import LocalVerifier
from app.review.reviewer import review


def print_banner(title: str) -> None:
    border = "=" * 80
    print(f"\n{border}")
    print(f"  {title.upper()}")
    print(f"{border}\n")


def format_fix_status(index: int, status: str, attempts: int) -> str:
    """Format status string matching project specification."""
    if status == "verified":
        if attempts == 1:
            return f"Fix #{index} verified"
        else:
            return f"Fix #{index} {attempts} attempts -> verified"
    else:
        return f"Fix #{index} failed"


def main() -> None:
    if "LLM_PROVIDER" not in os.environ:
        os.environ["LLM_PROVIDER"] = "mock"

    print("=" * 80)
    print("  CODEINSIGHT AI - AUTOMATED REPAIR & RETRY AGENT DEMO")
    print(f"  Active LLM Provider: {os.environ.get('LLM_PROVIDER', 'mock')}")
    print("=" * 80)

    # Snippet 1: SQL Injection (Security)
    snippet_1 = '''def fetch_user_record(cursor, username: str):
    # Query constructed via direct string interpolation (vulnerable to SQLi)
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()
'''

    # Snippet 2: Division by Zero on Empty List (Bug)
    snippet_2 = '''def compute_average_latency(measurements: list[float]) -> float:
    # Unchecked division by collection length
    total = sum(measurements)
    return total / len(measurements)
'''

    # Snippet 3: Mutable Default Argument (Bug)
    snippet_3 = '''def register_event(event_name: str, tags: list = []):
    # Mutable default argument retains state across multiple function calls
    tags.append(event_name)
    return tags
'''

    results = []

    # --- Scenario 1: Immediate Verification on Attempt 1 ---
    print_banner("Scenario 1: SQL Injection (Immediate Verification)")
    findings_1 = review(snippet_1, file="app/db/users.py", changed_lines={1, 2, 3, 4})
    filtered_1 = filter_findings(findings_1, changed_lines={1, 2, 3, 4})
    top_finding_1 = filtered_1.kept[0].finding
    print(f"Top Finding: Line {top_finding_1.line} - {top_finding_1.description}")

    agent_1 = RepairAgent(verifier=LocalVerifier(), max_attempts=3)
    outcome_1 = agent_1.repair(snippet_1, top_finding_1, file_path="app/db/users.py")
    status_str_1 = format_fix_status(1, outcome_1.status, outcome_1.total_attempts)
    results.append(status_str_1)
    print(f"Status: {status_str_1}")
    print(f"Explanation: {outcome_1.final_patch.explanation if outcome_1.final_patch else 'None'}")

    # --- Scenario 2: Self-Healing Retry (Syntax Error -> Verified) ---
    print_banner("Scenario 2: Division by Zero (Syntax Self-Healing Loop)")
    findings_2 = review(snippet_2, file="app/metrics/latency.py", changed_lines={2, 3, 4})
    filtered_2 = filter_findings(findings_2, changed_lines={2, 3, 4})
    top_finding_2 = filtered_2.kept[0].finding
    print(f"Top Finding: Line {top_finding_2.line} - {top_finding_2.description}")

    agent_2 = RepairAgent(verifier=LocalVerifier(), max_attempts=3)
    outcome_2 = agent_2.repair(snippet_2, top_finding_2, file_path="app/metrics/latency.py")
    status_str_2 = format_fix_status(2, outcome_2.status, outcome_2.total_attempts)
    results.append(status_str_2)
    print(f"Status: {status_str_2}")
    for attempt in outcome_2.attempts:
        v_stage = attempt.verification.stage if attempt.verification else "none"
        v_passed = attempt.verification.passed if attempt.verification else False
        print(f"  - Attempt {attempt.attempt}: Verification passed={v_passed} (stage={v_stage})")
    print(f"Final Fix Explanation: {outcome_2.final_patch.explanation if outcome_2.final_patch else 'None'}")

    # --- Scenario 3: Persistent Failure / Unmet Contract ---
    print_banner("Scenario 3: Mutable Default (Regression Test Failure Exhausted)")
    findings_3 = review(snippet_3, file="app/events/logger.py", changed_lines={1, 2, 3})
    filtered_3 = filter_findings(findings_3, changed_lines={1, 2, 3})
    top_finding_3 = filtered_3.kept[0].finding
    print(f"Top Finding: Line {top_finding_3.line} - {top_finding_3.description}")

    # Verifier enforcing an unmet regression contract to demonstrate max attempts failure
    strict_test_suite = '''
def test_strict_immutability():
    assert False, "Regression contract failed: events framework enforces tuple immutability"
'''
    agent_3 = RepairAgent(verifier=LocalVerifier(test_code=strict_test_suite), max_attempts=3)
    outcome_3 = agent_3.repair(snippet_3, top_finding_3, file_path="app/events/logger.py")
    status_str_3 = format_fix_status(3, outcome_3.status, outcome_3.total_attempts)
    results.append(status_str_3)
    print(f"Status: {status_str_3}")
    for attempt in outcome_3.attempts:
        v_stage = attempt.verification.stage if attempt.verification else "none"
        print(f"  - Attempt {attempt.attempt}: Verification stage={v_stage} (error: {attempt.error})")

    # --- Per-Fix Status Summary ---
    print("\n" + "=" * 80)
    print("  PER-FIX STATUS REPORT")
    print("=" * 80)
    for res in results:
        print(f"  {res}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
