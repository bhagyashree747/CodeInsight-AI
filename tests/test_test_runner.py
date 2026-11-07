"""Tests for the CodeInsight-AI automated test runner."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import app.verification.test_runner as test_runner_module
from app.verification.test_runner import run_tests


def test_passing_tests_return_passed_status(tmp_path: Path) -> None:
    """A test file whose assertions pass should pass."""
    test_file = tmp_path / "test_example.py"
    test_file.write_text(
        "def test_addition():\n"
        "    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )

    result = run_tests(test_file)

    assert result["passed"] is True
    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert result["error"] is None


def test_failing_tests_return_failed_status(tmp_path: Path) -> None:
    """A failed assertion should be captured."""
    test_file = tmp_path / "test_example.py"
    test_file.write_text(
        "def test_addition():\n"
        "    assert 2 + 2 == 5\n",
        encoding="utf-8",
    )

    result = run_tests(test_file)

    assert result["passed"] is False
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert "AssertionError" in result["stdout"]


def test_missing_path_returns_error(tmp_path: Path) -> None:
    """A nonexistent target should return a clear error."""
    result = run_tests(tmp_path / "missing")

    assert result["passed"] is False
    assert result["status"] == "error"
    assert result["error"] is not None


def test_non_python_file_is_rejected(tmp_path: Path) -> None:
    """The runner should reject files that are not Python files."""
    target = tmp_path / "notes.txt"
    target.write_text("not a Python test file", encoding="utf-8")

    result = run_tests(target)

    assert result["passed"] is False
    assert result["status"] == "error"
    assert "Python test file" in result["error"]


def test_nonpositive_timeout_is_rejected(tmp_path: Path) -> None:
    """A timeout must be greater than zero."""
    test_file = tmp_path / "test_example.py"
    test_file.write_text(
        "def test_example():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    result = run_tests(test_file, timeout=0)

    assert result["passed"] is False
    assert result["status"] == "error"
    assert "Timeout" in result["error"]


def test_pytest_collection_error_is_not_reported_as_test_failure(
    tmp_path: Path,
) -> None:
    test_file = tmp_path / "test_broken.py"
    test_file.write_text("def test_broken(:\n", encoding="utf-8")

    result = run_tests(test_file)

    assert result["passed"] is False
    assert result["status"] == "error"
    assert result["exit_code"] == 2
    assert "SyntaxError" in result["stdout"] or "SyntaxError" in result["stderr"]


def test_pytest_timeout_is_reported(tmp_path: Path) -> None:
    test_file = tmp_path / "test_slow.py"
    test_file.write_text(
        "import time\n"
        "def test_slow():\n"
        "    time.sleep(2)\n",
        encoding="utf-8",
    )

    result = run_tests(test_file, timeout=0.5)

    assert result["passed"] is False
    assert result["status"] == "timeout"
    assert result["duration_seconds"] is not None
    assert 0 < result["duration_seconds"] < 2
    assert len(result["stdout"]) <= 4000
    assert len(result["stderr"]) <= 4000
    assert "timeout" in result["error"].lower()


def test_timeout_terminates_child_process(tmp_path: Path) -> None:
    test_file = tmp_path / "test_spawn_child.py"
    child_pid_file = tmp_path / "child.pid"
    child_marker = tmp_path / "child_survived.txt"
    child_code = (
        "import os, pathlib, time\n"
        "time.sleep(6)\n"
        f"pathlib.Path({str(child_marker)!r}).write_text('survived')\n"
    )
    test_file.write_text(
        "import pathlib, subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        f"pathlib.Path({str(child_pid_file)!r}).write_text("
        "f'{child.pid},{time.monotonic()}')\n"
        "time.sleep(30)\n"
        "def test_spawn_child():\n"
        "    assert True\n",
        encoding="utf-8",
    )

    def cleanup_child() -> None:
        if not child_pid_file.exists():
            return
        try:
            child_pid = int(
                child_pid_file.read_text(encoding="utf-8").split(",", maxsplit=1)[0]
            )
        except (OSError, ValueError):
            return

        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(child_pid), "/T", "/F"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                    shell=False,
                )
            else:
                os.kill(child_pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError, ProcessLookupError):
            pass

    try:
        result = run_tests(test_file, timeout=4.0)

        assert result["status"] == "timeout"
        assert result["duration_seconds"] is not None
        assert child_pid_file.exists()

        _, child_started_at = child_pid_file.read_text(encoding="utf-8").split(
            ",", maxsplit=1
        )
        deadline = float(child_started_at) + 6.2
        while time.monotonic() < deadline and not child_marker.exists():
            time.sleep(0.05)

        assert not child_marker.exists(), "child continued after timeout cleanup"
    finally:
        cleanup_child()


def test_subprocess_start_error_is_reported(tmp_path: Path, monkeypatch) -> None:
    test_file = tmp_path / "test_example.py"
    test_file.write_text("def test_example():\n    assert True\n", encoding="utf-8")

    def fail_to_start(*args, **kwargs):
        raise OSError("process unavailable")

    monkeypatch.setattr(test_runner_module.subprocess, "Popen", fail_to_start)

    result = run_tests(test_file)

    assert result["passed"] is False
    assert result["status"] == "error"
    assert "Could not start pytest" in result["error"]


def test_large_stdout_and_stderr_are_drained_and_bounded(
    tmp_path: Path,
    monkeypatch,
) -> None:
    test_file = tmp_path / "test_example.py"
    test_file.write_text("def test_example():\n    assert True\n", encoding="utf-8")
    original_popen = test_runner_module.subprocess.Popen
    child_script = (
        "import sys\n"
        "sys.stdout.write('O' * 1000000)\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('E' * 1000000)\n"
        "sys.stderr.flush()\n"
        "sys.exit(1)\n"
    )

    def emit_large_output(command, **kwargs):
        return original_popen(
            [test_runner_module.sys.executable, "-c", child_script],
            **kwargs,
        )

    monkeypatch.setattr(test_runner_module.subprocess, "Popen", emit_large_output)

    result = run_tests(test_file)

    assert result["passed"] is False
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert len(result["stdout"]) <= 4000
    assert len(result["stderr"]) <= 4000
    assert result["stdout"].startswith("[...output truncated...]")
    assert result["stderr"].startswith("[...output truncated...]")
    assert result["stdout"].endswith("O" * 100)
    assert result["stderr"].endswith("E" * 100)


def test_timeout_must_be_finite(tmp_path: Path) -> None:
    test_file = tmp_path / "test_example.py"
    test_file.write_text("def test_example():\n    assert True\n", encoding="utf-8")

    result = run_tests(test_file, timeout=float("inf"))

    assert result["passed"] is False
    assert result["status"] == "error"


def test_unrepresentably_large_timeout_is_rejected(tmp_path: Path) -> None:
    test_file = tmp_path / "test_example.py"
    test_file.write_text("def test_example():\n    assert True\n", encoding="utf-8")

    result = run_tests(test_file, timeout=10**10000)

    assert result["passed"] is False
    assert result["status"] == "error"