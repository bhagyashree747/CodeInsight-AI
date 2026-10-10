"""Local verifier executing syntax compilation, optional ruff linting, and pytest suites."""

import logging
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from app.repair.verifier_interface import VerificationResult, Verifier

logger = logging.getLogger(__name__)


class LocalVerifier(Verifier):
    """Verifies patched code through Python syntax compilation, optional ruff, and isolated pytest suites."""

    def __init__(self, test_code: str | None = None) -> None:
        self.test_code = test_code

    def verify(self, patched_code: str, file_path: str = "snippet.py") -> VerificationResult:
        """Run verification pipeline: Stage 1 (Syntax) -> Stage 2 (Lint) -> Stage 3 (Tests)."""
        # Stage 1: Syntax compilation
        syntax_res = self._check_syntax(patched_code, file_path)
        if not syntax_res.passed:
            return syntax_res

        # Stage 2: Lint via ruff (if available)
        lint_res = self._check_lint(patched_code, file_path)
        if not lint_res.passed:
            return lint_res

        # Stage 3: Tests via pytest (if test_code is supplied)
        if self.test_code is not None:
            test_res = self._check_tests(patched_code, file_path)
            if not test_res.passed:
                return test_res

        return VerificationResult(
            passed=True,
            stage="none",
            error="",
            output="All verification checks passed successfully.",
        )

    def _check_syntax(self, code: str, file_path: str) -> VerificationResult:
        """Stage 1: Validate code syntax using Python's built-in compile()."""
        try:
            compile(code, file_path, "exec")
            return VerificationResult(
                passed=True,
                stage="none",
                error="",
                output="Syntax compilation successful.",
            )
        except SyntaxError as err:
            lineno = err.lineno or 0
            err_msg = f"SyntaxError at line {lineno}: {err.msg}"
            err_line = (err.text or "").strip()
            output = f'File "{file_path}", line {lineno}\n    {err_line}\nSyntaxError: {err.msg}'
            logger.debug("Syntax verification failed: %s", err_msg)
            return VerificationResult(
                passed=False,
                stage="syntax",
                error=err_msg,
                output=output,
            )

    def _check_lint(self, code: str, file_path: str) -> VerificationResult:
        """Stage 2: Run ruff check on a temporary file if ruff is installed; skip silently otherwise."""
        ruff_bin = shutil.which("ruff")
        if not ruff_bin:
            return VerificationResult(
                passed=True,
                stage="none",
                error="",
                output="Ruff not found; lint stage skipped.",
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_name = Path(file_path).name or "snippet.py"
            if not file_name.endswith(".py"):
                file_name += ".py"
            temp_file = Path(tmp_dir) / file_name
            temp_file.write_text(code, encoding="utf-8")

            try:
                proc = subprocess.run(
                    [ruff_bin, "check", str(temp_file)],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if proc.returncode != 0:
                    combined = f"{proc.stdout}\n{proc.stderr}".strip()
                    trimmed = combined[:1500]
                    return VerificationResult(
                        passed=False,
                        stage="lint",
                        error="Ruff lint errors detected",
                        output=trimmed,
                    )
            except Exception as err:
                logger.warning("Ruff check invocation failed: %s", err)

        return VerificationResult(
            passed=True,
            stage="none",
            error="",
            output="Lint stage passed.",
        )

    def _check_tests(self, code: str, file_path: str) -> VerificationResult:
        """Stage 3: Run pytest in an isolated temporary directory with a 20s timeout."""
        if self.test_code is None:
            return VerificationResult(
                passed=True,
                stage="none",
                error="",
                output="No test code provided; test stage skipped.",
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            file_name = Path(file_path).name or "snippet.py"
            if not file_name.endswith(".py"):
                file_name += ".py"

            # Write patched file and test file in isolated temporary folder
            patched_file = tmp_path / file_name
            patched_file.write_text(code, encoding="utf-8")

            test_file = tmp_path / "test_verification.py"
            test_file.write_text(self.test_code, encoding="utf-8")

            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", str(test_file)],
                    cwd=str(tmp_path),
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if proc.returncode != 0:
                    combined = f"{proc.stdout}\n{proc.stderr}".strip()
                    trimmed = combined[:1500]
                    return VerificationResult(
                        passed=False,
                        stage="tests",
                        error="Pytest verification suite failed",
                        output=trimmed,
                    )
            except subprocess.TimeoutExpired:
                return VerificationResult(
                    passed=False,
                    stage="tests",
                    error="Pytest suite timed out after 20 seconds",
                    output="TimeoutExpired: pytest execution exceeded 20s limit.",
                )
            except Exception as err:
                return VerificationResult(
                    passed=False,
                    stage="tests",
                    error=f"Error executing pytest: {err}",
                    output=str(err)[:1500],
                )

        return VerificationResult(
            passed=True,
            stage="none",
            error="",
            output="Pytest verification suite passed.",
        )
