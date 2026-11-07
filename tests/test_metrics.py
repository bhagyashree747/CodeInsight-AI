"""Tests for CodeInsight-AI evaluation metrics."""

import pytest

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


@pytest.mark.parametrize("bad_status", ["skipped", None, 1, []])
def test_unknown_or_malformed_status_is_rejected(bad_status) -> None:
    with pytest.raises(ValueError, match="unsupported status"):
        calculate_verification_metrics([{"status": bad_status}])


@pytest.mark.parametrize("bad_duration", [-1, True, float("nan"), float("inf"), "2"])
def test_invalid_duration_is_rejected(bad_duration) -> None:
    with pytest.raises(ValueError, match="invalid duration"):
        calculate_verification_metrics([
            {"status": "passed", "duration_seconds": bad_duration}
        ])


def test_malformed_report_and_checks_are_rejected() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        calculate_verification_metrics(["not a report"])

    with pytest.raises(TypeError, match="checks must be a mapping"):
        calculate_verification_metrics([{"status": "passed", "checks": []}])

    with pytest.raises(TypeError, match="tests check must be a mapping"):
        calculate_verification_metrics([
            {"status": "passed", "checks": {"tests": []}}
        ])


def test_report_duration_is_used_when_test_duration_is_missing() -> None:
    result = calculate_verification_metrics([
        {"status": "passed", "duration_seconds": 1.25}
    ])

    assert result["average_duration_seconds"] == 1.25


def test_zero_second_duration_is_valid() -> None:
    result = calculate_verification_metrics([
        {"status": "passed", "duration_seconds": 0}
    ])

    assert result["average_duration_seconds"] == 0.0


def test_test_check_duration_takes_priority_over_report_duration() -> None:
    result = calculate_verification_metrics([
        {
            "status": "passed",
            "checks": {"tests": {"duration_seconds": 2.5}},
            "duration_seconds": 8.0,
        }
    ])

    assert result["average_duration_seconds"] == 2.5


def test_negative_infinity_duration_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid duration"):
        calculate_verification_metrics([
            {"status": "passed", "duration_seconds": float("-inf")}
        ])


def test_iterator_of_reports_is_supported() -> None:
    reports = iter([
        {"status": "passed", "duration_seconds": 1.0},
        {"status": "failed", "duration_seconds": 3.0},
    ])

    result = calculate_verification_metrics(reports)

    assert result["total_runs"] == 2
    assert result["passed_runs"] == 1
    assert result["failed_runs"] == 1
    assert result["pass_rate"] == 50.0
    assert result["failure_rate"] == 50.0
    assert result["average_duration_seconds"] == 2.0


def test_large_finite_durations_do_not_overflow_average() -> None:
    result = calculate_verification_metrics([
        {"status": "passed", "duration_seconds": 1e308},
        {"status": "failed", "duration_seconds": 1e308},
    ])

    assert result["average_duration_seconds"] == 1e308


def test_average_of_maximum_finite_durations_remains_finite() -> None:
    import sys

    maximum_float = sys.float_info.max
    result = calculate_verification_metrics([
        {"status": "passed", "duration_seconds": maximum_float},
        {"status": "passed", "duration_seconds": maximum_float},
    ])

    assert result["average_duration_seconds"] == maximum_float