"""Verification interfaces and result models for CodeInsight AI."""

from typing import Any, Literal, Protocol, runtime_checkable
from pydantic import BaseModel, Field

VerificationStage = Literal["syntax", "lint", "tests", "none"]


class VerificationResult(BaseModel):
    """Result of running verification stages on patched code."""

    passed: bool = Field(..., description="Whether verification passed")
    stage: VerificationStage = Field(
        default="none",
        description="Failing stage ('syntax', 'lint', 'tests') or 'none' if passed",
    )
    error: str = Field(default="", description="Error summary or message if verification failed")
    output: str = Field(default="", description="Detailed compiler, linter, or test output")
    project_report: dict[str, Any] | None = Field(
        default=None,
        description="Full project-level verification report when applicable",
    )


@runtime_checkable
class Verifier(Protocol):
    """Protocol for verifiers validating patched code."""

    def verify(self, patched_code: str, file_path: str) -> VerificationResult:
        """Verify the patched code against syntax, lint, or test requirements."""
        ...
