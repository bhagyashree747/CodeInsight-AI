"""Automated test execution for CodeInsight-AI."""

import os
import subprocess
import sys
from pathlib import Path


def run_tests(
    target: str | Path,
    timeout: int = 60,
) -> dict:
    """
    Run pytest for a trusted project target and capture the results.

    Args:
        target: A Python test file or directory containing tests.
        timeout: Maximum execution time in seconds.

    Returns:
        A dictionary containing the test status, exit code,
        captured output, and error details.
    """
    path = Path(target).resolve()

    if not path.exists():
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Path does not exist: {path}",
            "duration_seconds": None,
        }

    if not path.is_file() and not path.is_dir():
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Target must be a file or directory: {path}",
            "duration_seconds": None,
        }

    if path.is_file() and path.suffix != ".py":
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Expected a Python test file: {path}",
            "duration_seconds": None,
        }

    if timeout <= 0:
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": "Timeout must be greater than zero.",
            "duration_seconds": None,
        }

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        str(path),
    ]

    try:
        import time

        start_time = time.monotonic()

        completed = subprocess.run(
            command,
            cwd=str(path if path.is_dir() else path.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
            env=os.environ.copy(),
        )

        duration = round(time.monotonic() - start_time, 3)

        if completed.returncode == 0:
            status = "passed"
        elif completed.returncode == 1:
            status = "failed"
        else:
            status = "error"

        return {
            "passed": completed.returncode == 0,
            "status": status,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "error": None,
            "duration_seconds": duration,
        }

    except subprocess.TimeoutExpired as exc:
        return {
            "passed": False,
            "status": "timeout",
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "error": f"Tests exceeded the {timeout}-second timeout.",
            "duration_seconds": timeout,
        }

    except OSError as exc:
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Could not start pytest: {exc}",
            "duration_seconds": None,
        }