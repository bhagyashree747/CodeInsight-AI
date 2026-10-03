"""Tests for the relevance module (rules, scorer, and filter)."""

import pytest

from app.relevance.filter import filter_findings
from app.relevance.rules import RelevanceConfig
from app.relevance.scorer import ScoreWeights, score
from app.review.schema import Category, Finding, Severity


def create_finding(
    file: str = "app/main.py",
    line: int = 10,
    category: str = "bug",
    severity: str = "high",
    confidence: float = 0.9,
    description: str = "Definite bug in business logic",
    suggested_fix_hint: str = "Fix line",
    actionable: bool = True,
) -> Finding:
    return Finding(
        file=file,
        line=line,
        category=category,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        confidence=confidence,
        description=description,
        suggested_fix_hint=suggested_fix_hint,
        actionable=actionable,
    )


# --- Relevance Filtering Tests ---

def test_low_confidence_discarded():
    finding = create_finding(confidence=0.3)
    result = filter_findings([finding])

    assert result.kept_count == 0
    assert result.discarded_count == 1
    assert "below minimum threshold" in result.discarded[0].reason


def test_style_only_discarded():
    style_finding = create_finding(
        description="Improve naming convention to match PEP8 snake_case style",
        confidence=0.9,
    )
    result = filter_findings([style_finding])

    assert result.kept_count == 0
    assert result.discarded_count == 1
    assert "Style-only" in result.discarded[0].reason


def test_off_diff_discarded():
    finding = create_finding(line=15)
    # Changed lines are only 10, 11
    result = filter_findings([finding], changed_lines={10, 11})

    assert result.kept_count == 0
    assert result.discarded_count == 1
    assert "outside changed lines" in result.discarded[0].reason


def test_duplicates_removed():
    f1 = create_finding(file="main.py", line=10, category="bug", description="First finding")
    f2 = create_finding(file="main.py", line=10, category="bug", description="Duplicate finding")

    result = filter_findings([f1, f2])

    assert result.kept_count == 1
    assert result.discarded_count == 1
    assert result.kept[0].description == "First finding"
    assert "Duplicate finding" in result.discarded[0].reason


def test_output_sorted_by_score():
    f_high = create_finding(
        line=1,
        severity="high",
        confidence=0.95,
        description="High severity critical defect",
    )
    f_med = create_finding(
        line=2,
        severity="medium",
        confidence=0.75,
        description="Medium severity defect",
    )
    f_low = create_finding(
        line=3,
        severity="low",
        confidence=0.55,
        description="Low severity minor defect",
    )

    # Pass in unsorted order
    result = filter_findings([f_low, f_high, f_med])

    assert result.kept_count == 3
    scores = [sf.score for sf in result.kept]
    # Check that scores are monotonically decreasing
    assert scores == sorted(scores, reverse=True)
    assert result.kept[0].line == 1  # high severity was highest
    assert result.kept[1].line == 2  # med
    assert result.kept[2].line == 3  # low


def test_non_actionable_discarded():
    finding = create_finding(actionable=False, description="Issue with no practical fix")
    result = filter_findings([finding])

    assert result.kept_count == 0
    assert result.discarded_count == 1
    assert "non-actionable" in result.discarded[0].reason


# --- Scorer Tests ---

def test_scorer_bounds_and_factors():
    f_high = create_finding(severity="high", confidence=1.0, actionable=True, line=5)
    f_low = create_finding(severity="low", confidence=0.5, actionable=False, line=5)

    score_high = score(f_high, changed_lines={5})
    score_low = score(f_low, changed_lines={5})

    assert 0.0 <= score_high <= 1.0
    assert 0.0 <= score_low <= 1.0
    assert score_high > score_low


def test_scorer_on_diff_vs_off_diff():
    f = create_finding(line=5)
    score_on_diff = score(f, changed_lines={5})
    score_off_diff = score(f, changed_lines={10})

    assert score_on_diff > score_off_diff
