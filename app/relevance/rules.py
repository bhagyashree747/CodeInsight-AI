"""Relevance rules and thresholds for filtering review findings."""

from dataclasses import dataclass, field
import re
from app.review.schema import Finding


@dataclass(frozen=True)
class RelevanceConfig:
    """Configurable thresholds and parameters for relevance filtering."""

    min_confidence: float = 0.5
    require_actionable: bool = True
    style_keywords: tuple[str, ...] = (
        "naming",
        "docstring",
        "formatting",
        "style",
        "whitespace",
        "indentation",
        "pep8",
        "typo",
        "spelling",
        "convention",
        "casing",
        "camelcase",
        "snake_case",
    )


def check_confidence(
    finding: Finding,
    config: RelevanceConfig = RelevanceConfig(),
) -> tuple[bool, str]:
    """Check if finding confidence meets or exceeds the minimum threshold."""
    if finding.confidence < config.min_confidence:
        return (
            False,
            f"Confidence {finding.confidence:.2f} is below minimum threshold {config.min_confidence:.2f}",
        )
    return True, "Confidence threshold met"


def check_actionable(
    finding: Finding,
    config: RelevanceConfig = RelevanceConfig(),
) -> tuple[bool, str]:
    """Check if finding is actionable."""
    if config.require_actionable and not finding.actionable:
        return False, "Finding marked as non-actionable"
    return True, "Actionable check passed"


def check_not_style(
    finding: Finding,
    config: RelevanceConfig = RelevanceConfig(),
) -> tuple[bool, str]:
    """Check if finding description is a style/formatting nitpick rather than a substantive defect."""
    desc_lower = finding.description.lower()

    for kw in config.style_keywords:
        # Match as whole word to avoid false positives
        pattern = rf"\b{re.escape(kw.lower())}\b"
        if re.search(pattern, desc_lower):
            return False, f"Style-only finding (matched keyword: '{kw}')"

    return True, "Substantive issue check passed"


def check_changed_lines(
    finding: Finding,
    changed_lines: set[int] | None = None,
    config: RelevanceConfig = RelevanceConfig(),
) -> tuple[bool, str]:
    """Check if finding references a line modified in the PR diff (if diff lines provided)."""
    if changed_lines is not None and finding.line not in changed_lines:
        return False, f"Line {finding.line} is outside changed lines in PR diff"
    return True, "Line is on diff or diff was not restricted"


def check_not_duplicate(
    finding: Finding,
    seen_keys: set[tuple[str, int, str]],
    config: RelevanceConfig = RelevanceConfig(),
) -> tuple[bool, str]:
    """Check if finding is a duplicate of a previously seen finding (file + line + category)."""
    cat_str = finding.category.value if hasattr(finding.category, "value") else str(finding.category)
    key = (finding.file, finding.line, cat_str.lower())
    if key in seen_keys:
        return False, f"Duplicate finding for {finding.file}:{finding.line} ({cat_str})"
    return True, "Not a duplicate"


# Convenience aliases
rule_min_confidence = check_confidence
rule_actionable = check_actionable
rule_not_style = check_not_style
rule_changed_lines = check_changed_lines
rule_not_duplicate = check_not_duplicate
