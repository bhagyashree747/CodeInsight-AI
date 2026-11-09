"""Pipeline integration tests for project-level patch verification."""

import builtins
import importlib
from pathlib import Path

import pytest

import app.pipeline as pipeline_module
import app.repair.retry as retry_module
import app.verification.repair_adapter as adapter_module
from app.pipeline import run_pipeline
from app.repair.schema import Patch
from app.repair.verifier_interface import VerificationResult
from app.review.llm_client import MockLLMClient
from app.review.schema import Category, Finding, Severity
from app.verification.repair_adapter import RepairVerificationAdapter


@pytest.fixture
def generated_patch(monkeypatch):
    finding = Finding(
        file="app/calculator.py",
        line=1,
        category=Category.BUG,
        severity=Severity.HIGH,
        confidence=0.95,
        description="Incorrect calculation",
        suggested_fix_hint="Return the expected value",
    )
    patches = []
    feedback = []

    def fake_generate_patch(*, code, finding, attempt, failure_feedback, **kwargs):
        feedback.append(failure_feedback)
        patch = Patch(
            finding=finding,
            original_code=code,
            fixed_code="def value():\n    return 2\n",
            explanation="Correct calculation",
            diff="",
            attempt=attempt,
        )
        patches.append(patch)
        return patch

    monkeypatch.setattr(
        pipeline_module,
        "review",
        lambda **kwargs: [finding],
    )
    monkeypatch.setattr(retry_module, "generate_patch", fake_generate_patch)
    return finding, patches, feedback


def _passing_report() -> dict:
    passed = {
        "passed": True,
        "status": "passed",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "error": None,
        "duration_seconds": 0.1,
    }
    return {
        "status": "passed",
        "target": "app/calculator.py",
        "checks": {
            "syntax": {"passed": True, "files_checked": 2, "errors": []},
            "tests": passed,
        },
        "failed_checks": [],
        "duration_seconds": 0.2,
        "baseline_tests": passed,
        "comparison": {
            "baseline_status": "passed",
            "patched_status": "passed",
            "assessment": "both_passed",
        },
    }


def _regression_report() -> dict:
    report = _passing_report()
    failed = {
        "passed": False,
        "status": "failed",
        "exit_code": 1,
        "stdout": "AssertionError",
        "stderr": "",
        "error": "assertion failed",
        "duration_seconds": 0.1,
    }
    report["status"] = "failed"
    report["checks"]["tests"] = failed
    report["failed_checks"] = ["tests"]
    report["comparison"] = {
        "baseline_status": "passed",
        "patched_status": "failed",
        "assessment": "baseline_passed_patched_failed",
    }
    return report


def _normalise_report(monkeypatch, report: dict) -> VerificationResult:
    adapter = RepairVerificationAdapter()
    monkeypatch.setattr(adapter, "verify_patch", lambda **kwargs: report)
    return adapter.verify_patch_result(
        patch=object(),
        original_file="app/calculator.py",
        workspace=".",
    )


def test_setup_failure_and_skipped_syntax_are_not_classified_as_syntax(
    monkeypatch,
) -> None:
    report = {
        "status": "failed",
        "checks": {
            "setup": {
                "passed": False,
                "status": "error",
                "error": "workspace missing",
            },
            "syntax": {
                "passed": False,
                "status": "skipped",
                "files_checked": 0,
                "errors": [],
            },
            "tests": {"passed": False, "status": "skipped", "error": "setup failed"},
        },
        "failed_checks": ["setup"],
        "baseline_tests": {"passed": False, "status": "skipped"},
        "comparison": {"assessment": "inconclusive"},
    }

    result = _normalise_report(monkeypatch, report)

    assert result.passed is False
    assert result.stage == "tests"
    assert "setup failed" in result.error.lower()
    assert "syntax" not in result.error.lower()
    assert result.project_report == report


def test_skipped_syntax_preserves_baseline_timeout_classification(
    monkeypatch,
) -> None:
    report = {
        "status": "failed",
        "checks": {
            "syntax": {
                "passed": False,
                "status": "skipped",
                "files_checked": 0,
                "errors": [],
            },
            "tests": {"passed": False, "status": "skipped", "error": "not run"},
        },
        "failed_checks": ["syntax", "tests"],
        "baseline_tests": {"passed": False, "status": "timeout"},
        "comparison": {
            "baseline_status": "timeout",
            "patched_status": "skipped",
            "assessment": "inconclusive",
        },
    }

    result = _normalise_report(monkeypatch, report)

    assert result.passed is False
    assert result.stage == "tests"
    assert "baseline" in result.error.lower()
    assert "timed out" in result.error.lower()


def test_actual_patched_syntax_failure_is_classified_as_syntax(
    monkeypatch,
) -> None:
    report = {
        "status": "failed",
        "checks": {
            "syntax": {
                "passed": False,
                "files_checked": 1,
                "errors": [{"message": "invalid syntax"}],
            },
            "tests": {"passed": False, "status": "skipped"},
        },
        "failed_checks": ["syntax", "tests"],
        "baseline_tests": {"passed": True, "status": "passed"},
        "comparison": {
            "baseline_status": "passed",
            "patched_status": "skipped",
            "assessment": "inconclusive",
        },
    }

    result = _normalise_report(monkeypatch, report)

    assert result.passed is False
    assert result.stage == "syntax"
    assert "invalid syntax" in result.error
    assert result.project_report == report


def test_adapter_module_import_does_not_require_repair_interface(
    monkeypatch,
) -> None:
    original_import = builtins.__import__

    def reject_repair_interface(name, *args, **kwargs):
        if name == "app.repair.verifier_interface":
            raise ModuleNotFoundError(name=name)
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", reject_repair_interface)
        reloaded_module = importlib.reload(adapter_module)
        assert reloaded_module.RepairVerificationAdapter

    importlib.reload(adapter_module)


def test_pipeline_sends_full_patch_to_adapter_and_retains_report(
    tmp_path: Path,
    monkeypatch,
    generated_patch,
) -> None:
    source = tmp_path / "app" / "calculator.py"
    source.parent.mkdir()
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    finding, patches, _ = generated_patch
    report = _passing_report()
    calls = []

    def verify_patch(self, patch, original_file, workspace, test_timeout=60):
        calls.append((patch, original_file, workspace, test_timeout))
        return report

    monkeypatch.setattr(RepairVerificationAdapter, "verify_patch", verify_patch)

    result = run_pipeline(
        code=source.read_text(encoding="utf-8"),
        file="app/calculator.py",
        client=MockLLMClient(),
        project_workspace=tmp_path,
    )

    assert len(patches) == 1
    assert calls == [
        (patches[0], source.resolve(), tmp_path.resolve(), 60)
    ]
    repair = result["repairs"][0]
    assert repair["status"] == "verified"
    assert repair["project_verification_reports"] == [report]
    assert repair["finding"]["description"] == finding.description


def test_regression_is_passed_to_retry_feedback(
    tmp_path: Path,
    monkeypatch,
    generated_patch,
) -> None:
    source = tmp_path / "app" / "calculator.py"
    source.parent.mkdir()
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    _, patches, feedback = generated_patch
    reports = [_regression_report(), _passing_report()]

    monkeypatch.setattr(
        RepairVerificationAdapter,
        "verify_patch",
        lambda *args, **kwargs: reports.pop(0),
    )

    result = run_pipeline(
        code=source.read_text(encoding="utf-8"),
        file="app/calculator.py",
        client=MockLLMClient(),
        max_attempts=2,
        project_workspace=tmp_path,
    )

    repair = result["repairs"][0]
    assert len(patches) == 2
    assert feedback[0] is None
    assert "regressed" in feedback[1].lower()
    assert repair["status"] == "verified"
    assert repair["project_verification_reports"] == [
        _regression_report(),
        _passing_report(),
    ]


def test_timeout_report_is_retained_and_included_in_retry_feedback(
    tmp_path: Path,
    monkeypatch,
    generated_patch,
) -> None:
    source = tmp_path / "app" / "calculator.py"
    source.parent.mkdir()
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    _, patches, feedback = generated_patch
    timeout_report = _passing_report()
    timeout_report["status"] = "failed"
    timeout_report["checks"]["tests"] = {
        "passed": False,
        "status": "timeout",
        "error": "patched test suite timed out",
    }
    timeout_report["failed_checks"] = ["tests"]
    timeout_report["comparison"] = {
        "baseline_status": "passed",
        "patched_status": "timeout",
        "assessment": "inconclusive",
    }
    reports = [timeout_report, _passing_report()]
    monkeypatch.setattr(
        RepairVerificationAdapter,
        "verify_patch",
        lambda *args, **kwargs: reports.pop(0),
    )

    result = run_pipeline(
        code=source.read_text(encoding="utf-8"),
        file="app/calculator.py",
        client=MockLLMClient(),
        max_attempts=2,
        project_workspace=tmp_path,
    )

    repair = result["repairs"][0]
    assert len(patches) == 2
    assert "timed out" in feedback[1].lower()
    assert "patched test suite timed out" in feedback[1]
    assert repair["project_verification_reports"] == [
        timeout_report,
        _passing_report(),
    ]


def test_baseline_failure_with_passing_patch_is_inconclusive(
    tmp_path: Path,
    monkeypatch,
    generated_patch,
) -> None:
    source = tmp_path / "app" / "calculator.py"
    source.parent.mkdir()
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    baseline_failure = _passing_report()
    baseline_failure["baseline_tests"] = {
        "passed": False,
        "status": "failed",
        "error": "existing baseline assertion failure",
    }
    baseline_failure["comparison"] = {
        "baseline_status": "failed",
        "patched_status": "passed",
        "assessment": "baseline_failed_patched_passed",
    }
    monkeypatch.setattr(
        RepairVerificationAdapter,
        "verify_patch",
        lambda *args, **kwargs: baseline_failure,
    )

    result = run_pipeline(
        code=source.read_text(encoding="utf-8"),
        file="app/calculator.py",
        client=MockLLMClient(),
        max_attempts=1,
        project_workspace=tmp_path,
    )

    repair = result["repairs"][0]
    assert repair["status"] == "failed"
    assert repair["verification_stage"] == "tests"
    assert repair["project_verification_reports"] == [baseline_failure]


def test_invalid_project_workspace_fails_without_local_verifier_fallback(
    tmp_path: Path,
    monkeypatch,
    generated_patch,
) -> None:
    source = tmp_path / "app" / "calculator.py"
    source.parent.mkdir()
    source.write_text("def value():\n    return 1\n", encoding="utf-8")

    def unexpected_local_verifier(*args, **kwargs):
        pytest.fail("Project mode must not fall back to LocalVerifier.")

    monkeypatch.setattr(pipeline_module, "LocalVerifier", unexpected_local_verifier)

    result = run_pipeline(
        code=source.read_text(encoding="utf-8"),
        file="app/calculator.py",
        client=MockLLMClient(),
        max_attempts=1,
        project_workspace=tmp_path / "missing",
    )

    assert result["repairs"] == []
    assert any(
        "Invalid project verification paths" in error
        for error in result["pipeline_errors"]
    )


def test_project_file_must_exist_within_workspace(
    tmp_path: Path,
    generated_patch,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()

    result = run_pipeline(
        code="def value():\n    return 1\n",
        file="calculator.py",
        client=MockLLMClient(),
        project_workspace=workspace,
        project_file="missing.py",
    )

    assert result["repairs"] == []
    assert any(
        "Invalid project verification paths" in error
        for error in result["pipeline_errors"]
    )


def test_project_file_outside_workspace_is_rejected(
    tmp_path: Path,
    generated_patch,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    outside_file = tmp_path / "outside.py"
    outside_file.write_text("value = 1\n", encoding="utf-8")

    result = run_pipeline(
        code="value = 1\n",
        file="outside.py",
        client=MockLLMClient(),
        project_workspace=workspace,
        project_file=outside_file,
    )

    assert result["repairs"] == []
    assert any(
        "Invalid project verification paths" in error
        for error in result["pipeline_errors"]
    )


def test_project_callback_exception_is_retained_as_failed_attempt(
    tmp_path: Path,
    monkeypatch,
    generated_patch,
) -> None:
    source = tmp_path / "app" / "calculator.py"
    source.parent.mkdir()
    source.write_text("def value():\n    return 1\n", encoding="utf-8")

    def fail_verification(*args, **kwargs):
        raise RuntimeError("verification process unavailable")

    monkeypatch.setattr(
        RepairVerificationAdapter,
        "verify_patch",
        fail_verification,
    )

    result = run_pipeline(
        code=source.read_text(encoding="utf-8"),
        file="app/calculator.py",
        client=MockLLMClient(),
        max_attempts=1,
        project_workspace=tmp_path,
    )

    repair = result["repairs"][0]
    assert repair["status"] == "failed"
    error_report = repair["project_verification_reports"][0]
    assert error_report["status"] == "error"
    assert "verification process unavailable" in (
        error_report["checks"]["project_verification"]["error"]
    )


def test_standalone_verifier_mode_remains_compatible(
    tmp_path: Path,
    monkeypatch,
    generated_patch,
) -> None:
    source = tmp_path / "calculator.py"
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    verification_calls = []

    class FakeVerifier:
        def verify(self, patched_code: str, file_path: str) -> VerificationResult:
            verification_calls.append((patched_code, file_path))
            return VerificationResult(passed=True, stage="none")

    result = run_pipeline(
        code=source.read_text(encoding="utf-8"),
        file=str(source),
        client=MockLLMClient(),
        verifier=FakeVerifier(),
    )

    assert result["repairs"][0]["status"] == "verified"
    assert verification_calls == [
        ("def value():\n    return 2\n", str(source))
    ]
    assert "project_verification_reports" not in result["repairs"][0]


def test_default_pipeline_still_constructs_local_verifier(monkeypatch) -> None:
    constructed = []

    class FakeLocalVerifier:
        def __init__(self, test_code=None):
            constructed.append(test_code)

        def verify(self, patched_code, file_path):
            return VerificationResult(passed=True, stage="none")

    monkeypatch.setattr(pipeline_module, "LocalVerifier", FakeLocalVerifier)
    monkeypatch.setattr(pipeline_module, "review", lambda **kwargs: [])

    result = run_pipeline(
        code="value = 1\n",
        file="example.py",
        client=MockLLMClient(),
        test_code="test source",
    )

    assert result["repairs"] == []
    assert constructed == ["test source"]
