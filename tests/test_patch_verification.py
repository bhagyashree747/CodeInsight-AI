"""Tests for verifying patches in isolated project workspaces."""

from pathlib import Path

import app.verification.runner as runner_module
from app.verification.runner import run_patch_verification


def _create_workspace(workspace: Path, expected_value: int) -> Path:
    source_file = workspace / "app" / "calculator.py"
    source_file.parent.mkdir(parents=True)
    (source_file.parent / "__init__.py").write_text("", encoding="utf-8")
    source_file.write_text(
        f"def value():\n    return {expected_value}\n",
        encoding="utf-8",
    )
    test_file = workspace / "tests" / "test_calculator.py"
    test_file.parent.mkdir()
    test_file.write_text(
        "from app.calculator import value\n\n"
        "def test_value():\n"
        "    assert value() == 2\n",
        encoding="utf-8",
    )
    return source_file


def _snapshot_workspace(workspace: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(workspace)): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }


def test_patch_verification_compares_full_suites_without_modifying_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    source_file = _create_workspace(workspace, expected_value=1)
    original_workspace = _snapshot_workspace(workspace)

    report = run_patch_verification(
        patched_code="def value():\n    return 2\n",
        original_file=source_file,
        workspace=workspace,
        test_timeout=20,
    )

    assert report["status"] == "passed"
    assert report["target"] == str(source_file.resolve())
    assert report["checks"]["syntax"]["passed"] is True
    assert report["checks"]["syntax"]["files_checked"] == 3
    assert report["checks"]["tests"]["status"] == "passed"
    assert report["baseline_tests"]["status"] == "failed"
    assert report["comparison"] == {
        "baseline_status": "failed",
        "patched_status": "passed",
        "assessment": "baseline_failed_patched_passed",
    }
    assert _snapshot_workspace(workspace) == original_workspace


def test_patch_verification_reports_test_regressions(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    source_file = _create_workspace(workspace, expected_value=2)
    original_workspace = _snapshot_workspace(workspace)

    report = run_patch_verification(
        patched_code="def value():\n    return 1\n",
        original_file=source_file,
        workspace=workspace,
        test_timeout=20,
    )

    assert report["status"] == "failed"
    assert report["baseline_tests"]["status"] == "passed"
    assert report["checks"]["tests"]["status"] == "failed"
    assert report["comparison"]["assessment"] == "baseline_passed_patched_failed"
    assert _snapshot_workspace(workspace) == original_workspace


def test_patch_syntax_failure_skips_patched_suite(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    source_file = _create_workspace(workspace, expected_value=2)
    original_workspace = _snapshot_workspace(workspace)

    report = run_patch_verification(
        patched_code="def value(:\n",
        original_file=source_file,
        workspace=workspace,
        test_timeout=20,
    )

    assert report["status"] == "failed"
    assert report["checks"]["syntax"]["passed"] is False
    assert report["checks"]["tests"]["status"] == "skipped"
    assert report["comparison"]["assessment"] == "inconclusive"
    assert report["checks"]["syntax"]["errors"][0]["file"] == str(source_file)
    assert _snapshot_workspace(workspace) == original_workspace


def test_baseline_timeout_makes_comparison_inconclusive_and_preserves_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    source_file = _create_workspace(workspace, expected_value=2)
    original_workspace = _snapshot_workspace(workspace)
    results = [
        {"passed": False, "status": "timeout", "error": "baseline timeout"},
        {"passed": True, "status": "passed", "error": None},
    ]
    monkeypatch.setattr(runner_module, "run_tests", lambda *args, **kwargs: results.pop(0))

    report = run_patch_verification(
        patched_code="def value():\n    return 2\n",
        original_file=source_file,
        workspace=workspace,
    )

    assert report["baseline_tests"]["status"] == "timeout"
    assert report["checks"]["tests"]["status"] == "passed"
    assert report["comparison"]["assessment"] == "inconclusive"
    assert _snapshot_workspace(workspace) == original_workspace


def test_patched_timeout_makes_comparison_inconclusive_and_preserves_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    source_file = _create_workspace(workspace, expected_value=2)
    original_workspace = _snapshot_workspace(workspace)
    results = [
        {"passed": True, "status": "passed", "error": None},
        {"passed": False, "status": "timeout", "error": "patched timeout"},
    ]
    monkeypatch.setattr(runner_module, "run_tests", lambda *args, **kwargs: results.pop(0))

    report = run_patch_verification(
        patched_code="def value():\n    return 2\n",
        original_file=source_file,
        workspace=workspace,
    )

    assert report["baseline_tests"]["status"] == "passed"
    assert report["checks"]["tests"]["status"] == "timeout"
    assert report["comparison"]["assessment"] == "inconclusive"
    assert _snapshot_workspace(workspace) == original_workspace


def test_baseline_execution_error_makes_comparison_inconclusive_and_preserves_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    source_file = _create_workspace(workspace, expected_value=2)
    original_workspace = _snapshot_workspace(workspace)
    results = [
        {"passed": False, "status": "error", "error": "could not start pytest"},
        {"passed": True, "status": "passed", "error": None},
    ]
    monkeypatch.setattr(runner_module, "run_tests", lambda *args, **kwargs: results.pop(0))

    report = run_patch_verification(
        patched_code="def value():\n    return 2\n",
        original_file=source_file,
        workspace=workspace,
    )

    assert report["baseline_tests"]["status"] == "error"
    assert report["checks"]["tests"]["status"] == "passed"
    assert report["comparison"]["assessment"] == "inconclusive"
    assert _snapshot_workspace(workspace) == original_workspace


def test_invalid_workspace_is_reported_as_setup_failure(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    source_file = _create_workspace(workspace, expected_value=2)
    original_workspace = _snapshot_workspace(workspace)

    report = run_patch_verification(
        patched_code="def value():\n    return 2\n",
        original_file=source_file,
        workspace=tmp_path / "missing-workspace",
    )

    assert report["checks"]["setup"]["status"] == "error"
    assert report["failed_checks"] == ["setup"]
    assert report["checks"]["syntax"]["status"] == "skipped"
    assert report["checks"]["tests"]["status"] == "skipped"
    assert report["comparison"]["assessment"] == "inconclusive"
    assert _snapshot_workspace(workspace) == original_workspace


def test_invalid_source_file_is_reported_as_setup_failure(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "project"
    _create_workspace(workspace, expected_value=2)
    original_workspace = _snapshot_workspace(workspace)

    report = run_patch_verification(
        patched_code="def value():\n    return 2\n",
        original_file="app/missing.py",
        workspace=workspace,
    )

    assert report["checks"]["setup"]["status"] == "error"
    assert report["failed_checks"] == ["setup"]
    assert report["checks"]["syntax"]["status"] == "skipped"
    assert report["checks"]["tests"]["status"] == "skipped"
    assert report["comparison"]["assessment"] == "inconclusive"
    assert _snapshot_workspace(workspace) == original_workspace
