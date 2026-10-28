"""Adapter connecting verification tools to the AI repair interface."""

import tempfile
import time
from pathlib import Path

from app.verification.syntax import check_python_syntax
from app.verification.test_runner import run_tests


class RepairVerificationAdapter:
    """Verify repaired Python code using the existing verification tools."""

    def __init__(
        self,
        test_code: str | None = None,
        test_timeout: int = 20,
    ) -> None:
        if test_timeout <= 0:
            raise ValueError("test_timeout must be greater than zero")

        self.test_code = test_code
        self.test_timeout = test_timeout

    def verify(
        self,
        patched_code: str,
        file_path: str = "snippet.py",
    ):
        """Verify patched code and return Member 1's result model.

        The repair interface must be available when this method is called.
        """
        # Import lazily because Member 1's branch is not yet integrated.
        from app.repair.verifier_interface import VerificationResult

        start_time = time.monotonic()
        filename = Path(file_path).name or "snippet.py"

        if not filename.endswith(".py"):
            filename += ".py"

        # Stage 1: Write the proposed code to a temporary file and
        # reuse the existing syntax checker.
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / filename

            try:
                source_path.write_text(
                    patched_code,
                    encoding="utf-8",
                )
            except OSError as exc:
                return VerificationResult(
                    passed=False,
                    stage="syntax",
                    error=f"Could not write patched code: {exc}",
                    output=str(exc),
                )

            syntax_result = check_python_syntax(source_path)

            if not syntax_result["passed"]:
                errors = syntax_result["errors"]
                message = "; ".join(
                    (
                        f"Line {error['line']}: {error['message']}"
                        if error.get("line") is not None
                        else error["message"]
                    )
                    for error in errors
                )

                return VerificationResult(
                    passed=False,
                    stage="syntax",
                    error=message or "Python syntax verification failed.",
                    output=str(errors),
                )

            # Stage 2: Run the supplied tests, if provided.
            if self.test_code is not None:
                test_file = temp_path / "test_verification.py"

                try:
                    test_file.write_text(
                        self.test_code,
                        encoding="utf-8",
                    )
                except OSError as exc:
                    return VerificationResult(
                        passed=False,
                        stage="tests",
                        error=f"Could not write test code: {exc}",
                        output=str(exc),
                    )

                test_result = run_tests(
                    temp_path,
                    timeout=self.test_timeout,
                )

                if not test_result["passed"]:
                    details = "\n".join(
                        part
                        for part in (
                            test_result.get("stdout") or "",
                            test_result.get("stderr") or "",
                            test_result.get("error") or "",
                        )
                        if part
                    )

                    stage = (
                        "tests"
                        if test_result["status"] in {"failed", "timeout"}
                        else "none"
                    )

                    return VerificationResult(
                        passed=False,
                        stage=stage,
                        error=(
                            f"Automated tests {test_result['status']}."
                        ),
                        output=details[:4000],
                    )

        duration = round(time.monotonic() - start_time, 3)

        return VerificationResult(
            passed=True,
            stage="none",
            error="",
            output=(
                "Syntax verification passed. "
                + (
                    "Automated tests passed. "
                    if self.test_code is not None
                    else "Automated tests were not requested. "
                )
                + f"Verification duration: {duration} seconds."
            ),
        )