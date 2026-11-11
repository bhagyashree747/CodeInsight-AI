"""Relevance and filtering module for CodeInsight AI."""

from app.relevance.filter import DiscardedFinding, FilterResult, ScoredFinding, filter_findings
from app.relevance.rules import (
    RelevanceConfig,
    check_actionable,
    check_changed_lines,
    check_confidence,
    check_not_duplicate,
    check_not_style,
)
from app.relevance.scorer import DEFAULT_WEIGHTS, ScoreWeights, score

__all__ = [
    "DEFAULT_WEIGHTS",
    "DiscardedFinding",
    "FilterResult",
    "RelevanceConfig",
    "ScoreWeights",
    "ScoredFinding",
    "check_actionable",
    "check_changed_lines",
    "check_confidence",
    "check_not_duplicate",
    "check_not_style",
    "filter_findings",
    "score",
]
