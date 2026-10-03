"""Core code reviewer orchestrator module."""

import json
import logging
import re
from typing import Any
from app.review.llm_client import LLMClient, get_client
from app.review.prompts import SYSTEM_PROMPT, build_user_prompt
from app.review.schema import Finding, ReviewResult

logger = logging.getLogger(__name__)


def _extract_json_block(text: str) -> str:
    """Extract a JSON substring from raw model output, handling markdown fences and extraneous text."""
    if not text or not text.strip():
        raise ValueError("Empty response received from LLM")

    # 1. Match code fences: ```json ... ``` or ``` ... ```
    fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    fence_matches = list(re.finditer(fence_pattern, text, re.IGNORECASE))
    for match in fence_matches:
        candidate = match.group(1).strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            return candidate
        # Also handle potential list if model returned a bare array
        if candidate.startswith("[") and candidate.endswith("]"):
            return candidate

    # 2. Search for the outermost JSON object {...}
    start = text.find("{")
    if start != -1:
        end = text.rfind("}")
        if end > start:
            return text[start : end + 1].strip()

    # 3. Search for outermost JSON array [...]
    start_arr = text.find("[")
    if start_arr != -1:
        end_arr = text.rfind("]")
        if end_arr > start_arr:
            return text[start_arr : end_arr + 1].strip()

    raise ValueError(f"Could not locate a valid JSON block in model output:\n{text}")


def _parse_and_validate(raw_text: str) -> ReviewResult:
    """Extract and validate JSON against the ReviewResult pydantic model."""
    json_str = _extract_json_block(raw_text)

    # First attempt: direct pydantic json validation
    try:
        return ReviewResult.model_validate_json(json_str)
    except Exception:
        pass

    # Second attempt: deserialize to python object and handle loose schemas
    parsed: Any = json.loads(json_str)
    if isinstance(parsed, list):
        return ReviewResult.model_validate({"findings": parsed})

    if isinstance(parsed, dict):
        if "findings" not in parsed:
            for alt in ("issues", "defects", "results", "errors"):
                if alt in parsed and isinstance(parsed[alt], list):
                    parsed["findings"] = parsed[alt]
                    break
        return ReviewResult.model_validate(parsed)

    raise ValueError(f"Extracted JSON does not conform to ReviewResult schema: {parsed}")


def review(
    context: str,
    file: str = "snippet.py",
    changed_lines: set[int] | None = None,
    client: LLMClient | None = None,
) -> list[Finding]:
    """Review code context using an LLM client and return validated findings.

    Args:
        context: Source code content to be reviewed.
        file: Path or filename of the code being reviewed.
        changed_lines: Optional set of 1-indexed line numbers modified in PR diff.
        client: Optional LLMClient instance. Defaults to get_client().

    Returns:
        A list of validated Finding objects within the valid line range of the code.
    """
    total_lines = len(context.splitlines())
    if client is None:
        client = get_client()

    user_prompt = build_user_prompt(context=context, file=file, changed_lines=changed_lines)

    # Step 1: Initial LLM call
    try:
        raw_response = client.complete(system=SYSTEM_PROMPT, user=user_prompt)
    except Exception as err:
        logger.warning("LLM client failed during initial review call: %s", err)
        return []

    # Step 2: Extract & validate with single retry on failure
    review_result: ReviewResult | None = None
    try:
        review_result = _parse_and_validate(raw_response)
    except Exception as initial_err:
        logger.info(
            "Initial validation failed (%s). Retrying once with error feedback to LLM...",
            initial_err,
        )
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"[RETRY NOTICE]\n"
            f"Your previous response failed schema validation with error: {initial_err}\n"
            f"Previous output was:\n{raw_response}\n\n"
            f"Please output ONLY valid JSON matching the exact ReviewResult schema:\n"
            f'{{"findings": [...]}}'
        )
        try:
            retry_response = client.complete(system=SYSTEM_PROMPT, user=retry_prompt)
            review_result = _parse_and_validate(retry_response)
        except Exception as retry_err:
            logger.warning(
                "LLM review failed after retry. Validation error: %s. Returning empty findings.",
                retry_err,
            )
            return []

    if review_result is None:
        return []

    # Step 3: Filter findings whose line numbers fall outside valid code range [1..total_lines]
    valid_findings: list[Finding] = []
    for finding in review_result.findings:
        if 1 <= finding.line <= total_lines:
            # Normalize file name if finding has generic or mismatched name
            if not finding.file or finding.file == "snippet.py":
                finding.file = file
            valid_findings.append(finding)
        else:
            logger.warning(
                "Dropping finding on line %d: outside valid range 1..%d for file '%s'",
                finding.line,
                total_lines,
                file,
            )

    return valid_findings
