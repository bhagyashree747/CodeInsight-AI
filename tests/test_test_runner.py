"""Tests for the CodeInsight-AI automated test runner."""

from pathlib import Path

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