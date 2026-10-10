"""CodeInsight AI - Patch Generation and Repair Demo.

Demonstrates automated code repair across 3 buggy scenarios:
1. SQL Injection vulnerability (Security) -> Parameterized query
2. Division by zero on empty input (Bug) -> Empty collection guard
3. Mutable default argument (Bug) -> None default with body initialization

Workflow for each scenario:
Review -> Relevance Filter -> Top Finding Selection -> Patch Generation -> Diff & Explanation
"""

import os
from app.relevance.filter import filter_findings
from app.repair.patch_generator import apply_patch, generate_patch
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


def run_repair_demo(
    name: str,
    filename: str,
    code: str,
    changed_lines: set[int] | None = None,
) -> bool:
    print_banner(f"Repair Demo: {name} ({filename})")
    display_code(code)

    tracker = TrackingClient(get_client())

    print("[Step 1] Running Automated Review...")
    try:
        raw_findings = review(context=code, file=filename, changed_lines=changed_lines, client=tracker)
    except Exception as err:
        print(f"\nFAILED: {err}")
        return False

    if tracker.last_error is not None:
        print(f"\nFAILED: {tracker.last_error}")
        return False

    print(f"-> Generated {len(raw_findings)} raw finding(s).")

    print("\n[Step 2] Filtering Relevance & Scoring Findings...")
    filter_result = filter_findings(findings=raw_findings, changed_lines=changed_lines)
    print(f"-> {filter_result.summary}")

    if not filter_result.kept:
        print("-> No actionable findings kept. Skipping patch generation.")
        return True

    top_item = filter_result.kept[0]
    top_finding = top_item.finding
    print(f"\n[Step 3] Selected Top Finding (Score: {top_item.score}):")
    print(f"  Line:        {top_finding.line}")
    print(f"  Category:    {top_finding.category.value if hasattr(top_finding.category, 'value') else top_finding.category}")
    print(f"  Severity:    {top_finding.severity.value if hasattr(top_finding.severity, 'value') else top_finding.severity}")
    print(f"  Description: {top_finding.description}")
    print(f"  Fix Hint:    {top_finding.suggested_fix_hint}")

    print("\n[Step 4] Generating Patch via LLM...")
    try:
        patch = generate_patch(code=code, finding=top_finding, client=tracker)
    except Exception as err:
        print(f"\nFAILED: {err}")
        return False

    if tracker.last_error is not None:
        print(f"\nFAILED: {tracker.last_error}")
        return False

    print("\n[Step 5] Generated Unified Diff:")
    print("-" * 60)
    for line in patch.diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            print(f"  \033[92m{line}\033[0m")  # Green for added lines if supported
        elif line.startswith("-") and not line.startswith("---"):
            print(f"  \033[91m{line}\033[0m")  # Red for removed lines if supported
        else:
            print(f"  {line}")
    print("-" * 60)

    print("\n[Step 6] Explanation of Repair:")
    print(f"  \"{patch.explanation}\"")

    # Verify apply_patch safety
    apply_res = apply_patch(patch=patch, original_path=filename)
    if apply_res.success:
        print(f"\n[Step 7] Patch safely staged to temporary file copy:")
        print(f"  Original file intact: {apply_res.original_path}")
        print(f"  Staged patched copy:  {apply_res.patched_path}")
        # Clean up staged temporary file
        try:
            if apply_res.patched_path:
                os.remove(apply_res.patched_path)
        except OSError:
            pass
    return True


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    active_provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()

    print("=" * 80)
    print("  CODEINSIGHT AI - AUTOMATED CODE REPAIR & PATCH DEMO")
    print(f"  Active LLM Provider: {active_provider}")
    print("=" * 80)

    # Buggy Snippet 1: SQL Injection
    snippet_sql = '''def fetch_user_record(cursor, username: str):
    # Query constructed via direct string interpolation (vulnerable to SQLi)
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()
'''

    # Buggy Snippet 2: Division by Zero on Empty List
    snippet_div_zero = '''def compute_average_latency(measurements: list[float]) -> float:
    # Unchecked division by collection length
    total = sum(measurements)
    return total / len(measurements)
'''

    # Buggy Snippet 3: Mutable Default Argument
    snippet_mutable_default = '''def register_event(event_name: str, tags: list = []):
    # Mutable default argument retains state across multiple function calls
    tags.append(event_name)
    return tags
'''

    cases = [
        ("SQL Injection Vulnerability", "app/db/users.py", snippet_sql, {1, 2, 3, 4}),
        ("Division by Zero on Empty Input", "app/metrics/latency.py", snippet_div_zero, {2, 3, 4}),
        ("Mutable Default Argument", "app/events/logger.py", snippet_mutable_default, {1, 2, 3}),
    ]

    all_succeeded = True
    for name, filename, code, changed_lines in cases:
        ok = run_repair_demo(
            name=name,
            filename=filename,
            code=code,
            changed_lines=changed_lines,
        )
        if not ok:
            all_succeeded = False

    print("\n" + "=" * 80)
    if all_succeeded:
        print("  PATCH DEMO COMPLETE - ALL 3 BUGGY SNIPPETS EXECUTED SUCCESSFULLY")
    else:
        print("  PATCH DEMO FINISHED WITH FAILURES")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
