"""Main entry point for CodeInsight-AI verification."""

import json
import sys
from pathlib import Path

try:
    from .syntax import check_python_syntax
    from .test_runner import run_tests
except ImportError:
    from syntax import check_python_syntax
    from test_runner import run_tests


def run_verification(
    target: str | Path,
    run_test_suite: bool = False,
    test_timeout: int = 60,
) -> dict:
    """
    Run syntax verification and optionally execute automated tests.

    Args:
        target: Python file or project directory to inspect.
        run_test_suite: Whether to execute pytest tests.
        test_timeout: Maximum test execution time in seconds.

    Returns:
        A structured verification report.
    """
    path = Path(target).resolve()
    syntax_result = check_python_syntax(path)

    checks = {
        "syntax": syntax_result,
    }

    # Only run tests when syntax verification passes.
    # This avoids executing tests when the inspected code has syntax errors.
    if run_test_suite:
        if syntax_result["passed"]:
            test_result = run_tests(path, timeout=test_timeout)
        else:
            test_result = {
                "passed": False,
                "status": "skipped",
                "exit_code": None,
                "stdout": "",
                "stderr": "",
                "error": "Tests skipped because syntax verification failed.",
                "duration_seconds": None,
            }

        checks["tests"] = test_result

    failed_checks = [
        name
        for name, result in checks.items()
        if not result["passed"]
    ]

    return {
        "status": "passed" if not failed_checks else "failed",
        "target": str(path),
        "checks": checks,
        "failed_checks": failed_checks,
    }


def main() -> int:
    """Run verification from the command line."""
    target = sys.argv[1] if len(sys.argv) > 1 else "."

    # CLI usage:
    # python -m app.verification.runner .
    # python -m app.verification.runner . --tests
    run_test_suite = "--tests" in sys.argv[2:]

    result = run_verification(
        target,
        run_test_suite=run_test_suite,
    )

    print(json.dumps(result, indent=2))

    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())