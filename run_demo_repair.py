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
from app.repair.agent import RepairAgent
from app.repair.local_verifier import LocalVerifier
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


def format_fix_status(index: int, status: str, attempts: int) -> str:
    """Format status string matching project specification (verified, number of attempts, failed)."""
    if status == "verified":
        if attempts == 1:
            return f"Fix #{index} verified (1 attempt)"
        else:
            return f"Fix #{index} {attempts} attempts -> verified"
    else:
        return f"Fix #{index} failed ({attempts} attempt{'s' if attempts != 1 else ''})"


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
    print("  CODEINSIGHT AI - AUTOMATED REPAIR & RETRY AGENT DEMO")
    print(f"  Active LLM Provider: {active_provider}")
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

    results: list[str] = []
    all_succeeded = True

    if active_provider == "mock":
        # --- Scenario 1: Immediate Verification on Attempt 1 ---
        print_banner("Scenario 1: SQL Injection (Immediate Verification)")
        try:
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
            if outcome_1.status != "verified":
                all_succeeded = False
        except Exception as err:
            print(f"FAILED: {err}")
            results.append(f"Fix #1 FAILED: {err}")
            all_succeeded = False

        # --- Scenario 2: Self-Healing Retry (Syntax Error -> Verified) ---
        print_banner("Scenario 2: Division by Zero (Syntax Self-Healing Loop)")
        try:
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
            if outcome_2.status != "verified":
                all_succeeded = False
        except Exception as err:
            print(f"FAILED: {err}")
            results.append(f"Fix #2 FAILED: {err}")
            all_succeeded = False

        # --- Scenario 3: Persistent Failure / Unmet Contract ---
        print_banner("Scenario 3: Mutable Default (Regression Test Failure Exhausted)")
        try:
            findings_3 = review(snippet_3, file="app/events/logger.py", changed_lines={1, 2, 3})
            filtered_3 = filter_findings(findings_3, changed_lines={1, 2, 3})
            top_finding_3 = filtered_3.kept[0].finding
            print(f"Top Finding: Line {top_finding_3.line} - {top_finding_3.description}")

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
            # In mock mode, Scenario 3 is designed to demonstrate max attempts failure
            all_succeeded = False
        except Exception as err:
            print(f"FAILED: {err}")
            results.append(f"Fix #3 FAILED: {err}")
            all_succeeded = False

    else:
        # Real provider active: run real repair pipeline on the 3 snippets without scripted failures
        snippets = [
            (1, "SQL Injection", "app/db/users.py", snippet_1, {1, 2, 3, 4}),
            (2, "Division by Zero", "app/metrics/latency.py", snippet_2, {2, 3, 4}),
            (3, "Mutable Default", "app/events/logger.py", snippet_3, {1, 2, 3}),
        ]

        for idx, title, file_path, code, changed_lines in snippets:
            print_banner(f"Scenario {idx}: {title} (Real Provider Pipeline)")
            tracker = TrackingClient(get_client())
            try:
                findings = review(code, file=file_path, changed_lines=changed_lines, client=tracker)
                if tracker.last_error is not None:
                    print(f"FAILED: {tracker.last_error}")
                    results.append(f"Fix #{idx} FAILED: {tracker.last_error}")
                    all_succeeded = False
                    continue

                filtered = filter_findings(findings, changed_lines=changed_lines)
                if not filtered.kept:
                    print("No actionable findings detected to repair.")
                    results.append(f"Fix #{idx} skipped (no findings)")
                    continue

                top_finding = filtered.kept[0].finding
                print(f"Top Finding: Line {top_finding.line} - {top_finding.description}")

                agent = RepairAgent(verifier=LocalVerifier(), client=tracker, max_attempts=3)
                outcome = agent.repair(code, top_finding, file_path=file_path)

                if tracker.last_error is not None:
                    print(f"FAILED: {tracker.last_error}")
                    results.append(f"Fix #{idx} FAILED: {tracker.last_error}")
                    all_succeeded = False
                    continue

                status_str = format_fix_status(idx, outcome.status, outcome.total_attempts)
                results.append(status_str)
                print(f"Status: {status_str}")
                for attempt in outcome.attempts:
                    v_stage = attempt.verification.stage if attempt.verification else "none"
                    v_passed = attempt.verification.passed if attempt.verification else False
                    err_msg = f" (error: {attempt.error})" if attempt.error else ""
                    print(f"  - Attempt {attempt.attempt}: passed={v_passed} stage={v_stage}{err_msg}")

                if outcome.final_patch:
                    print(f"Final Fix Explanation: {outcome.final_patch.explanation}")

                if outcome.status != "verified":
                    all_succeeded = False
                    if outcome.attempts and outcome.attempts[-1].error:
                        print(f"FAILED: {outcome.attempts[-1].error}")
            except Exception as err:
                print(f"FAILED: {err}")
                results.append(f"Fix #{idx} FAILED: {err}")
                all_succeeded = False

    # --- Per-Fix Status Summary ---
    print("\n" + "=" * 80)
    print("  PER-FIX STATUS REPORT")
    print("=" * 80)
    for res in results:
        print(f"  {res}")
    print("=" * 80)

    if all_succeeded:
        print("  REPAIR DEMO COMPLETE - ALL CASES EXECUTED SUCCESSFULLY")
    else:
        print("  REPAIR DEMO FINISHED WITH FAILURES")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
