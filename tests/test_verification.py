"""Automated tests for the CodeInsight-AI verification engine."""

from pathlib import Path

from app.verification.syntax import check_python_syntax


def test_valid_python_file_passes(tmp_path: Path) -> None:
    """Valid Python code should pass syntax verification."""
    source_file = tmp_path / "valid_example.py"
    source_file.write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )

    result = check_python_syntax(source_file)

    assert result["passed"] is True
    assert result["files_checked"] == 1
    assert result["errors"] == []


def test_invalid_python_file_fails(tmp_path: Path) -> None:
    """Invalid Python code should fail and report its syntax error."""
    source_file = tmp_path / "invalid_example.py"
    source_file.write_text(
        "def add(a, b:\n    return a + b\n",
        encoding="utf-8",
    )

    result = check_python_syntax(source_file)

    assert result["passed"] is False
    assert result["files_checked"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["file"] == str(source_file.resolve())
    assert result["errors"][0]["line"] is not None
    assert result["errors"][0]["message"]


def test_missing_file_fails(tmp_path: Path) -> None:
    """A nonexistent file should produce a clear failure result."""
    missing_file = tmp_path / "does_not_exist.py"

    result = check_python_syntax(missing_file)

    assert result["passed"] is False
    assert result["files_checked"] == 0
    assert result["errors"]


def test_non_python_file_is_rejected(tmp_path: Path) -> None:
    """A non-Python file should not be accepted by the syntax checker."""
    source_file = tmp_path / "example.txt"
    source_file.write_text("This is not Python.", encoding="utf-8")

    result = check_python_syntax(source_file)

    assert result["passed"] is False
    assert result["files_checked"] == 0
    assert result["errors"]