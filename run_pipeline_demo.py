"""Pipeline demo script — runs the 3 canonical buggy snippets through the full pipeline.

Usage:
    python run_pipeline_demo.py

Respects the LLM_PROVIDER env var (reads .env if present). Writes results to
results/demo_output.json and prints a readable summary to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# .env loading — must happen before any app import so get_client() sees it
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    _env_file = Path(__file__).resolve().parent / ".env"
    if _env_file.is_file():
        load_dotenv(dotenv_path=_env_file, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# App imports (after env is loaded)
# ---------------------------------------------------------------------------
from app.pipeline import run_pipeline  # noqa: E402
from app.review.llm_client import get_client  # noqa: E402

# ---------------------------------------------------------------------------
# Canonical buggy snippets (same as the other demo scripts)
# ---------------------------------------------------------------------------
SNIPPETS = [
    {
        "label": "SQL Injection",
        "file": "db_query.py",
        "code": """\
import sqlite3

def get_user(username: str) -> dict | None:
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
""",
    },
    {
        "label": "Division by Zero",
        "file": "statistics.py",
        "code": """\
def compute_average(values: list[float]) -> float:
    total = sum(values)
    return total / len(values)
""",
    },
    {
        "label": "Mutable Default Argument",
        "file": "utils.py",
        "code": """\
def append_item(item: str, collection: list[str] = []) -> list[str]:
    collection.append(item)
    return collection
""",
    },
]


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _sep(char: str = "-", width: int = 70) -> str:
    return char * width


def _print_banner(title: str) -> None:
    print(_sep("="))
    print(f"  {title.upper()}")
    print(_sep("="))


def _print_repair_summary(result: dict) -> None:
    summary = result["summary"]
    counts = result["counts"]
    print(f"  Issues detected : {counts['issues_detected']}")
    print(f"  Kept (relevant) : {counts['kept']}")
    print(f"  Filtered noise  : {counts['filtered_as_noise']}")
    by_sev = counts.get("by_severity", {})
    if by_sev:
        sev_str = ", ".join(f"{k}={v}" for k, v in sorted(by_sev.items()))
        print(f"  By severity     : {sev_str}")
    print(f"  Verified fixes  : {summary['verified']}")
    print(f"  Failed fixes    : {summary['failed']}")
    print(f"  Needed retries  : {summary['retried']}")

    for rep in result.get("repairs", []):
        f = rep["finding"]
        status_icon = "[OK]" if rep["status"] == "verified" else "[FAIL]"
        print(
            f"\n  {status_icon} {f['file']}:{f['line']} [{f['severity']}] "
            f"{f['description'][:60]}..."
        )
        print(f"      status={rep['status']}  attempts={rep['attempts']}  "
              f"verified_at={rep['verification_stage']}")
        if rep.get("explanation"):
            print(f"      explanation: {rep['explanation'][:100]}")

    errors = result.get("pipeline_errors", [])
    if errors:
        print("\n  [!] Pipeline errors:")
        for err in errors:
            print(f"     * {err[:200]}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Re-load .env here too for safety (import-time load may have been skipped)
    try:
        from dotenv import load_dotenv as _ld

        _env_file = Path(__file__).resolve().parent / ".env"
        if _env_file.is_file():
            _ld(dotenv_path=_env_file, override=True)
        else:
            _ld(override=True)
    except ImportError:
        pass

    provider = os.environ.get("LLM_PROVIDER", "mock")
    client = get_client()

    _print_banner(f"CodeInsight AI - Full Pipeline Demo  [provider: {provider}]")
    print()

    all_results: list[dict] = []

    for idx, snippet in enumerate(SNIPPETS, start=1):
        print(f"\n{'─' * 70}")
        print(f"  Snippet {idx}/{len(SNIPPETS)}: {snippet['label']}  ({snippet['file']})")
        print("─" * 70)

        result = run_pipeline(
            code=snippet["code"],
            file=snippet["file"],
            client=client,
        )
        result["label"] = snippet["label"]
        all_results.append(result)

        _print_repair_summary(result)

    # ------------------------------------------------------------------
    # Write JSON output
    # ------------------------------------------------------------------
    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(exist_ok=True)
    output_path = results_dir / "demo_output.json"
    output_path.write_text(json.dumps(all_results, indent=2), encoding="utf-8")

    print()
    print(_sep("="))
    verified_total = sum(r["summary"]["verified"] for r in all_results)
    failed_total = sum(r["summary"]["failed"] for r in all_results)
    print(f"  TOTAL  verified={verified_total}  failed={failed_total}")
    print(f"  Results written to: {output_path}")
    print(_sep("="))

    sys.exit(0 if failed_total == 0 else 1)


if __name__ == "__main__":
    main()
