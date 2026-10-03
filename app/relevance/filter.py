"""Filter findings based on relevance rules and scoring."""

from typing import Any
from pydantic import BaseModel, Field
from app.relevance.rules import (
    RelevanceConfig,
    check_actionable,
    check_changed_lines,
    check_confidence,
    check_not_duplicate,
    check_not_style,
)
from app.relevance.scorer import ScoreWeights, score
from app.review.schema import Category, Finding, Severity


class ScoredFinding(BaseModel):
    """A finding that passed relevance filters and received a relevance score."""

    finding: Finding
    score: float = Field(..., ge=0.0, le=1.0, description="Composite relevance score")

    # Delegate core finding attributes for convenience and backward compatibility
    @property
    def file(self) -> str:
        return self.finding.file

    @property
    def line(self) -> int:
        return self.finding.line

    @property
    def category(self) -> Category:
        return self.finding.category

    @property
    def severity(self) -> Severity:
        return self.finding.severity

    @property
    def confidence(self) -> float:
        return self.finding.confidence

    @property
    def description(self) -> str:
        return self.finding.description

    @property
    def suggested_fix_hint(self) -> str:
        return self.finding.suggested_fix_hint

    @property
    def actionable(self) -> bool:
        return self.finding.actionable


class DiscardedFinding(BaseModel):
    """A finding filtered out by relevance rules along with the rejection reason."""

    finding: Finding
    reason: str = Field(..., description="Explanation of why this finding was discarded")

    @property
    def file(self) -> str:
        return self.finding.file

    @property
    def line(self) -> int:
        return self.finding.line

    @property
    def category(self) -> Category:
        return self.finding.category

    @property
    def description(self) -> str:
        return self.finding.description


class FilterResult(BaseModel):
    """Result of relevance filtering containing kept, discarded, and summary counts."""

    kept: list[ScoredFinding] = Field(default_factory=list, description="Findings that passed all filters, sorted by score descending")
    discarded: list[DiscardedFinding] = Field(default_factory=list, description="Findings rejected by filters")
    kept_count: int = Field(default=0, description="Total count of kept findings")
    discarded_count: int = Field(default=0, description="Total count of discarded findings")
    total_count: int = Field(default=0, description="Total count of evaluated findings")

    @property
    def summary(self) -> str:
        return f"{self.kept_count} useful, {self.discarded_count} filtered as noise"


def filter_findings(
    findings: list[Finding],
    changed_lines: set[int] | None = None,
    config: RelevanceConfig | None = None,
    weights: ScoreWeights | None = None,
) -> FilterResult:
    """Filter raw findings using relevance rules and score the remaining findings.

    Filtering rules applied in order:
    1. Duplicate check (same file + line + category)
    2. Actionability check (must be actionable)
    3. Minimum confidence check (confidence >= min_confidence)
    4. Changed lines check (if changed_lines specified, finding must be on changed lines)
    5. Style / nitpick check (reject purely cosmetic or naming findings)

    Args:
        findings: List of Finding instances from code review.
        changed_lines: Optional set of 1-indexed line numbers modified in PR diff.
        config: Optional RelevanceConfig. Defaults to standard configuration.
        weights: Optional ScoreWeights for relevance scoring.

    Returns:
        FilterResult with kept (scored and sorted descending) and discarded findings.
    """
    cfg = config or RelevanceConfig()
    seen_keys: set[tuple[str, int, str]] = set()

    kept: list[ScoredFinding] = []
    discarded: list[DiscardedFinding] = []

    for finding in findings:
        # Rule 1: Duplicate check
        ok, reason = check_not_duplicate(finding, seen_keys, cfg)
        if not ok:
            discarded.append(DiscardedFinding(finding=finding, reason=reason))
            continue

        cat_str = finding.category.value if hasattr(finding.category, "value") else str(finding.category)
        seen_keys.add((finding.file, finding.line, cat_str.lower()))

        # Rule 2: Actionable check
        ok, reason = check_actionable(finding, cfg)
        if not ok:
            discarded.append(DiscardedFinding(finding=finding, reason=reason))
            continue

        # Rule 3: Minimum confidence threshold
        ok, reason = check_confidence(finding, cfg)
        if not ok:
            discarded.append(DiscardedFinding(finding=finding, reason=reason))
            continue

        # Rule 4: Changed lines diff constraint
        ok, reason = check_changed_lines(finding, changed_lines, cfg)
        if not ok:
            discarded.append(DiscardedFinding(finding=finding, reason=reason))
            continue

        # Rule 5: Style / cosmetic nitpicks
        ok, reason = check_not_style(finding, cfg)
        if not ok:
            discarded.append(DiscardedFinding(finding=finding, reason=reason))
            continue

        # All checks passed: compute relevance score
        f_score = score(finding, changed_lines=changed_lines, weights=weights)
        kept.append(ScoredFinding(finding=finding, score=f_score))

    # Sort kept findings by score descending
    kept.sort(key=lambda sf: sf.score, reverse=True)

    return FilterResult(
        kept=kept,
        discarded=discarded,
        kept_count=len(kept),
        discarded_count=len(discarded),
        total_count=len(findings),
    )
