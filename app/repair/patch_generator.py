"""Patch generator and patch application module for automated code repair."""

import ast
import difflib
import json
import logging
from pathlib import Path
import re
import tempfile
import textwrap
from typing import Any

from app.repair.prompts import (
    FUNCTION_REPAIR_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
    build_function_repair_prompt,
    build_repair_prompt,
)
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


def _parse_function_repair_response(raw_text: str) -> tuple[str, str]:
    """Extract corrected function code and explanation from LLM output.

    Accepts either JSON ({"fixed_code": "...", "explanation": "..."}) or raw function code.
    """
    if not raw_text or not raw_text.strip():
        raise ValueError("Empty response received from LLM")

    # First attempt: JSON extraction
    try:
        fixed_code, explanation = _parse_repair_json(raw_text)
        return fixed_code, explanation
    except Exception:
        pass

    # Second attempt: check if response has code fences ```python ... ```
    fence_pattern = r"```(?:python)?\s*([\s\S]*?)\s*```"
    match = re.search(fence_pattern, raw_text, re.IGNORECASE)
    if match:
        code_inside = match.group(1).strip()
        return code_inside, "Applied function fix."

    # Third attempt: raw function code directly
    stripped = raw_text.strip()
    if "def " in stripped or "async def " in stripped:
        return stripped, "Applied function fix."

    raise ValueError(f"Could not parse valid function code from response:\n{raw_text}")


def validate_function_patch(func_code: str, expected_name: str) -> None:
    """Validate that func_code parses as a single function definition with expected_name.

    Args:
        func_code: The candidate fixed function code.
        expected_name: The expected function name.

    Raises:
        PatchGenerationError: If func_code is invalid syntax, contains multiple statements,
                             is not a function definition, or has a mismatched name.
    """
    dedented = textwrap.dedent(func_code).strip()
    if not dedented:
        raise PatchGenerationError("Generated function patch is empty.")

    try:
        tree = ast.parse(dedented)
    except Exception as err:
        raise PatchGenerationError(f"Generated function patch has syntax error: {err}") from err

    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)):
        statement_types = [type(stmt).__name__ for stmt in tree.body]
        raise PatchGenerationError(
            f"Generated patch must be a single function definition, got {len(tree.body)} "
            f"statement(s): {statement_types}"
        )

    actual_name = tree.body[0].name
    if actual_name != expected_name:
        raise PatchGenerationError(
            f"Function name mismatch: expected '{expected_name}', got '{actual_name}'"
        )


def splice_function(
    file_code: str,
    func_code: str,
    start_line: int,
    end_line: int,
) -> str:
    """Splice corrected function into full file replacing lines start_line..end_line.

    Preserves surrounding code, decorators, indentation, and line endings.
    Never edits any file on disk.

    Args:
        file_code: Full original file content.
        func_code: Corrected function code.
        start_line: 1-indexed start line (inclusive).
        end_line: 1-indexed end line (inclusive).

    Returns:
        Full patched file content with corrected function spliced in.
    """
    has_crlf = "\r\n" in file_code
    line_ending = "\r\n" if has_crlf else "\n"
    orig_lines = file_code.splitlines()

    start_idx = max(0, start_line - 1)
    end_idx = min(len(orig_lines), end_line)
    replaced_orig_lines = orig_lines[start_idx:end_idx]

    # Find indentation of the def line in replaced lines
    def_line = None
    for l in replaced_orig_lines:
        stripped = l.lstrip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            def_line = l
            break
    if def_line is None and replaced_orig_lines:
        def_line = replaced_orig_lines[0]
    target_indent = ""
    if def_line:
        target_indent = def_line[: len(def_line) - len(def_line.lstrip())]

    # Find decorators in replaced lines before def
    orig_decorators = []
    for l in replaced_orig_lines:
        stripped = l.lstrip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            break
        if stripped.startswith("@"):
            orig_decorators.append(l)

    # Check if func_code already has decorators
    dedented = textwrap.dedent(func_code).strip("\r\n")
    try:
        tree = ast.parse(dedented)
        func_node = tree.body[0] if tree.body else None
        has_decorators_in_new = bool(getattr(func_node, "decorator_list", None))
    except Exception:
        has_decorators_in_new = False

    new_func_lines = []
    for line in dedented.splitlines():
        if line.strip():
            new_func_lines.append(target_indent + line)
        else:
            new_func_lines.append("")

    if not has_decorators_in_new and orig_decorators:
        final_replacement_lines = orig_decorators + new_func_lines
    else:
        final_replacement_lines = new_func_lines

    new_file_lines = orig_lines[:start_idx] + final_replacement_lines + orig_lines[end_idx:]
    result = line_ending.join(new_file_lines)
    if file_code.endswith("\r\n"):
        result += "\r\n"
    elif file_code.endswith("\n"):
        result += "\n"
    return result


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


def generate_function_patch(
    full_code: str,
    function_info: dict[str, Any] | Any,
    finding: Finding,
    client: LLMClient | None = None,
    previous_patch: Patch | None = None,
    failure_feedback: str | None = None,
    attempt: int = 1,
) -> Patch:
    """Generate a repair patch for a function and splice it into the full file.

    Args:
        full_code: Full original source code of the file.
        function_info: Dict or object with name, start_line, end_line, text.
        finding: The Finding to be repaired.
        client: Optional LLMClient instance. Defaults to get_client().
        previous_patch: Optional previously attempted patch that failed.
        failure_feedback: Optional feedback from previous failed patch.
        attempt: Attempt counter for this patch generation.

    Returns:
        Patch instance containing the full fixed code with function spliced in.

    Raises:
        PatchGenerationError: If LLM output fails schema/AST validation,
                             or produces identical code.
    """
    if client is None:
        client = get_client()

    func_name = function_info["name"] if isinstance(function_info, dict) else function_info.name
    start_line = int(function_info["start_line"] if isinstance(function_info, dict) else function_info.start_line)
    end_line = int(function_info["end_line"] if isinstance(function_info, dict) else function_info.end_line)
    func_text = str(function_info["text"] if isinstance(function_info, dict) else function_info.text)

    user_prompt = build_function_repair_prompt(
        function_text=func_text,
        finding=finding,
        previous_patch=previous_patch,
        failure_feedback=failure_feedback,
    )

    # Attempt 1: Call LLM and parse response
    raw_response = ""
    try:
        raw_response = client.complete(system=FUNCTION_REPAIR_SYSTEM_PROMPT, user=user_prompt)
        fixed_func, explanation = _parse_function_repair_response(raw_response)
        validate_function_patch(fixed_func, expected_name=func_name)
    except Exception as initial_err:
        logger.info(
            "Initial function repair parsing/validation failed (%s). Retrying once with error feedback...",
            initial_err,
        )
        retry_prompt = (
            f"{user_prompt}\n\n"
            f"[RETRY NOTICE]\n"
            f"Your previous response failed validation with error: {initial_err}\n"
            f"Previous output was:\n{raw_response}\n\n"
            f"Please output ONLY valid JSON matching:\n"
            f'{{"fixed_code": "<corrected function only>", "explanation": "<one or two sentences>"}}'
        )
        try:
            retry_response = client.complete(system=FUNCTION_REPAIR_SYSTEM_PROMPT, user=retry_prompt)
            fixed_func, explanation = _parse_function_repair_response(retry_response)
            validate_function_patch(fixed_func, expected_name=func_name)
        except Exception as retry_err:
            logger.error("Function repair failed after retry: %s", retry_err)
            raise PatchGenerationError(
                f"Failed to generate valid function patch after retry: {retry_err}"
            ) from retry_err

    # Splice into the full file
    spliced_code = splice_function(
        file_code=full_code,
        func_code=fixed_func,
        start_line=start_line,
        end_line=end_line,
    )

    if spliced_code == full_code:
        raise PatchGenerationError("Generated function patch is identical to original code (no fix was applied).")

    # Generate unified diff on the full file
    filename = finding.file if finding and finding.file else "snippet.py"
    diff_lines = list(
        difflib.unified_diff(
            full_code.splitlines(keepends=True),
            spliced_code.splitlines(keepends=True),
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
        )
    )
    diff_str = "".join(diff_lines)

    patch = Patch(
        finding=finding,
        original_code=full_code,
        fixed_code=spliced_code,
        explanation=explanation or f"Repaired function {func_name}",
        diff=diff_str,
        attempt=attempt,
        fixed_function=fixed_func,
    )
    return patch


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
