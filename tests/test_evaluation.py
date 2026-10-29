"""Tests for the evaluation module (mock provider, fully offline).

Covers:
  - Benchmark dataset structure, fields, and counts
  - test_code fails on buggy code AND passes on fixed_code for all 12 snippets
  - LocalVerifier execution on fixed_code
  - Metrics functions on hand-crafted inputs (including API error exclusions)
  - run_experiments.main() smoke tests and call counting
"""

from __future__ import annotations

import csv as csv_mod
from pathlib import Path

import pytest

from evaluation.benchmark import (
    BENCHMARK,
    BUGGY_SNIPPETS,
    CLEAN_SNIPPETS,
    BenchmarkSnippet,
)
from evaluation.metrics import (
    aggregate_filter_metrics,
    compute_false_positive_rate,
    compute_filter_metrics,
    compute_repair_metrics,
)
from app.repair.local_verifier import LocalVerifier


# ---------------------------------------------------------------------------
# 1. Benchmark dataset structure
# ---------------------------------------------------------------------------

def test_benchmark_has_12_buggy_snippets():
    assert len(BUGGY_SNIPPETS) == 12, f"Expected 12, got {len(BUGGY_SNIPPETS)}"


def test_benchmark_has_3_clean_snippets():
    assert len(CLEAN_SNIPPETS) == 3, f"Expected 3, got {len(CLEAN_SNIPPETS)}"


def test_benchmark_total_is_15():
    assert len(BENCHMARK) == 15


def test_all_buggy_snippets_have_required_fields():
    for s in BUGGY_SNIPPETS:
        assert s.id, f"Missing id: {s}"
        assert s.code, f"Missing code: {s.id}"
        assert s.fixed_code, f"Missing fixed_code: {s.id}"
        assert s.known_bug_line is not None, f"Missing known_bug_line: {s.id}"
        assert s.known_bug_line >= 1, f"Invalid known_bug_line: {s.id}"
        assert s.category in ("bug", "security", "logic", "performance"), \
            f"Invalid category '{s.category}': {s.id}"
        assert s.test_code, f"Missing test_code: {s.id}"
        assert not s.is_clean


def test_all_clean_snippets_have_required_fields():
    for s in CLEAN_SNIPPETS:
        assert s.id, f"Missing id: {s}"
        assert s.code, f"Missing code: {s.id}"
        assert s.known_bug_line is None, f"Clean snippet should have None known_bug_line: {s.id}"
        assert s.is_clean


def test_snippet_ids_are_unique():
    ids = [s.id for s in BENCHMARK]
    assert len(ids) == len(set(ids)), "Duplicate snippet IDs found"


def test_buggy_snippets_cover_multiple_categories():
    cats = {s.category for s in BUGGY_SNIPPETS}
    assert len(cats) >= 3, f"Expected >=3 categories, got: {cats}"


# ---------------------------------------------------------------------------
# 2. test_code FAILS on buggy code and PASSES on fixed_code (all 12 snippets)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("snippet", BUGGY_SNIPPETS, ids=lambda s: s.id)
def test_test_code_fails_on_buggy_code(snippet: BenchmarkSnippet):
    """The bundled test_code must FAIL on the buggy code."""
    verifier = LocalVerifier(test_code=snippet.test_code)
    res = verifier.verify(snippet.code, file_path="snippet.py")
    assert not res.passed, (
        f"test_code for '{snippet.id}' unexpectedly PASSED on buggy code. "
        "The test must reject buggy behavior."
    )


@pytest.mark.parametrize("snippet", BUGGY_SNIPPETS, ids=lambda s: s.id)
def test_test_code_passes_on_fixed_code(snippet: BenchmarkSnippet):
    """LocalVerifier on fixed_code must return passed=True for all snippets."""
    verifier = LocalVerifier(test_code=snippet.test_code)
    res = verifier.verify(snippet.fixed_code, file_path="snippet.py")  # type: ignore[arg-type]
    assert res.passed, (
        f"LocalVerifier on fixed_code for '{snippet.id}' failed at stage '{res.stage}':\n"
        f"Error: {res.error}\n"
        f"Output:\n{res.output}"
    )


# ---------------------------------------------------------------------------
# 3. Metrics on hand-crafted inputs
# ---------------------------------------------------------------------------

class TestComputeFilterMetrics:
    def test_exact_hit(self):
        m = compute_filter_metrics(kept_lines=[5], known_bug_line=5)
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0

    def test_within_tolerance(self):
        m = compute_filter_metrics(kept_lines=[7], known_bug_line=5, tolerance=2)
        assert m["recall"] == 1.0

    def test_outside_tolerance(self):
        m = compute_filter_metrics(kept_lines=[10], known_bug_line=5, tolerance=2)
        assert m["recall"] == 0.0
        assert m["precision"] == 0.0

    def test_empty_kept_lines(self):
        m = compute_filter_metrics(kept_lines=[], known_bug_line=5)
        assert m["precision"] == 0.0
        assert m["recall"] == 0.0

    def test_precision_partial(self):
        m = compute_filter_metrics(kept_lines=[5, 20, 30], known_bug_line=5)
        assert abs(m["precision"] - 1 / 3) < 1e-6
        assert m["recall"] == 1.0

    def test_multiple_hits_clamp_recall_at_1(self):
        m = compute_filter_metrics(kept_lines=[4, 5, 6], known_bug_line=5, tolerance=1)
        assert m["recall"] == 1.0
        assert m["precision"] == 1.0


class TestAggregate:
    def test_empty(self):
        m = aggregate_filter_metrics([])
        assert m["precision"] == 0.0
        assert m["recall"] == 0.0

    def test_average(self):
        rows = [
            {"precision": 1.0, "recall": 1.0},
            {"precision": 0.0, "recall": 0.0},
        ]
        m = aggregate_filter_metrics(rows)
        assert abs(m["precision"] - 0.5) < 1e-6
        assert abs(m["recall"] - 0.5) < 1e-6


class TestFalsePositiveRate:
    def test_no_false_positives(self):
        rows = [{"kept_count": 0}, {"kept_count": 0}]
        assert compute_false_positive_rate(rows) == 0.0

    def test_all_false_positives(self):
        rows = [{"kept_count": 2}, {"kept_count": 1}]
        assert compute_false_positive_rate(rows) == 1.0

    def test_partial(self):
        rows = [{"kept_count": 1}, {"kept_count": 0}, {"kept_count": 0}]
        assert compute_false_positive_rate(rows) == pytest.approx(1 / 3, abs=1e-4)

    def test_empty(self):
        assert compute_false_positive_rate([]) == 0.0


class TestRepairMetrics:
    def test_all_verified(self):
        rows = [{"status": "verified", "attempts": 1}, {"status": "verified", "attempts": 2}]
        m = compute_repair_metrics(rows)
        assert m["success_rate"] == 1.0
        assert abs(m["avg_attempts"] - 1.5) < 1e-6
        assert m["error_count"] == 0

    def test_none_verified(self):
        rows = [{"status": "failed", "attempts": 3}, {"status": "failed", "attempts": 3}]
        m = compute_repair_metrics(rows)
        assert m["success_rate"] == 0.0
        assert m["avg_attempts"] == 3.0
        assert m["error_count"] == 0

    def test_partial(self):
        rows = [
            {"status": "verified", "attempts": 1},
            {"status": "failed", "attempts": 3},
        ]
        m = compute_repair_metrics(rows)
        assert m["success_rate"] == 0.5
        assert m["error_count"] == 0

    def test_api_errors_excluded_from_success_rate(self):
        """API errors (status='error') must be excluded from success rate denominator."""
        rows = [
            {"status": "verified", "attempts": 1},
            {"status": "failed", "attempts": 3},
            {"status": "error", "attempts": 1, "error": "429 Too Many Requests"},
            {"status": "error", "attempts": 1, "error": "Connection timeout"},
        ]
        m = compute_repair_metrics(rows)
        # 1 verified out of 2 valid non-error attempts = 50%
        assert m["success_rate"] == 0.5
        assert m["error_count"] == 2
        assert m["valid_count"] == 2

    def test_all_errors(self):
        rows = [{"status": "error", "attempts": 1}]
        m = compute_repair_metrics(rows)
        assert m["success_rate"] == 0.0
        assert m["error_count"] == 1
        assert m["valid_count"] == 0

    def test_empty(self):
        m = compute_repair_metrics([])
        assert m["success_rate"] == 0.0
        assert m["avg_attempts"] == 0.0
        assert m["error_count"] == 0


# ---------------------------------------------------------------------------
# 4. run_experiments smoke test (mock provider, --limit 1)
# ---------------------------------------------------------------------------

def test_run_experiments_smoke(tmp_path):
    """Smoke-test run_experiments.main() with mock provider and --limit 1."""
    import evaluation.run_experiments as exp

    exp._review_cache.clear()
    exp.main(["--limit", "1", "--provider", "mock", "--sleep", "0", "--out", str(tmp_path)])

    assert (tmp_path / "experiment_filter.csv").exists()
    assert (tmp_path / "experiment_repair.csv").exists()
    assert (tmp_path / "README.md").exists()


def test_filter_csv_has_correct_columns(tmp_path):
    """The filter CSV must contain the expected columns."""
    import evaluation.run_experiments as exp

    exp._review_cache.clear()
    exp.main(["--limit", "1", "--provider", "mock", "--sleep", "0", "--out", str(tmp_path)])

    csv_path = tmp_path / "experiment_filter.csv"
    with csv_path.open(encoding="utf-8") as f:
        reader = csv_mod.DictReader(f)
        fieldnames = reader.fieldnames or []

    for col in ("provider", "id", "precision_on", "recall_on", "precision_off", "recall_off"):
        assert col in fieldnames, f"Missing column '{col}' in filter CSV"


def test_repair_csv_has_correct_columns(tmp_path):
    """The repair CSV must contain status, verified, attempts, and error columns."""
    import evaluation.run_experiments as exp

    exp._review_cache.clear()
    exp.main(["--limit", "1", "--provider", "mock", "--sleep", "0", "--out", str(tmp_path)])

    csv_path = tmp_path / "experiment_repair.csv"
    with csv_path.open(encoding="utf-8") as f:
        reader = csv_mod.DictReader(f)
        fieldnames = reader.fieldnames or []

    for col in ("provider", "id", "max_attempts", "status", "verified", "attempts", "error"):
        assert col in fieldnames, f"Missing column '{col}' in repair CSV"
