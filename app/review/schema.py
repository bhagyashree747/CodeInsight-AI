"""Pydantic schemas for code review findings and results."""

from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Category(str, Enum):
    """Category of finding."""
    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    LOGIC = "logic"


class Severity(str, Enum):
    """Severity level of finding."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Finding(BaseModel):
    """Represents an individual code review finding."""

    model_config = ConfigDict(str_strip_whitespace=True)

    file: str = Field(..., min_length=1, description="File path relative to repository root")
    line: int = Field(..., ge=1, description="Line number (1-indexed)")
    category: Category = Field(..., description="Category of the finding: bug, security, performance, logic")
    severity: Severity = Field(..., description="Severity level: high, medium, low")
    confidence: float = Field(..., description="Confidence score clamped between 0.0 and 1.0")
    description: str = Field(..., description="Detailed description of the issue")
    suggested_fix_hint: str = Field(default="", description="Actionable hint or code snippet to fix the issue")
    actionable: bool = Field(default=True, description="Whether this finding has a concrete actionable fix")

    @field_validator("file", "suggested_fix_hint", mode="before")
    @classmethod
    def _strip_strings(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, v: Any) -> str:
        if v is None:
            raise ValueError("Description cannot be empty")
        stripped = str(v).strip()
        if not stripped:
            raise ValueError("Description cannot be empty or whitespace only")
        return stripped

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: Any) -> float:
        try:
            val = float(v)
        except (TypeError, ValueError) as err:
            raise ValueError(f"Invalid confidence value '{v}': must be a float") from err
        # Clamp confidence to [0.0, 1.0]
        return max(0.0, min(1.0, val))

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, v: Any) -> Category:
        if isinstance(v, Category):
            return v
        if isinstance(v, str):
            v_clean = v.strip().lower()
            for cat in Category:
                if cat.value == v_clean:
                    return cat
        raise ValueError(
            f"Invalid category '{v}'. Must be one of: {[c.value for c in Category]}"
        )

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, v: Any) -> Severity:
        if isinstance(v, Severity):
            return v
        if isinstance(v, str):
            v_clean = v.strip().lower()
            for sev in Severity:
                if sev.value == v_clean:
                    return sev
        raise ValueError(
            f"Invalid severity '{v}'. Must be one of: {[s.value for s in Severity]}"
        )


class ReviewResult(BaseModel):
    """Collection of findings returned by the reviewer."""

    findings: list[Finding] = Field(default_factory=list, description="List of review findings")
