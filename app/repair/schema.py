"""Pydantic schemas for automated code repair patches and application results."""

from pydantic import BaseModel, Field
from app.review.schema import Finding


class Patch(BaseModel):
    """Represents a generated code repair patch for a specific finding."""

    finding: Finding = Field(..., description="The finding that triggered this repair")
    original_code: str = Field(..., description="The original source code before repair")
    fixed_code: str = Field(..., description="The full corrected source code file")
    explanation: str = Field(..., description="Brief explanation of the changes made")
    diff: str = Field(..., description="Unified diff between original and fixed code")
    attempt: int = Field(default=1, ge=1, description="Repair attempt iteration number")


class ApplyResult(BaseModel):
    """Result of applying a patch to a temporary file copy."""

    original_path: str = Field(..., description="Path to the original un-modified file")
    patched_path: str | None = Field(default=None, description="Path to the temporary patched copy")
    success: bool = Field(..., description="Whether the patch was successfully written")
    error: str | None = Field(default=None, description="Error message if application failed")
