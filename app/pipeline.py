"""End-to-end code review and repair pipeline.

Flow: review() -> filter_findings() -> RepairAgent.repair_all()

Every error is captured in the result dict — the pipeline never raises.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any

from app.relevance.filter import FilterResult, filter_findings
from app.repair.agent import RepairAgent
from app.repair.local_verifier import LocalVerifier
from app.repair.schema import Patch
from app.repair.verifier_interface import VerificationResult, Verifier
from app.review.llm_client import LLMClient, get_client
from app.review.reviewer import review
from app.review.schema import Finding
from app.verification.repair_adapter import RepairVerificationAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    """Convert a Finding to a JSON-serializable dict."""
    return {
        "file": finding.file,
        "line": finding.line,
        "category": finding.category.value,
        "severity": finding.severity.value,
        "confidence": finding.confidence,
        "description": finding.description,
        "suggested_fix_hint": finding.suggested_fix_hint,
        "actionable": finding.actionable,
    }


def _count_by_severity(filter_result: FilterResult) -> dict[str, int]:
    """Count kept findings grouped by severity value."""
    counts: dict[str, int] = {}
    for sf in filter_result.kept:
        sev = sf.finding.severity.value
        counts[sev] = counts.get(sev, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_pipeline(
    code: str,
    file: str = "snippet.py",
    changed_lines: set[int] | None = None,
    client: LLMClient | None = None,
    verifier: Verifier | None = None,
    max_attempts: int = 3,
    test_code: str | None = None,
    functions: list[dict[str, Any]] | list[Any] | None = None,
    extra_context: str | None = None,
    context_level: str | None = None,
    project_workspace: str | Path | None = None,
    project_test_timeout: float = 60,
    project_file: str | Path | None = None,
) -> dict[str, Any]:
    """Run the full review → filter → repair pipeline on a code snippet.

    Args:
        code: Source code to analyse.
        file: Logical filename for the snippet (used in findings and verifier).
        changed_lines: Optional set of 1-indexed line numbers in the PR diff.
            When supplied, only findings on changed lines are kept.
        client: LLMClient to use for both review and repair. Defaults to
            ``get_client()`` which honours the ``LLM_PROVIDER`` env var.
        verifier: Verifier implementation for patch verification. Defaults to
            ``LocalVerifier`` (syntax → ruff → optional pytest).
        max_attempts: Maximum repair attempts per finding.
        test_code: Optional test code string to pass to ``LocalVerifier``.
            Ignored when a custom *verifier* is provided.
        project_workspace: If supplied, verify each generated patch against this
            project's full baseline and patched test suites instead of using
            ``LocalVerifier``.
        project_test_timeout: Timeout for each project test-suite run.
        project_file: Source file path within ``project_workspace``. May be
            absolute or relative to the workspace. Defaults to ``file`` in
            project mode; ``file`` remains the logical review/verifier name.
        functions: Optional list of function dicts or objects (name, start_line, end_line,
            text, and optional too_large). When supplied, review and repair run at the
            function level, splicing verified fixes into the full file.
        extra_context: Optional supplementary context (read-only) for review and repair.
        context_level: Optional metadata string representing scope of extra_context.

    Returns:
        A JSON-serialisable dict with keys:
        ``file``, ``context_level``, ``counts``, ``findings``, ``discarded``, ``repairs``, ``summary``.
        All errors are captured inside the dict — this function never raises.
    """

    resolved_project_workspace: Path | None = None
    resolved_project_file: Path | None = None
    if project_workspace is not None:
        if verifier is not None:
            return _error_result(
                file,
                "Specify either verifier or project_workspace, not both.",
                context_level=context_level,
            )
        try:
            resolved_project_workspace = Path(project_workspace).expanduser().resolve(
                strict=True
            )
            if not resolved_project_workspace.is_dir():
                raise ValueError(
                    f"Project workspace is not a directory: "
                    f"{resolved_project_workspace}"
                )
            project_source = Path(
                project_file if project_file is not None else file
            ).expanduser()
            if not project_source.is_absolute():
                project_source = resolved_project_workspace / project_source
            resolved_project_file = project_source.resolve(strict=True)
            resolved_project_file.relative_to(resolved_project_workspace)
            if (
                not resolved_project_file.is_file()
                or resolved_project_file.suffix.lower() != ".py"
            ):
                raise ValueError(
                    "Project file must be an existing Python file within "
                    f"the project workspace: {resolved_project_file}"
                )
        except (OSError, RuntimeError, TypeError, ValueError) as err:
            return _error_result(
                file,
                f"Invalid project verification paths: {err}",
                context_level=context_level,
            )

    # Resolve client once so both review and repair use the same instance.
    if client is None:
        try:
            client = get_client()
        except Exception as err:
            logger.error("get_client() failed: %s", err)
            return _error_result(file, f"Failed to initialise LLM client: {err}", context_level=context_level)

    # Project mode deliberately uses the Patch-level verifier instead of
    # falling back to LocalVerifier, which cannot validate the full workspace.
    patch_verifier = None
    if project_workspace is not None:
        adapter = RepairVerificationAdapter()

        def verify_project_patch(patch: Patch) -> VerificationResult:
            return adapter.verify_patch_result(
                patch=patch,
                original_file=resolved_project_file,
                workspace=resolved_project_workspace,
                test_timeout=project_test_timeout,
            )

        patch_verifier = verify_project_patch
    elif verifier is None:
        try:
            verifier = LocalVerifier(test_code=test_code)
        except Exception as err:
            logger.error("LocalVerifier init failed: %s", err)
            return _error_result(file, f"Failed to initialise verifier: {err}", context_level=context_level)

    # ------------------------------------------------------------------
    # Stage 1: Review
    # ------------------------------------------------------------------
    findings: list[Finding] = []
    review_error: str | None = None
    if functions is not None:
        try:
            for func_item in functions:
                f_name = func_item["name"] if isinstance(func_item, dict) else func_item.name
                f_start = int(func_item["start_line"] if isinstance(func_item, dict) else func_item.start_line)
                f_end = int(func_item["end_line"] if isinstance(func_item, dict) else func_item.end_line)
                f_text = str(func_item["text"] if isinstance(func_item, dict) else func_item.text)

                func_findings = review(
                    context=f_text,
                    file=file,
                    changed_lines=changed_lines,
                    client=client,
                    start_line=f_start,
                    extra_context=extra_context,
                    context_level=context_level,
                )
                findings.extend(func_findings)
        except Exception as err:
            review_error = (
                f"Review stage raised an unexpected exception: {err}\n"
                f"{traceback.format_exc()}"
            )
            logger.error(review_error)
    else:
        try:
            findings = review(
                context=code,
                file=file,
                changed_lines=changed_lines,
                client=client,
                extra_context=extra_context,
                context_level=context_level,
            )
        except Exception as err:
            review_error = (
                f"Review stage raised an unexpected exception: {err}\n"
                f"{traceback.format_exc()}"
            )
            logger.error(review_error)
            # Continue with zero findings rather than crashing.

    # ------------------------------------------------------------------
    # Stage 2: Filter
    # ------------------------------------------------------------------
    filter_result: FilterResult
    filter_error: str | None = None
    try:
        filter_result = filter_findings(findings, changed_lines=changed_lines)
    except Exception as err:
        filter_error = f"Filter stage raised an unexpected exception: {err}\n{traceback.format_exc()}"
        logger.error(filter_error)
        # Build an empty FilterResult so the rest of the pipeline can proceed.
        from app.relevance.filter import FilterResult as FR  # noqa: PLC0415
        filter_result = FR(
            kept=[],
            discarded=[],
            kept_count=0,
            discarded_count=0,
            total_count=len(findings),
        )

    # ------------------------------------------------------------------
    # Stage 3: Repair
    # ------------------------------------------------------------------
    repair_outcomes_raw: list[dict[str, Any]] = []
    repair_error: str | None = None

    if filter_result.kept:
        agent = RepairAgent(
            verifier=verifier,
            client=client,
            max_attempts=max_attempts,
            functions=functions,
            extra_context=extra_context,
            patch_verifier=patch_verifier,
        )
        try:
            outcomes = agent.repair_all(
                code=code,
                scored_findings=filter_result.kept,
                file_path=file,
                functions=functions,
                extra_context=extra_context,
            )
        except Exception as err:
            repair_error = (
                f"Repair stage raised an unexpected exception: {err}\n"
                f"{traceback.format_exc()}"
            )
            logger.error(repair_error)
            outcomes = []

        for sf, outcome in zip(filter_result.kept, outcomes):
            # Extract diff / explanation from final patch (may be None on failure or skip)
            diff_text = ""
            explanation = ""
            verification_stage = "none"
            project_verification_reports = []

            patched_code = None
            patched_function = None
            if outcome.status == "skipped":
                explanation = "repair skipped: function too large"
            elif outcome.final_patch is not None:
                diff_text = outcome.final_patch.diff or ""
                explanation = outcome.final_patch.explanation or ""
                patched_code = outcome.final_patch.fixed_code
                patched_function = outcome.final_patch.fixed_function

            # Last attempt's verification stage
            if outcome.attempts:
                last_attempt = outcome.attempts[-1]
                if last_attempt.verification is not None:
                    verification_stage = last_attempt.verification.stage
            for attempt in outcome.attempts:
                if (
                    attempt.verification is not None
                    and attempt.verification.project_report is not None
                ):
                    project_verification_reports.append(
                        attempt.verification.project_report
                    )

            repair_result = {
                "finding": _finding_to_dict(sf.finding),
                "patched_function": patched_function,
                "patched_code": patched_code,
                "diff": diff_text,
                "explanation": explanation,
                "status": outcome.status,
                "attempts": outcome.total_attempts,
                "verification_stage": verification_stage,
            }
            if project_workspace is not None:
                repair_result["project_verification_reports"] = (
                    project_verification_reports
                )
            repair_outcomes_raw.append(repair_result)
    else:
        outcomes = []

    # ------------------------------------------------------------------
    # Stage 4: Assemble result dict
    # ------------------------------------------------------------------
    verified_count = sum(1 for r in repair_outcomes_raw if r["status"] == "verified")
    failed_count = sum(1 for r in repair_outcomes_raw if r["status"] == "failed")
    retried_count = sum(1 for r in repair_outcomes_raw if r["attempts"] > 1)
    skipped_count = sum(1 for r in repair_outcomes_raw if r["status"] == "skipped")

    # Pipeline-level errors summary
    pipeline_errors: list[str] = []
    if review_error:
        pipeline_errors.append(review_error)
    if filter_error:
        pipeline_errors.append(filter_error)
    if repair_error:
        pipeline_errors.append(repair_error)

    summary: dict[str, int] = {
        "verified": verified_count,
        "failed": failed_count,
        "retried": retried_count,
    }
    if skipped_count > 0:
        summary["skipped"] = skipped_count

    result: dict[str, Any] = {
        "file": file,
        "context_level": context_level,
        "counts": {
            "issues_detected": len(findings),
            "kept": filter_result.kept_count,
            "filtered_as_noise": filter_result.discarded_count,
            "by_severity": _count_by_severity(filter_result),
        },
        "findings": [
            {
                **_finding_to_dict(sf.finding),
                "score": sf.score,
            }
            for sf in filter_result.kept
        ],
        "discarded": [
            {
                **_finding_to_dict(df.finding),
                "reason": df.reason,
            }
            for df in filter_result.discarded
        ],
        "repairs": repair_outcomes_raw,
        "summary": summary,
    }

    if pipeline_errors:
        result["pipeline_errors"] = pipeline_errors

    return result


# ---------------------------------------------------------------------------
# Internal fallback for catastrophic early failures
# ---------------------------------------------------------------------------

def _error_result(file: str, error: str, context_level: str | None = None) -> dict[str, Any]:
    """Return a minimal result dict that captures a fatal initialisation error."""
    return {
        "file": file,
        "context_level": context_level,
        "counts": {
            "issues_detected": 0,
            "kept": 0,
            "filtered_as_noise": 0,
            "by_severity": {},
        },
        "findings": [],
        "discarded": [],
        "repairs": [],
        "summary": {"verified": 0, "failed": 0, "retried": 0},
        "pipeline_errors": [error],
    }
