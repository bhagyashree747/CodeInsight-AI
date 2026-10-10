"""Prompts and prompt builders for automated code repair."""

from typing import TYPE_CHECKING
from app.review.schema import Finding

if TYPE_CHECKING:
    from app.repair.schema import Patch

REPAIR_SYSTEM_PROMPT = """You are an expert engineer fixing ONE issue.
Make the smallest change that fixes it.
Do not refactor or change unrelated code.
Keep function names and signatures.
Return ONLY JSON in this format:
{"fixed_code": "<full corrected file>", "explanation": "<one or two sentences>"}
Do not include markdown code fences (like ```json). Return raw JSON only."""


def build_repair_prompt(
    code: str,
    finding: Finding,
    previous_patch: "Patch | None" = None,
    failure_feedback: str | None = None,
) -> str:
    """Build the user prompt for repairing a single code finding.

    Args:
        code: Full original source code of the file.
        finding: The Finding to repair.
        previous_patch: Optional previous Patch attempt that failed.
        failure_feedback: Optional error message or feedback from testing the previous patch.

    Returns:
        Formatted prompt string for the LLM.
    """
    lines = code.splitlines()
    numbered_lines = [f"{i + 1}: {line}" for i, line in enumerate(lines)]
    code_with_lines = "\n".join(numbered_lines) if numbered_lines else "(empty file)"

    cat_str = finding.category.value if hasattr(finding.category, "value") else str(finding.category)
    sev_str = finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity)

    feedback_section = ""
    if previous_patch is not None or failure_feedback is not None:
        feedback_parts = [
            "\n[PREVIOUS ATTEMPT FAILED]",
            "Your last fix failed, correct it.",
        ]
        if previous_patch is not None:
            feedback_parts.append(f"Previous failed fixed code:\n{previous_patch.fixed_code}")
        if failure_feedback:
            feedback_parts.append(f"Failure reason / test output:\n{failure_feedback}")
        feedback_section = "\n".join(feedback_parts) + "\n"

    return f"""File: {finding.file}

Original code to fix (line numbers prefixed):
{code_with_lines}

Issue to fix:
- Line: {finding.line}
- Category: {cat_str}
- Severity: {sev_str}
- Description: {finding.description}
- Suggested Fix Hint: {finding.suggested_fix_hint or 'None provided'}
{feedback_section}
Fix this issue with the minimal necessary change while keeping the rest of the code intact.
Return ONLY valid JSON matching:
{{"fixed_code": "<full corrected file>", "explanation": "<one or two sentences>"}}
"""
