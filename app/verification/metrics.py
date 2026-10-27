"""Evaluation metrics for CodeInsight-AI verification runs."""

from collections.abc import Iterable, Mapping
from typing import Any


def calculate_verification_metrics(
    results: Iterable[Mapping[str, Any]],
) -> dict:
    """
    Calculate aggregate metrics from verification reports.

    Each result should follow the structure returned by
    app.verification.runner.run_verification().
    """
    reports = list(results)
    total_runs = len(reports)

    if total_runs == 0:
        return {
            "total_runs": 0,
            "passed_runs": 0,
            "failed_runs": 0,
            "pass_rate": 0.0,
            "failure_rate": 0.0,
            "average_duration_seconds": 0.0,
        }

    passed_runs = sum(
        report.get("status") == "passed"
        for report in reports
    )
    failed_runs = total_runs - passed_runs

    durations = []

    for report in reports:
        checks = report.get("checks", {})

        # Prefer the test-runner duration when available.
        test_result = checks.get("tests", {})
        duration = test_result.get("duration_seconds")

        if duration is None:
            duration = report.get("duration_seconds")

        if isinstance(duration, (int, float)) and not isinstance(
            duration, bool
        ):
            if duration >= 0:
                durations.append(float(duration))

    average_duration = (
        sum(durations) / len(durations)
        if durations
        else 0.0
    )

    return {
        "total_runs": total_runs,
        "passed_runs": passed_runs,
        "failed_runs": failed_runs,
        "pass_rate": round(passed_runs / total_runs * 100, 2),
        "failure_rate": round(failed_runs / total_runs * 100, 2),
        "average_duration_seconds": round(average_duration, 3),
    }