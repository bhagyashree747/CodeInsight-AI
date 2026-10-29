"""Evaluation experiment runner for CodeInsight AI.

Usage:
    python evaluation/run_experiments.py [--limit N] [--provider PROV] [--sleep S] [--out DIR]

Examples:
    python evaluation/run_experiments.py --limit 3
    python evaluation/run_experiments.py --provider mock --limit 12
    python evaluation/run_experiments.py --provider openai_compat --sleep 3 --out results/

Experiments:
    A) Noise filter ON vs OFF  -> results/experiment_filter.csv + filter_chart.png
    B) One-shot vs Self-correcting repair -> results/experiment_repair.csv + repair_chart.png

Honesty: mock results carry a clear WARNING banner and named provider in chart titles/CSV.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# .env loading — must happen before any app import
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    _env_file = Path(__file__).resolve().parent.parent / ".env"
    if _env_file.is_file():
        load_dotenv(dotenv_path=_env_file, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# App imports
# ---------------------------------------------------------------------------
from evaluation.benchmark import BENCHMARK, BenchmarkSnippet  # noqa: E402
from evaluation.metrics import (  # noqa: E402
    aggregate_filter_metrics,
    compute_false_positive_rate,
    compute_filter_metrics,
    compute_repair_metrics,
)
from app.relevance.filter import filter_findings  # noqa: E402
from app.repair.local_verifier import LocalVerifier  # noqa: E402
from app.repair.agent import RepairAgent  # noqa: E402
from app.review.llm_client import get_client  # noqa: E402
from app.review.reviewer import review  # noqa: E402


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run CodeInsight AI evaluation experiments."
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Use only the first N snippets from the benchmark (default: all).",
    )
    p.add_argument(
        "--provider",
        type=str,
        default=None,
        metavar="PROV",
        help="LLM provider override (mock | openai_compat | ollama). "
             "Defaults to LLM_PROVIDER env var, or 'mock' if unset.",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        metavar="S",
        help="Seconds to pause between LLM calls (default: 2).",
    )
    p.add_argument(
        "--out",
        type=str,
        default="results",
        metavar="DIR",
        help="Output directory for CSV, PNG, README (default: results/).",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Client wrapper: counts ALL calls and enforces --sleep between every call
# ---------------------------------------------------------------------------

class TrackingRateLimitedClient:
    """Wraps an LLMClient to count all complete() invocations and enforce sleep."""

    def __init__(self, inner_client: Any, sleep_s: float = 0.0) -> None:
        self.inner_client = inner_client
        self.sleep_s = sleep_s
        self.call_count = 0

    def complete(self, system: str, user: str) -> str:
        self.call_count += 1
        try:
            return self.inner_client.complete(system=system, user=user)
        finally:
            if self.sleep_s > 0:
                time.sleep(self.sleep_s)


def is_api_error(err: Any) -> bool:
    """Check if an exception or message indicates an API error (429, timeout, etc.)."""
    if not err:
        return False
    msg = str(err).lower()
    keywords = [
        "429", "rate limit", "ratelimit", "quota", "resource exhausted",
        "too many requests", "connection error", "timeout", "timed out",
        "service unavailable", "503", "502", "504", "bad gateway",
        "server error", "api key", "unauthorized", "401", "403",
    ]
    return any(k in msg for k in keywords)


# ---------------------------------------------------------------------------
# Review result cache: snippet_id -> list[Finding]
# ---------------------------------------------------------------------------

_review_cache: dict[str, list] = {}
_review_errors: dict[str, str] = {}


def _cached_review(snippet: BenchmarkSnippet, client: Any) -> list:
    """Call review() once per snippet, then return the cached result."""
    if snippet.id in _review_cache:
        return _review_cache[snippet.id]

    findings = []
    try:
        findings = review(
            context=snippet.code,
            file=f"{snippet.id}.py",
            client=client,
        )
    except Exception as err:
        print(f"  [!] review() error for {snippet.id}: {err}")
        _review_errors[snippet.id] = str(err)

    _review_cache[snippet.id] = findings
    return findings


# ---------------------------------------------------------------------------
# Experiment A: Filter ON vs OFF
# ---------------------------------------------------------------------------

def run_filter_experiment(
    snippets: list[BenchmarkSnippet],
    client: Any,
    provider: str,
) -> tuple[list[dict], list[dict]]:
    """Run the noise-filter experiment.

    Returns:
        (buggy_rows, clean_rows) — each is a list of result dicts.
    """
    buggy_rows: list[dict] = []
    clean_rows: list[dict] = []

    print("\n[Experiment A] Noise filter ON vs OFF")
    print("-" * 60)

    buggy = [s for s in snippets if not s.is_clean]
    clean = [s for s in snippets if s.is_clean]

    for snippet in buggy:
        print(f"  Reviewing {snippet.id} ...", end=" ", flush=True)
        findings = _cached_review(snippet, client)
        print(f"{len(findings)} finding(s)")

        # Filter OFF: all findings
        all_lines = [f.line for f in findings]
        metrics_off = compute_filter_metrics(
            all_lines, snippet.known_bug_line  # type: ignore[arg-type]
        )

        # Filter ON
        fr = filter_findings(findings)
        kept_lines = [sf.finding.line for sf in fr.kept]
        metrics_on = compute_filter_metrics(
            kept_lines, snippet.known_bug_line  # type: ignore[arg-type]
        )

        buggy_rows.append({
            "provider": provider,
            "id": snippet.id,
            "category": snippet.category,
            "known_bug_line": snippet.known_bug_line,
            "total_findings": len(findings),
            "kept_on": len(kept_lines),
            "kept_off": len(all_lines),
            "precision_on": metrics_on["precision"],
            "recall_on": metrics_on["recall"],
            "precision_off": metrics_off["precision"],
            "recall_off": metrics_off["recall"],
        })

    for snippet in clean:
        print(f"  Reviewing (clean) {snippet.id} ...", end=" ", flush=True)
        findings = _cached_review(snippet, client)
        print(f"{len(findings)} finding(s)")

        fr = filter_findings(findings)
        clean_rows.append({
            "provider": provider,
            "id": snippet.id,
            "total_findings": len(findings),
            "kept_count": len(fr.kept),
        })

    return buggy_rows, clean_rows


# ---------------------------------------------------------------------------
# Experiment B: Repair one-shot vs self-correcting
# ---------------------------------------------------------------------------

def _run_repair_for_snippet(
    snippet: BenchmarkSnippet,
    client: Any,
    max_attempts: int,
    provider: str,
) -> dict:
    """Run repair pipeline for one snippet with the given max_attempts budget."""
    findings = _cached_review(snippet, client)

    if snippet.id in _review_errors:
        err_msg = _review_errors[snippet.id]
        status = "error" if is_api_error(err_msg) else "failed"
        return {
            "provider": provider,
            "id": snippet.id,
            "category": snippet.category,
            "max_attempts": max_attempts,
            "status": status,
            "verified": False,
            "attempts": 0,
            "error": err_msg[:200],
        }

    if not findings:
        return {
            "provider": provider,
            "id": snippet.id,
            "category": snippet.category,
            "max_attempts": max_attempts,
            "status": "failed",
            "verified": False,
            "attempts": 0,
            "error": "no_findings",
        }

    fr = filter_findings(findings)
    kept = fr.kept if fr.kept else []
    if not kept:
        return {
            "provider": provider,
            "id": snippet.id,
            "category": snippet.category,
            "max_attempts": max_attempts,
            "status": "failed",
            "verified": False,
            "attempts": 0,
            "error": "all_filtered",
        }

    # Use the highest-scored finding
    top = kept[0]

    verifier = LocalVerifier(test_code=snippet.test_code)
    agent = RepairAgent(verifier=verifier, client=client, max_attempts=max_attempts)

    try:
        outcome = agent.repair(
            code=snippet.code,
            finding=top.finding,
            file_path="snippet.py",
        )
        if outcome.status == "verified":
            return {
                "provider": provider,
                "id": snippet.id,
                "category": snippet.category,
                "max_attempts": max_attempts,
                "status": "verified",
                "verified": True,
                "attempts": outcome.total_attempts,
                "error": "",
            }

        # Check for API errors in attempt history
        api_err_found = any(is_api_error(att.error) for att in outcome.attempts if att.error)
        if api_err_found:
            err_text = next(att.error for att in outcome.attempts if is_api_error(att.error))
            return {
                "provider": provider,
                "id": snippet.id,
                "category": snippet.category,
                "max_attempts": max_attempts,
                "status": "error",
                "verified": False,
                "attempts": outcome.total_attempts,
                "error": err_text[:200],
            }

        last_err = outcome.attempts[-1].error if outcome.attempts else "unverified"
        return {
            "provider": provider,
            "id": snippet.id,
            "category": snippet.category,
            "max_attempts": max_attempts,
            "status": "failed",
            "verified": False,
            "attempts": outcome.total_attempts,
            "error": (last_err or "")[:200],
        }

    except Exception as err:
        status = "error" if is_api_error(err) else "failed"
        return {
            "provider": provider,
            "id": snippet.id,
            "category": snippet.category,
            "max_attempts": max_attempts,
            "status": status,
            "verified": False,
            "attempts": 1,
            "error": str(err)[:200],
        }


def run_repair_experiment(
    snippets: list[BenchmarkSnippet],
    client: Any,
    provider: str,
) -> tuple[list[dict], list[dict]]:
    """Run one-shot (max_attempts=1) and self-correcting (max_attempts=3) repairs.

    Returns:
        (one_shot_rows, self_correcting_rows)
    """
    buggy = [s for s in snippets if not s.is_clean and s.test_code]

    print("\n[Experiment B] Repair: one-shot vs self-correcting")
    print("-" * 60)

    one_shot_rows: list[dict] = []
    self_correcting_rows: list[dict] = []

    for snippet in buggy:
        print(f"  One-shot   {snippet.id} ...", end=" ", flush=True)
        row1 = _run_repair_for_snippet(snippet, client, max_attempts=1, provider=provider)
        one_shot_rows.append(row1)
        print(f"status={row1['status']}  attempts={row1['attempts']}")

        print(f"  3-attempt  {snippet.id} ...", end=" ", flush=True)
        row3 = _run_repair_for_snippet(snippet, client, max_attempts=3, provider=provider)
        self_correcting_rows.append(row3)
        print(f"status={row3['status']}  attempts={row3['attempts']}")

    return one_shot_rows, self_correcting_rows


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("(no data)\n", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Chart helpers (matplotlib optional)
# ---------------------------------------------------------------------------

def _try_import_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        return None


def _save_filter_chart(
    filter_rows: list[dict],
    clean_rows: list[dict],
    out_dir: Path,
    provider: str,
) -> None:
    plt = _try_import_matplotlib()
    if plt is None:
        print("  [!] matplotlib not installed — skipping charts")
        return

    agg_on = aggregate_filter_metrics(
        [{"precision": r["precision_on"], "recall": r["recall_on"]} for r in filter_rows]
    )
    agg_off = aggregate_filter_metrics(
        [{"precision": r["precision_off"], "recall": r["recall_off"]} for r in filter_rows]
    )
    fp_rate_on = compute_false_positive_rate(clean_rows)
    fp_rate_off = compute_false_positive_rate(
        [{"kept_count": r["total_findings"]} for r in clean_rows]
    )

    labels = ["Precision", "Recall", "FP Rate"]
    on_vals = [agg_on["precision"], agg_on["recall"], fp_rate_on]
    off_vals = [agg_off["precision"], agg_off["recall"], fp_rate_off]

    x = range(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar([i - width / 2 for i in x], off_vals, width, label="Filter OFF", color="#e05c5c")
    ax.bar([i + width / 2 for i in x], on_vals, width, label="Filter ON", color="#5c9ee0")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Score")
    ax.set_title(f"Noise Filter: ON vs OFF  [provider={provider}]")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    chart_path = out_dir / "filter_chart.png"
    fig.savefig(str(chart_path), dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: {chart_path}")


def _save_repair_chart(
    one_shot: list[dict],
    self_corr: list[dict],
    out_dir: Path,
    provider: str,
) -> None:
    plt = _try_import_matplotlib()
    if plt is None:
        return

    m1 = compute_repair_metrics(one_shot)
    m3 = compute_repair_metrics(self_corr)

    labels = ["Success Rate", "Avg Attempts (norm.)"]
    # Normalise avg_attempts by max_attempts (1 and 3) for fair visual comparison
    v1 = [float(m1["success_rate"]), float(m1["avg_attempts"]) / 1.0]
    v3 = [float(m3["success_rate"]), float(m3["avg_attempts"]) / 3.0]

    x = range(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar([i - width / 2 for i in x], v1, width, label="One-shot (max=1)", color="#e09e5c")
    ax.bar([i + width / 2 for i in x], v3, width, label="Self-correcting (max=3)", color="#5ce07a")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Score")
    ax.set_title(f"Repair: One-shot vs Self-correcting  [provider={provider}]")
    ax.legend()
    ax.grid(axis="y", linestyle="--", alpha=0.5)

    chart_path = out_dir / "repair_chart.png"
    fig.savefig(str(chart_path), dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  Chart saved: {chart_path}")


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

_README_TEMPLATE = """\
# CodeInsight AI — Evaluation Results

## How to run

```bash
# Quick test with mock provider (first 3 snippets):
python evaluation/run_experiments.py --limit 3

# Full benchmark with a real provider:
python evaluation/run_experiments.py --provider openai_compat --sleep 3

# All options:
python evaluation/run_experiments.py --help
```

## Output files

| File | Description |
|---|---|
| `experiment_filter.csv` | Per-snippet filter precision/recall (ON vs OFF) |
| `experiment_repair.csv` | Per-snippet repair success (one-shot vs 3-attempt) |
| `filter_chart.png` | Bar chart: filter ON vs OFF metrics |
| `repair_chart.png` | Bar chart: repair one-shot vs self-correcting |

## Important: mock provider

When `--provider mock` (or `LLM_PROVIDER=mock`) is used, results are **synthetic
canned responses** and **do NOT reflect real LLM performance**. Mock mode is only
useful for testing the evaluation code itself (CI, offline development).

Use a real provider (`openai_compat` with `LLM_BASE_URL`/`LLM_API_KEY` set) for
meaningful benchmarks.

## Metrics

- **Precision**: fraction of kept findings that point at the known bug line (±2 lines).
- **Recall**: 1 if the known bug line was found in kept findings, else 0.
- **False Positive Rate**: fraction of clean snippets with >=1 kept finding.
- **Repair Success Rate**: fraction of snippets where the patched code passes its
  `test_code` suite (API errors are excluded from denominator).
"""


def _write_readme(out_dir: Path) -> None:
    readme_path = out_dir / "README.md"
    readme_path.write_text(_README_TEMPLATE, encoding="utf-8")
    print(f"  README written: {readme_path}")


# ---------------------------------------------------------------------------
# Summary table (plain ASCII for Windows terminals)
# ---------------------------------------------------------------------------

def _print_summary_table(
    filter_buggy: list[dict],
    filter_clean: list[dict],
    one_shot: list[dict],
    self_corr: list[dict],
    provider: str,
    total_calls: int,
) -> None:
    agg_on = aggregate_filter_metrics(
        [{"precision": r["precision_on"], "recall": r["recall_on"]} for r in filter_buggy]
    )
    agg_off = aggregate_filter_metrics(
        [{"precision": r["precision_off"], "recall": r["recall_off"]} for r in filter_buggy]
    )
    fp_on = compute_false_positive_rate(filter_clean)
    fp_off = compute_false_positive_rate(
        [{"kept_count": r["total_findings"]} for r in filter_clean]
    )
    m1 = compute_repair_metrics(one_shot)
    m3 = compute_repair_metrics(self_corr)

    print()
    print("=" * 65)
    print(f"  EVALUATION SUMMARY  [provider={provider}]")
    print("=" * 65)
    print()
    print("  [A] Noise Filter")
    print(f"      {'':20s} {'Filter OFF':>12}  {'Filter ON':>12}")
    print(f"      {'Precision':20s} {agg_off['precision']:>12.3f}  {agg_on['precision']:>12.3f}")
    print(f"      {'Recall':20s} {agg_off['recall']:>12.3f}  {agg_on['recall']:>12.3f}")
    print(f"      {'FP Rate (clean)':20s} {fp_off:>12.3f}  {fp_on:>12.3f}")
    print()
    print("  [B] Repair")
    print(f"      {'':20s} {'One-shot':>12}  {'3-attempt':>12}")
    print(f"      {'Success Rate':20s} {m1['success_rate']:>12.3f}  {m3['success_rate']:>12.3f}")
    print(f"      {'Avg Attempts':20s} {m1['avg_attempts']:>12.3f}  {m3['avg_attempts']:>12.3f}")
    print(f"      {'API Errors':20s} {m1['error_count']:>12}  {m3['error_count']:>12}")
    print()
    print(f"  LLM calls made: {total_calls}")
    print("=" * 65)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    _review_cache.clear()
    _review_errors.clear()

    args = _parse_args(argv)

    # Resolve provider
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    provider = os.environ.get("LLM_PROVIDER", "mock")

    # Mock honesty warning
    is_mock = provider == "mock"
    if is_mock:
        print()
        print("*" * 65)
        print("  WARNING: provider=mock")
        print("  Results are synthetic canned responses and are NOT real")
        print("  measurements of LLM capability. Use a real provider for")
        print("  meaningful evaluation results.")
        print("*" * 65)

    # Select snippets
    all_snippets = list(BENCHMARK)
    if args.limit is not None:
        from evaluation.benchmark import BUGGY_SNIPPETS, CLEAN_SNIPPETS
        buggy_limited = BUGGY_SNIPPETS[: args.limit]
        all_snippets = buggy_limited + CLEAN_SNIPPETS
        print(f"\nUsing first {args.limit} buggy snippet(s) + {len(CLEAN_SNIPPETS)} clean snippet(s).")
    else:
        print(f"\nUsing full benchmark: {sum(1 for s in all_snippets if not s.is_clean)} buggy "
              f"+ {sum(1 for s in all_snippets if s.is_clean)} clean snippets.")

    # Output dir
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build and wrap LLM client
    try:
        raw_client = get_client()
    except Exception as err:
        print(f"[FATAL] get_client() failed: {err}")
        sys.exit(1)

    sleep_s = args.sleep if not is_mock else 0.0  # no artificial delay for mock
    wrapped_client = TrackingRateLimitedClient(raw_client, sleep_s=sleep_s)

    # Run experiments
    filter_buggy, filter_clean = run_filter_experiment(all_snippets, wrapped_client, provider)
    one_shot, self_corr = run_repair_experiment(all_snippets, wrapped_client, provider)

    # Save CSVs
    filter_rows_combined = filter_buggy + [
        {
            "provider": r["provider"],
            "id": r["id"],
            "category": "clean",
            "known_bug_line": "",
            "total_findings": r["total_findings"],
            "kept_on": r["kept_count"],
            "kept_off": r["total_findings"],
            "precision_on": "",
            "recall_on": "",
            "precision_off": "",
            "recall_off": "",
        }
        for r in filter_clean
    ]
    _write_csv(out_dir / "experiment_filter.csv", filter_rows_combined)
    print(f"\n  Saved: {out_dir / 'experiment_filter.csv'}")

    repair_rows_combined = one_shot + self_corr
    _write_csv(out_dir / "experiment_repair.csv", repair_rows_combined)
    print(f"  Saved: {out_dir / 'experiment_repair.csv'}")

    # Charts
    _save_filter_chart(filter_buggy, filter_clean, out_dir, provider)
    _save_repair_chart(one_shot, self_corr, out_dir, provider)

    # README
    _write_readme(out_dir)

    # Summary table
    _print_summary_table(
        filter_buggy,
        filter_clean,
        one_shot,
        self_corr,
        provider,
        total_calls=wrapped_client.call_count,
    )


if __name__ == "__main__":
    main()
