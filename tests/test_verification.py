"""Automated tests for the CodeInsight-AI verification engine."""

from pathlib import Path

from app.verification.syntax import check_python_syntax
from app.verification.runner import run_verification


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
    error = result["errors"][0]
    assert error["file"] == str(source_file.resolve())
    assert error["line"] is not None
    assert error["column"] is not None
    assert error["message"]


def test_missing_file_fails(tmp_path: Path) -> None:
    """A nonexistent file should produce a clear failure result."""
    missing_file = tmp_path / "does_not_exist.py"

    result = check_python_syntax(missing_file)

    assert result["passed"] is False
    assert result["files_checked"] == 0
    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert set(error) == {"file", "line", "column", "message"}
    assert error["file"] == str(missing_file)
    assert error["line"] is None
    assert error["column"] is None
    assert error["message"].startswith("Could not access path")


def test_embedded_null_path_returns_structured_syntax_error() -> None:
    target = "bad\0path.py"

    result = check_python_syntax(target)

    assert result["passed"] is False
    assert result["files_checked"] == 0
    assert len(result["errors"]) == 1
    error = result["errors"][0]
    assert set(error) == {"file", "line", "column", "message"}
    assert error["file"] == target
    assert error["line"] is None
    assert error["column"] is None
    assert error["message"].startswith("Could not access path")


def test_non_python_file_is_rejected(tmp_path: Path) -> None:
    """A non-Python file should not be accepted by the syntax checker."""
    source_file = tmp_path / "example.txt"
    source_file.write_text("This is not Python.", encoding="utf-8")

    result = check_python_syntax(source_file)

    assert result["passed"] is False
    assert result["files_checked"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["file"] == str(source_file.resolve())
    assert result["errors"][0]["line"] is None
    assert result["errors"][0]["column"] is None
    assert result["errors"][0]["message"].startswith("Expected a Python")


def test_utf8_bom_and_non_ascii_source_pass(tmp_path: Path) -> None:
    source_file = tmp_path / "utf8_example.py"
    source_file.write_bytes(
        b"\xef\xbb\xbf# caf\xc3\xa9\nvalue = 'na\xc3\xafve'\n"
    )

    result = check_python_syntax(source_file)

    assert result["passed"] is True
    assert result["files_checked"] == 1


def test_invalid_utf8_file_fails_without_crashing(tmp_path: Path) -> None:
    source_file = tmp_path / "invalid_encoding.py"
    source_file.write_bytes(b"value = '\xff'\n")

    result = check_python_syntax(source_file)

    assert result["passed"] is False
    assert result["files_checked"] == 1
    assert result["errors"][0]["file"] == str(source_file.resolve())
    assert result["errors"][0]["line"] is None
    assert result["errors"][0]["column"] is None
    assert result["errors"][0]["message"].startswith("Could not read file:")


def test_directory_checks_only_python_files_outside_excluded_directories(
    tmp_path: Path,
) -> None:
    valid_file = tmp_path / "valid.py"
    invalid_file = tmp_path / "invalid.py"
    notes_file = tmp_path / "notes.txt"
    excluded_file = tmp_path / ".venv" / "Lib" / "invalid.py"

    valid_file.write_text("value = 1\n", encoding="utf-8")
    invalid_file.write_text("def broken(:\n", encoding="utf-8")
    notes_file.write_text("not Python syntax: (", encoding="utf-8")
    excluded_file.parent.mkdir(parents=True)
    excluded_file.write_text("def also_broken(:\n", encoding="utf-8")

    result = check_python_syntax(tmp_path)

    assert result["passed"] is False
    assert result["files_checked"] == 2
    assert [error["file"] for error in result["errors"]] == [
        str(invalid_file.resolve())
    ]


def test_missing_directory_fails(tmp_path: Path) -> None:
    result = check_python_syntax(tmp_path / "missing_directory")

    assert result["passed"] is False
    assert result["files_checked"] == 0
    assert result["errors"]


def test_excluded_directories_are_not_scanned(tmp_path: Path) -> None:
    source_file = tmp_path / ".venv" / "Lib" / "bad.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("def broken(:\n", encoding="utf-8")

    result = check_python_syntax(tmp_path)

    assert result["passed"] is True
    assert result["files_checked"] == 0


def test_unreadable_file_is_reported(tmp_path: Path, monkeypatch) -> None:
    source_file = tmp_path / "unreadable.py"
    source_file.write_text("value = 1\n", encoding="utf-8")
    original_read_text = Path.read_text

    def deny_read(path: Path, *args, **kwargs):
        if path == source_file:
            raise PermissionError("access denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_read)

    result = check_python_syntax(source_file)

    assert result["passed"] is False
    assert result["errors"][0]["message"].startswith("Could not read file:")


def test_directory_traversal_error_is_reported(tmp_path: Path, monkeypatch) -> None:
    import app.verification.syntax as syntax_module

    def fail_walk(path, *, topdown, followlinks, onerror):
        assert followlinks is False
        onerror(PermissionError(13, "access denied", str(path)))
        return iter(())

    monkeypatch.setattr(syntax_module.os, "walk", fail_walk)

    result = check_python_syntax(tmp_path)

    assert result["passed"] is False
    assert result["errors"][0]["file"] == str(tmp_path)
    assert result["errors"][0]["line"] is None
    assert result["errors"][0]["column"] is None
    assert result["errors"][0]["message"].startswith("Could not scan directory:")


def test_invalid_target_type_returns_structured_error() -> None:
    result = check_python_syntax(123)  # type: ignore[arg-type]

    assert result["passed"] is False
    assert result["files_checked"] == 0
    assert result["errors"][0]["file"] == "123"
    assert result["errors"][0]["line"] is None
    assert result["errors"][0]["column"] is None
    assert result["errors"][0]["message"].startswith("Could not access path")


def test_directory_scan_skips_symlinks_outside_requested_root(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()

    (root / "inside.py").write_text("value = 1\n", encoding="utf-8")
    outside_file = outside / "external.py"
    outside_file.write_text("def external_broken(:\n", encoding="utf-8")
    outside_dir = outside / "external_dir"
    outside_dir.mkdir()
    (outside_dir / "external_nested.py").write_text(
        "def nested_broken(:\n",
        encoding="utf-8",
    )

    try:
        (root / "external_file.py").symlink_to(outside_file)
        (root / "external_dir").symlink_to(outside_dir, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        import pytest

        pytest.skip(f"Symlinks are unavailable: {exc}")

    result = check_python_syntax(root)

    assert result["passed"] is True
    assert result["files_checked"] == 1
    assert result["errors"] == []


def test_requested_tests_are_reported_skipped_after_syntax_failure(
    tmp_path: Path,
) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    report = run_verification(tmp_path, run_test_suite=True)

    assert report["status"] == "failed"
    assert report["failed_checks"] == ["syntax", "tests"]
    assert report["checks"]["tests"]["status"] == "skipped"


def test_default_runner_only_performs_syntax_check(tmp_path: Path) -> None:
    (tmp_path / "valid.py").write_text("value = 1\n", encoding="utf-8")

    report = run_verification(tmp_path)

    assert report["status"] == "passed"
    assert set(report["checks"]) == {"syntax"}
    assert report["duration_seconds"] >= 0


def test_runner_returns_structured_error_for_embedded_null_path() -> None:
    target = "bad\0path.py"
    expected_path = str(Path(target).absolute())

    report = run_verification(target)

    assert report["status"] == "failed"
    assert report["target"] == expected_path
    assert report["failed_checks"] == ["syntax"]
    error = report["checks"]["syntax"]["errors"][0]
    assert set(error) == {"file", "line", "column", "message"}
    assert error["file"] == expected_path
    assert error["line"] is None
    assert error["column"] is None
    assert error["message"].startswith("Could not access path")