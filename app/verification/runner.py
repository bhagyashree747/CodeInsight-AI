"""Main entry point for CodeInsight-AI verification."""

import json
import shutil
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from .syntax import check_python_syntax
    from .test_runner import run_tests
except ImportError:
    from syntax import check_python_syntax
    from test_runner import run_tests


_WORKSPACE_EXCLUDED_ENTRIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "env",
    "node_modules",
    "site-packages",
    "venv",
}


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
    start_time = time.monotonic()
    unresolved_path = Path(target).expanduser()
    try:
        path = unresolved_path.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        path = unresolved_path.absolute()
        syntax_result = {
            "passed": False,
            "files_checked": 0,
            "errors": [
                {
                    "file": str(path),
                    "line": None,
                    "column": None,
                    "message": f"Could not access path {target}: {exc}",
                }
            ],
        }
    else:
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
        name for name, result in checks.items() if not result.get("passed", False)
    ]

    return {
        "status": "passed" if not failed_checks else "failed",
        "target": str(path),
        "checks": checks,
        "failed_checks": failed_checks,
        "duration_seconds": round(time.monotonic() - start_time, 3),
    }


def run_patch_verification(
    patched_code: str,
    original_file: str | Path,
    workspace: str | Path,
    test_timeout: float = 60,
) -> dict:
    """
    Compare the project's baseline and patched test suites in temporary copies.

    The workspace root is passed to pytest so it discovers the project's full
    test suite. The original workspace is only read and is never modified.
    Test code is executed; this is not a security sandbox.
    """
    start_time = time.monotonic()
    display_target = str(original_file)

    def failed_report(message: str) -> dict:
        setup_result = {
            "passed": False,
            "status": "error",
            "error": message,
        }
        skipped_syntax = {
            "passed": False,
            "status": "skipped",
            "files_checked": 0,
            "errors": [],
        }
        skipped_tests = {
            "passed": False,
            "status": "skipped",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": "Tests skipped because patch verification setup failed.",
            "duration_seconds": None,
        }
        return {
            "status": "failed",
            "target": display_target,
            "checks": {
                "setup": setup_result,
                "syntax": skipped_syntax,
                "tests": skipped_tests,
            },
            "failed_checks": ["setup"],
            "duration_seconds": round(time.monotonic() - start_time, 3),
            "baseline_tests": skipped_tests,
            "comparison": {
                "baseline_status": "skipped",
                "patched_status": "skipped",
                "assessment": "inconclusive",
            },
        }

    if not isinstance(patched_code, str):
        return failed_report("Patched source must be a string.")

    try:
        workspace_path = Path(workspace).expanduser().resolve(strict=True)
        if not workspace_path.is_dir():
            return failed_report(f"Workspace must be a directory: {workspace_path}")

        source_path = Path(original_file).expanduser()
        if not source_path.is_absolute():
            source_path = workspace_path / source_path
        source_path = source_path.resolve(strict=True)
        relative_source = source_path.relative_to(workspace_path)
        if not source_path.is_file() or source_path.suffix != ".py":
            return failed_report(
                f"Patched source must be an existing Python file: {source_path}"
            )
        display_target = str(source_path)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return failed_report(f"Could not resolve patch workspace or file: {exc}")

    def ignore_generated(directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in _WORKSPACE_EXCLUDED_ENTRIES
            or (Path(directory) / name).is_symlink()
        }

    try:
        with TemporaryDirectory(prefix="codeinsight-patch-verification-") as temp_dir:
            temp_root = Path(temp_dir)
            baseline_workspace = temp_root / "baseline"
            patched_workspace = temp_root / "patched"
            shutil.copytree(
                workspace_path,
                baseline_workspace,
                ignore=ignore_generated,
            )
            shutil.copytree(
                workspace_path,
                patched_workspace,
                ignore=ignore_generated,
            )

            baseline_tests = run_tests(baseline_workspace, timeout=test_timeout)

            patched_file = patched_workspace / relative_source
            patched_file.parent.mkdir(parents=True, exist_ok=True)
            patched_file.write_text(patched_code, encoding="utf-8")

            syntax_result = check_python_syntax(patched_workspace)
            for error in syntax_result["errors"]:
                try:
                    error_path = Path(error["file"]).resolve().relative_to(
                        patched_workspace.resolve()
                    )
                except (OSError, RuntimeError, ValueError):
                    continue
                error["file"] = str(workspace_path / error_path)

            if syntax_result["passed"]:
                patched_tests = run_tests(
                    patched_workspace,
                    timeout=test_timeout,
                )
            else:
                patched_tests = {
                    "passed": False,
                    "status": "skipped",
                    "exit_code": None,
                    "stdout": "",
                    "stderr": "",
                    "error": "Tests skipped because syntax verification failed.",
                    "duration_seconds": None,
                }

    except (OSError, shutil.Error) as exc:
        return failed_report(f"Could not prepare isolated patch workspaces: {exc}")

    checks = {"syntax": syntax_result, "tests": patched_tests}
    failed_checks = [
        name for name, result in checks.items() if not result.get("passed", False)
    ]

    baseline_status = baseline_tests["status"]
    patched_status = patched_tests["status"]
    if baseline_status not in {"passed", "failed"} or patched_status not in {
        "passed",
        "failed",
    }:
        assessment = "inconclusive"
    elif baseline_status == "passed" and patched_status == "failed":
        assessment = "baseline_passed_patched_failed"
    elif baseline_status == "failed" and patched_status == "passed":
        assessment = "baseline_failed_patched_passed"
    elif baseline_status == "passed":
        assessment = "both_passed"
    else:
        assessment = "both_failed"

    return {
        "status": "passed" if not failed_checks else "failed",
        "target": display_target,
        "checks": checks,
        "failed_checks": failed_checks,
        "duration_seconds": round(time.monotonic() - start_time, 3),
        "baseline_tests": baseline_tests,
        "comparison": {
            "baseline_status": baseline_status,
            "patched_status": patched_status,
            "assessment": assessment,
        },
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