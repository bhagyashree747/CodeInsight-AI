"""Tests for CodeInsight-AI evaluation metrics."""

from app.verification.metrics import calculate_verification_metrics


def test_metrics_for_mixed_results() -> None:
    """Calculate correct rates for passed and failed reports."""
    reports = [
        {
            "status": "passed",
            "checks": {
                "tests": {
                    "duration_seconds": 2.0,
                }
            },
        },
        {
            "status": "failed",
            "checks": {
                "tests": {
                    "duration_seconds": 4.0,
                }
            },
        },
    ]

    result = calculate_verification_metrics(reports)

    assert result["total_runs"] == 2
    assert result["passed_runs"] == 1
    assert result["failed_runs"] == 1
    assert result["pass_rate"] == 50.0
    assert result["failure_rate"] == 50.0
    assert result["average_duration_seconds"] == 3.0


def test_metrics_when_every_run_passes() -> None:
    """A fully successful set should have a 100% pass rate."""
    reports = [
        {"status": "passed", "checks": {}},
        {"status": "passed", "checks": {}},
    ]

    result = calculate_verification_metrics(reports)

    assert result["total_runs"] == 2
    assert result["passed_runs"] == 2
    assert result["failed_runs"] == 0
    assert result["pass_rate"] == 100.0
    assert result["failure_rate"] == 0.0


def test_empty_results() -> None:
    """An empty collection should return safe zero values."""
    result = calculate_verification_metrics([])

    assert result["total_runs"] == 0
    assert result["passed_runs"] == 0
    assert result["failed_runs"] == 0
    assert result["pass_rate"] == 0.0
    assert result["failure_rate"] == 0.0
    assert result["average_duration_seconds"] == 0.0


def test_missing_duration_is_ignored() -> None:
    """Missing duration values should not break metric calculation."""
    reports = [
        {
            "status": "passed",
            "checks": {
                "tests": {
                    "duration_seconds": 2.5,
                }
            },
        },
        {
            "status": "failed",
            "checks": {},
        },
    ]

    result = calculate_verification_metrics(reports)

    assert result["total_runs"] == 2
    assert result["average_duration_seconds"] == 2.5