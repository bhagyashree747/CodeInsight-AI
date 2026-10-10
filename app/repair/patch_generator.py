"""Patch generator and patch application module for automated code repair."""

import difflib
import json
import logging
from pathlib import Path
import tempfile
from typing import Any

from app.repair.prompts import REPAIR_SYSTEM_PROMPT, build_repair_prompt
from app.repair.schema import ApplyResult, Patch
from app.review.llm_client import LLMClient, get_client
from app.review.reviewer import _extract_json_block
from app.review.schema import Finding

logger = logging.getLogger(__name__)


class PatchGenerationError(Exception):
    """Raised when patch generation fails or produces invalid/identical code."""
    pass


def _parse_repair_json(raw_text: str) -> tuple[str, str]:
    """Extract and validate the JSON output for code repair."""
    json_str = _extract_json_block(raw_text)
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as err:
        raise ValueError(f"Invalid JSON string: {err}") from err

    if not isinstance(data, dict):
        raise ValueError("Repair response must be a JSON object")

    if "fixed_code" not in data:
        raise ValueError("Repair JSON is missing required 'fixed_code' key")

    fixed_code = str(data["fixed_code"])
    explanation = str(data.get("explanation", "")).strip()
    return fixed_code, explanation


def generate_patch(
    code: str,
    finding: Finding,
    client: LLMClient | None = None,
    previous_patch: Patch | None = None,
    failure_feedback: str | None = None,
    attempt: int = 1,
) -> Patch:
    """Generate a repair patch for a specific finding using an LLM.

    Args:
        code: Full original source code of the file.
        finding: The Finding to be repaired.
        client: Optional LLMClient instance. Defaults to get_client().
        previous_patch: Optional previously attempted patch that failed.
        failure_feedback: Optional feedback or test output from previous failed patch.
        attempt: Attempt counter for this patch generation.

    Returns:
        A Patch instance containing the fixed code, explanation, and unified diff.

    Raises:
        PatchGenerationError: If LLM output is invalid after retry, empty, or identical to original.
    """
    if client is None:
        client = get_client()

    user_prompt = build_repair_prompt(
        code=code,
        finding=finding,
        previous_patch=previous_patch,
        failure_feedback=failure_feedback,
    )

    # Attempt 1: Call LLM and parse JSON
    raw_response = ""
    try:
        raw_response = client.complete(system=REPAIR_SYSTEM_PROMPT, user=user_prompt)
        fixed_code, explanation = _parse_repair_json(raw_response)
    except Exception as initial_err:
        logger.info(
            "Initial repair parsing failed (%s). Retrying once with error feedback...",
            initial_err,
        )
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"[RETRY NOTICE]\n"
            f"Your previous response failed JSON parsing with error: {initial_err}\n"
            f"Previous output was:\n{raw_response}\n\n"
            f"Please output ONLY valid JSON matching:\n"
            f'{{"fixed_code": "<full corrected file>", "explanation": "<one or two sentences>"}}'
        )
        try:
            retry_response = client.complete(system=REPAIR_SYSTEM_PROMPT, user=retry_prompt)
            fixed_code, explanation = _parse_repair_json(retry_response)
        except Exception as retry_err:
            logger.error("Repair failed after retry: %s", retry_err)
            raise PatchGenerationError(
                f"Failed to generate valid patch JSON after retry: {retry_err}"
            ) from retry_err

    # Validate non-empty output
    if not fixed_code.strip():
        raise PatchGenerationError("Generated patch contains empty fixed code.")

    # Validate output is not identical to original
    if fixed_code == code:
        raise PatchGenerationError(
            "Generated patch is identical to original code (no fix was applied)."
        )

    # Generate unified diff
    filename = finding.file if finding and finding.file else "snippet.py"
    original_lines = code.splitlines(keepends=True)
    fixed_lines = fixed_code.splitlines(keepends=True)

    # Ensure last line has a newline for clean unified diff if original had it
    diff_lines = list(
        difflib.unified_diff(
            original_lines,
            fixed_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )
    diff_str = "".join(diff_lines)

    return Patch(
        finding=finding,
        original_code=code,
        fixed_code=fixed_code,
        explanation=explanation,
        diff=diff_str,
        attempt=attempt,
    )


def apply_patch(
    patch: Patch,
    original_path: str,
    work_dir: str | None = None,
) -> ApplyResult:
    """Write the fixed code from a patch to a temporary file, never modifying the original.

    Args:
        patch: The Patch containing the fixed code.
        original_path: Path to the original file.
        work_dir: Optional working directory for the temporary file.

    Returns:
        ApplyResult with original path, temporary patched path, and status.
    """
    try:
        orig_p = Path(original_path)
        suffix = orig_p.suffix or ".py"
        prefix = f"patched_{orig_p.stem}_"

        if work_dir is not None:
            Path(work_dir).mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=suffix,
            prefix=prefix,
            dir=work_dir,
            delete=False,
        ) as tmp_file:
            tmp_file.write(patch.fixed_code)
            temp_path = tmp_file.name

        return ApplyResult(
            original_path=str(original_path),
            patched_path=temp_path,
            success=True,
            error=None,
        )
    except Exception as err:
        logger.error("Failed to apply patch to temporary copy: %s", err)
        return ApplyResult(
            original_path=str(original_path),
            patched_path=None,
            success=False,
            error=str(err),
        )
