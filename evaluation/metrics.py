"""Metric helpers for evaluation experiments.

All functions operate on plain Python dicts / lists so they are easy to test.
"""

from __future__ import annotations


def compute_filter_metrics(
    kept_lines: list[int],
    known_bug_line: int,
    tolerance: int = 2,
) -> dict[str, float]:
    """Compute precision/recall for a single snippet's filter result.

    Args:
        kept_lines: 1-indexed line numbers of all kept findings.
        known_bug_line: The ground-truth bug line for this snippet.
        tolerance: A finding within ±tolerance lines of known_bug_line counts as a hit.

    Returns:
        dict with keys 'precision' and 'recall' (floats 0..1).
    """
    if not kept_lines:
        return {"precision": 0.0, "recall": 0.0}

    hits = sum(
        1
        for ln in kept_lines
        if abs(ln - known_bug_line) <= tolerance
    )
    precision = hits / len(kept_lines)
    recall = 1.0 if hits > 0 else 0.0
    return {"precision": precision, "recall": recall}


def aggregate_filter_metrics(rows: list[dict]) -> dict[str, float]:
    """Average precision and recall across all snippet rows.

    Each row must have 'precision' and 'recall' float keys.
    """
    if not rows:
        return {"precision": 0.0, "recall": 0.0}
    avg_p = sum(r["precision"] for r in rows) / len(rows)
    avg_r = sum(r["recall"] for r in rows) / len(rows)
    return {"precision": round(avg_p, 4), "recall": round(avg_r, 4)}


def compute_false_positive_rate(clean_rows: list[dict]) -> float:
    """Fraction of clean snippets that had at least one kept finding (false positive).

    Args:
        clean_rows: Each row must have a 'kept_count' int key.
    """
    if not clean_rows:
        return 0.0
    fp_count = sum(1 for r in clean_rows if r.get("kept_count", 0) > 0)
    return round(fp_count / len(clean_rows), 4)


def compute_repair_metrics(repair_rows: list[dict]) -> dict[str, float | int]:
    """Compute repair success rate for one-shot vs self-correcting experiments.

    API errors (status="error") are excluded from the success rate denominator
    and tracked separately under 'error_count'.

    Args:
        repair_rows: Each row may have 'status' ("verified" | "failed" | "error"),
                     'verified' (bool), and optionally 'attempts' (int).

    Returns:
        dict with 'success_rate', 'avg_attempts', 'error_count', and 'valid_count'.
    """
    if not repair_rows:
        return {"success_rate": 0.0, "avg_attempts": 0.0, "error_count": 0, "valid_count": 0}

    error_count = sum(1 for r in repair_rows if r.get("status") == "error")
    valid_rows = [r for r in repair_rows if r.get("status") != "error"]

    if not valid_rows:
        return {
            "success_rate": 0.0,
            "avg_attempts": 0.0,
            "error_count": error_count,
            "valid_count": 0,
        }

    successes = sum(
        1 for r in valid_rows
        if r.get("status") == "verified" or (r.get("status") is None and r.get("verified", False))
    )
    avg_attempts = sum(r.get("attempts", 1) for r in valid_rows) / len(valid_rows)
    return {
        "success_rate": round(successes / len(valid_rows), 4),
        "avg_attempts": round(avg_attempts, 4),
        "error_count": error_count,
        "valid_count": len(valid_rows),
    }
