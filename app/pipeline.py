"""End-to-end code review and repair pipeline.

Flow: review() -> filter_findings() -> RepairAgent.repair_all()

Every error is captured in the result dict — the pipeline never raises.
"""

from __future__ import annotations

import logging
import traceback
from typing import Any

from app.relevance.filter import FilterResult, filter_findings
from app.repair.agent import RepairAgent
from app.repair.local_verifier import LocalVerifier
from app.repair.verifier_interface import Verifier
from app.review.llm_client import LLMClient, get_client
from app.review.reviewer import review
from app.review.schema import Finding

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
        functions: Optional list of function dicts or objects (name, start_line, end_line,
            text, and optional too_large). When supplied, review and repair run at the
            function level, splicing verified fixes into the full file.

    Returns:
        A JSON-serialisable dict with keys:
        ``file``, ``counts``, ``findings``, ``discarded``, ``repairs``, ``summary``.
        All errors are captured inside the dict — this function never raises.
    """

    # Resolve client once so both review and repair use the same instance.
    if client is None:
        try:
            client = get_client()
        except Exception as err:
            logger.error("get_client() failed: %s", err)
            return _error_result(file, f"Failed to initialise LLM client: {err}")

    # Resolve verifier
    if verifier is None:
        try:
            verifier = LocalVerifier(test_code=test_code)
        except Exception as err:
            logger.error("LocalVerifier init failed: %s", err)
            return _error_result(file, f"Failed to initialise verifier: {err}")

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
            findings = review(context=code, file=file, changed_lines=changed_lines, client=client)
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
        )
        try:
            outcomes = agent.repair_all(
                code=code,
                scored_findings=filter_result.kept,
                file_path=file,
                functions=functions,
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

            if outcome.status == "skipped":
                explanation = "repair skipped: function too large"
            elif outcome.final_patch is not None:
                diff_text = outcome.final_patch.diff or ""
                explanation = outcome.final_patch.explanation or ""

            # Last attempt's verification stage
            if outcome.attempts:
                last_attempt = outcome.attempts[-1]
                if last_attempt.verification is not None:
                    verification_stage = last_attempt.verification.stage

            repair_outcomes_raw.append({
                "finding": _finding_to_dict(sf.finding),
                "status": outcome.status,
                "attempts": outcome.total_attempts,
                "diff": diff_text,
                "explanation": explanation,
                "verification_stage": verification_stage,
            })
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

    if pipeline_errors:
        result["pipeline_errors"] = pipeline_errors

    return result


# ---------------------------------------------------------------------------
# Internal fallback for catastrophic early failures
# ---------------------------------------------------------------------------

def _error_result(file: str, error: str) -> dict[str, Any]:
    """Return a minimal result dict that captures a fatal initialisation error."""
    return {
        "file": file,
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
