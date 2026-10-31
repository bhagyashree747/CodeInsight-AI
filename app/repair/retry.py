"""Retry orchestration for automated code repair with verification feedback."""

import logging
from typing import Any, Literal
from pydantic import BaseModel, Field

from app.repair.patch_generator import PatchGenerationError, generate_function_patch, generate_patch
from app.repair.schema import Patch
from app.repair.verifier_interface import VerificationResult, Verifier
from app.review.llm_client import LLMClient, get_client
from app.review.schema import Finding

logger = logging.getLogger(__name__)


class RepairAttempt(BaseModel):
    """Details of an individual repair attempt."""

    attempt: int = Field(..., description="1-indexed attempt number")
    patch: Patch | None = Field(default=None, description="Generated patch for this attempt")
    verification: VerificationResult | None = Field(default=None, description="Verification outcome")
    error: str | None = Field(default=None, description="Error message if generation or verification failed")


class RepairOutcome(BaseModel):
    """Aggregate outcome of a multi-attempt repair loop."""

    status: Literal["verified", "failed", "skipped"] = Field(
        ..., description="Repair status: 'verified', 'failed', or 'skipped'"
    )
    attempts: list[RepairAttempt] = Field(
        default_factory=list, description="Chronological record of repair attempts"
    )
    final_patch: Patch | None = Field(
        default=None, description="The final patch produced, if any"
    )
    final_code: str | None = Field(
        default=None, description="Final code after repair (or original if unpatched)"
    )
    total_attempts: int = Field(
        default=0, description="Total number of attempts performed"
    )


def repair_with_retries(
    code: str,
    finding: Finding,
    verifier: Verifier,
    client: LLMClient | None = None,
    max_attempts: int = 3,
    file_path: str = "snippet.py",
    function_info: dict[str, Any] | Any | None = None,
) -> RepairOutcome:
    """Attempt to repair a finding in a loop, feeding verification failures back to the LLM.

    Args:
        code: Full original source code.
        finding: Finding to repair.
        verifier: Verifier protocol implementation for checking patched code.
        client: Optional LLMClient. Defaults to get_client().
        max_attempts: Maximum number of repair attempts before giving up (default 3).
        file_path: File path of the snippet being verified.
        function_info: Optional function dict or object for function-level repair.

    Returns:
        RepairOutcome with status ('verified', 'failed', or 'skipped') and full attempt history.
    """
    if client is None:
        client = get_client()

    if function_info is not None:
        too_large = (
            function_info.get("too_large", False)
            if isinstance(function_info, dict)
            else getattr(function_info, "too_large", False)
        )
        if too_large:
            logger.info("Function marked as too_large; skipping repair.")
            return RepairOutcome(
                status="skipped",
                attempts=[],
                final_patch=None,
                final_code=code,
                total_attempts=0,
            )

    attempts: list[RepairAttempt] = []
    previous_patch: Patch | None = None
    failure_feedback: str | None = None

    for attempt in range(1, max_attempts + 1):
        # Step 1: Generate patch (handling PatchGenerationError as a failed attempt)
        try:
            if function_info is not None:
                patch = generate_function_patch(
                    full_code=code,
                    function_info=function_info,
                    finding=finding,
                    client=client,
                    previous_patch=previous_patch,
                    failure_feedback=failure_feedback,
                    attempt=attempt,
                )
            else:
                patch = generate_patch(
                    code=code,
                    finding=finding,
                    client=client,
                    previous_patch=previous_patch,
                    failure_feedback=failure_feedback,
                    attempt=attempt,
                )
        except PatchGenerationError as err:
            logger.warning("Attempt %d failed patch generation: %s", attempt, err)
            v_res = VerificationResult(
                passed=False,
                stage="none",
                error=f"PatchGenerationError: {err}",
                output=str(err),
            )
            attempts.append(
                RepairAttempt(
                    attempt=attempt,
                    patch=None,
                    verification=v_res,
                    error=str(err),
                )
            )
            failure_feedback = f"Patch generation error: {err}"
            previous_patch = None
            continue

        previous_patch = patch

        # Step 2: Verify patched code
        verification = verifier.verify(patched_code=patch.fixed_code, file_path=file_path)
        attempts.append(
            RepairAttempt(
                attempt=attempt,
                patch=patch,
                verification=verification,
                error=verification.error if not verification.passed else None,
            )
        )

        # Step 3: Check success
        if verification.passed:
            logger.info("Attempt %d: Patch successfully verified.", attempt)
            return RepairOutcome(
                status="verified",
                attempts=attempts,
                final_patch=patch,
                final_code=patch.fixed_code,
                total_attempts=attempt,
            )

        # Step 4: Prepare failure feedback for next iteration
        logger.info(
            "Attempt %d: Verification failed at stage '%s': %s",
            attempt,
            verification.stage,
            verification.error,
        )
        failure_feedback = (
            f"Verification failed at stage '{verification.stage}': {verification.error}\n"
            f"{verification.output}"
        ).strip()

    # Max attempts reached without verification
    last_patch = attempts[-1].patch if attempts and attempts[-1].patch else previous_patch
    return RepairOutcome(
        status="failed",
        attempts=attempts,
        final_patch=last_patch,
        final_code=last_patch.fixed_code if last_patch else code,
        total_attempts=len(attempts),
    )
