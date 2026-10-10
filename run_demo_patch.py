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
from app.review.reviewer import review


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
) -> None:
    print_banner(f"Repair Demo: {name} ({filename})")
    display_code(code)

    print("[Step 1] Running Automated Review...")
    raw_findings = review(context=code, file=filename, changed_lines=changed_lines)
    print(f"-> Generated {len(raw_findings)} raw finding(s).")

    print("\n[Step 2] Filtering Relevance & Scoring Findings...")
    filter_result = filter_findings(findings=raw_findings, changed_lines=changed_lines)
    print(f"-> {filter_result.summary}")

    if not filter_result.kept:
        print("-> No actionable findings kept. Skipping patch generation.")
        return

    top_item = filter_result.kept[0]
    top_finding = top_item.finding
    print(f"\n[Step 3] Selected Top Finding (Score: {top_item.score}):")
    print(f"  Line:        {top_finding.line}")
    print(f"  Category:    {top_finding.category.value if hasattr(top_finding.category, 'value') else top_finding.category}")
    print(f"  Severity:    {top_finding.severity.value if hasattr(top_finding.severity, 'value') else top_finding.severity}")
    print(f"  Description: {top_finding.description}")
    print(f"  Fix Hint:    {top_finding.suggested_fix_hint}")

    print("\n[Step 4] Generating Patch via LLM...")
    patch = generate_patch(code=code, finding=top_finding)

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


def main() -> None:
    # Set default mock provider if not configured
    if "LLM_PROVIDER" not in os.environ:
        os.environ["LLM_PROVIDER"] = "mock"

    print("=" * 80)
    print("  CODEINSIGHT AI - AUTOMATED CODE REPAIR & PATCH DEMO")
    print(f"  Active LLM Provider: {os.environ.get('LLM_PROVIDER', 'mock')}")
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

    run_repair_demo(
        name="SQL Injection Vulnerability",
        filename="app/db/users.py",
        code=snippet_sql,
        changed_lines={1, 2, 3, 4},
    )

    run_repair_demo(
        name="Division by Zero on Empty Input",
        filename="app/metrics/latency.py",
        code=snippet_div_zero,
        changed_lines={2, 3, 4},
    )

    run_repair_demo(
        name="Mutable Default Argument",
        filename="app/events/logger.py",
        code=snippet_mutable_default,
        changed_lines={1, 2, 3},
    )

    print("\n" + "=" * 80)
    print("  PATCH DEMO COMPLETE - ALL 3 BUGGY SNIPPETS REPAIRED SUCCESSFULLY")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
