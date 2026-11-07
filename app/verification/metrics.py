"""Evaluation metrics for CodeInsight-AI verification runs."""

from collections.abc import Iterable, Mapping
import math
from typing import Any


_RUN_STATUSES = {"passed", "failed"}


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

    passed_runs = 0
    durations = []

    for index, report in enumerate(reports):
        if not isinstance(report, Mapping):
            raise TypeError(f"Report {index} must be a mapping.")

        status = report.get("status")
        if not isinstance(status, str) or status not in _RUN_STATUSES:
            raise ValueError(
                f"Report {index} has unsupported status {status!r}; "
                f"expected one of {sorted(_RUN_STATUSES)}."
            )
        passed_runs += status == "passed"

        checks = report.get("checks", {})
        if not isinstance(checks, Mapping):
            raise TypeError(f"Report {index} checks must be a mapping.")

        test_result = checks.get("tests", {})
        if not isinstance(test_result, Mapping):
            raise TypeError(f"Report {index} tests check must be a mapping.")
        duration = test_result.get("duration_seconds")

        if duration is None:
            duration = report.get("duration_seconds")
        if duration is not None:
            if (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or duration < 0
            ):
                raise ValueError(
                    f"Report {index} has invalid duration {duration!r}; "
                    "duration must be a finite non-negative number."
                )
            try:
                duration_value = float(duration)
            except OverflowError as exc:
                raise ValueError(
                    f"Report {index} has invalid duration {duration!r}; "
                    "duration must be a finite non-negative number."
                ) from exc
            if not math.isfinite(duration_value):
                raise ValueError(
                    f"Report {index} has invalid duration {duration!r}; "
                    "duration must be a finite non-negative number."
                )
            durations.append(duration_value)

    failed_runs = total_runs - passed_runs
    if durations:
        duration_sum = sum(durations)
        if math.isfinite(duration_sum):
            average_duration = duration_sum / len(durations)
        else:
            scale = max(durations)
            scaled_average = math.fsum(
                duration / scale for duration in durations
            ) / len(durations)
            average_duration = min(scaled_average, 1.0) * scale

        if not math.isfinite(average_duration):
            raise ValueError(
                "Average duration cannot be represented as a finite float."
            )
    else:
        average_duration = 0.0

    return {
        "total_runs": total_runs,
        "passed_runs": passed_runs,
        "failed_runs": failed_runs,
        "pass_rate": round(passed_runs / total_runs * 100, 2) if total_runs else 0.0,
        "failure_rate": (
            round(failed_runs / total_runs * 100, 2) if total_runs else 0.0
        ),
        "average_duration_seconds": round(average_duration, 3),
    }