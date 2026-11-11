"""Adapter connecting verification tools to the AI repair interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.repair.verifier_interface import VerificationResult


class PatchLike(Protocol):
    fixed_code: str


class RepairVerificationAdapter:
    """Adapt local or project verification to the repair pipeline interfaces."""

    def __init__(self, test_code: str | None = None) -> None:
        self.test_code = test_code

    def verify(
        self,
        patched_code: str,
        file_path: str = "snippet.py",
    ) -> VerificationResult:
        """Return the actual result model produced by Member 1's LocalVerifier.

        Repair integration is optional at import time, but the repair modules
        must be integrated before this adapter can verify code.
        """
        try:
            from app.repair.local_verifier import LocalVerifier
        except ModuleNotFoundError as exc:
            if exc.name not in {
                "app.repair",
                "app.repair.local_verifier",
                "app.repair.verifier_interface",
            }:
                raise
            raise RuntimeError(
                "Repair verification requires Member 1's "
                "app.repair.verifier_interface and LocalVerifier modules."
            ) from exc

        return LocalVerifier(test_code=self.test_code).verify(
            patched_code=patched_code,
            file_path=file_path,
        )

    def verify_patch(
        self,
        patch: PatchLike,
        original_file: str | Path,
        workspace: str | Path,
        test_timeout: float = 60,
        tests: list[str] | None = None,
        python: str | Path | None = None,
    ) -> dict:
        """Verify a generated patch against the project's full test suite."""
        from app.verification.runner import run_patch_verification

        options = {}
        if tests is not None:
            options["tests"] = tests
        if python is not None:
            options["python"] = python

        return run_patch_verification(
            patched_code=patch.fixed_code,
            original_file=original_file,
            workspace=workspace,
            test_timeout=test_timeout,
            **options,
        )

    def verify_patch_result(
        self,
        patch: PatchLike,
        original_file: str | Path,
        workspace: str | Path,
        test_timeout: float = 60,
    ) -> VerificationResult:
        """Normalize the project report for the repair retry protocol."""
        from app.repair.verifier_interface import VerificationResult

        report = self.verify_patch(
            patch=patch,
            original_file=original_file,
            workspace=workspace,
            test_timeout=test_timeout,
        )
        comparison = report.get("comparison", {})
        checks = report.get("checks", {})
        syntax_result = checks.get("syntax", {})
        test_result = checks.get("tests", {})
        baseline_result = report.get("baseline_tests", {})
        assessment = comparison.get("assessment", "inconclusive")

        passed = (
            report.get("status") == "passed"
            and syntax_result.get("passed") is True
            and test_result.get("passed") is True
            and baseline_result.get("passed") is True
            and comparison.get("baseline_status") == "passed"
            and comparison.get("patched_status") == "passed"
            and assessment == "both_passed"
        )

        if passed:
            stage = "none"
            error = ""
        elif checks.get("setup", {}).get("status") == "error":
            stage = "tests"
            error = (
                "Project verification setup failed: "
                f"{checks['setup'].get('error', 'unknown setup error')}"
            )
        elif (
            syntax_result.get("passed") is False
            and syntax_result.get("status") != "skipped"
            and syntax_result.get("errors")
        ):
            stage = "syntax"
            syntax_errors = syntax_result.get("errors", [])
            error = "Patched project contains syntax errors."
            if syntax_errors:
                error = f"{error} {syntax_errors[0].get('message', '')}".strip()
        else:
            stage = "tests"
            if test_result.get("status") == "timeout":
                error = "Patched project verification timed out."
            elif baseline_result.get("status") == "timeout":
                error = "Baseline project verification timed out."
            elif assessment == "baseline_passed_patched_failed":
                error = "Patched project tests regressed relative to the passing baseline."
            elif assessment == "baseline_failed_patched_passed":
                error = (
                    "Project verification is inconclusive: baseline tests failed "
                    "while patched tests passed."
                )
            elif assessment == "both_failed":
                error = "Project verification is inconclusive: baseline and patched tests failed."
            else:
                failed_checks = report.get("failed_checks", [])
                error = (
                    f"Project verification is inconclusive (assessment: {assessment}); "
                    f"failed checks: {', '.join(failed_checks) or 'none'}."
                )

            for result in (test_result, baseline_result):
                if result.get("error"):
                    error = f"{error} {result['error']}"

        return VerificationResult(
            passed=passed,
            stage=stage,
            error=error,
            output=json.dumps(report, indent=2, ensure_ascii=False),
            project_report=report,
        )