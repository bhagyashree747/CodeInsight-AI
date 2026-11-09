"""Scorer module computing relevance scores for review findings."""

from dataclasses import dataclass
from app.review.schema import Finding, Severity


@dataclass(frozen=True)
class ScoreWeights:
    """Configurable weights for computing composite relevance score."""

    confidence_weight: float = 0.35
    severity_weight: float = 0.35
    actionability_weight: float = 0.15
    on_diff_weight: float = 0.15


DEFAULT_WEIGHTS = ScoreWeights()

SEVERITY_SCORES: dict[Severity | str, float] = {
    Severity.HIGH: 1.0,
    Severity.MEDIUM: 0.6,
    Severity.LOW: 0.3,
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}


def score(
    finding: Finding,
    changed_lines: set[int] | None = None,
    weights: ScoreWeights | None = None,
) -> float:
    """Compute a composite score from 0.0 to 1.0 for a given finding.

    Factors evaluated:
    - Confidence: finding.confidence (0.0 .. 1.0)
    - Severity: high=1.0, medium=0.6, low=0.3
    - Actionability: 1.0 if actionable else 0.0
    - Diff location: 1.0 if on diff (or if changed_lines is None), else 0.0

    Args:
        finding: The Finding to score.
        changed_lines: Optional set of 1-indexed lines modified in PR diff.
        weights: Optional ScoreWeights. Defaults to DEFAULT_WEIGHTS.

    Returns:
        A float value bounded between 0.0 and 1.0.
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS

    # 1. Severity factor
    sev = finding.severity
    sev_key = sev.value if hasattr(sev, "value") else str(sev).lower()
    sev_factor = SEVERITY_SCORES.get(sev_key, 0.5)

    # 2. Confidence factor
    conf_factor = max(0.0, min(1.0, float(finding.confidence)))

    # 3. Actionability factor
    act_factor = 1.0 if finding.actionable else 0.0

    # 4. On-diff factor: If changed_lines is None, full scope applies (1.0).
    if changed_lines is None:
        diff_factor = 1.0
    else:
        diff_factor = 1.0 if finding.line in changed_lines else 0.0

    total_weight = (
        w.confidence_weight
        + w.severity_weight
        + w.actionability_weight
        + w.on_diff_weight
    )

    if total_weight <= 0:
        return 0.0

    raw_score = (
        (w.confidence_weight * conf_factor)
        + (w.severity_weight * sev_factor)
        + (w.actionability_weight * act_factor)
        + (w.on_diff_weight * diff_factor)
    )

    final_score = raw_score / total_weight
    return round(max(0.0, min(1.0, final_score)), 4)
