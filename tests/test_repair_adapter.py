"""Contract tests for the optional repair-verifier integration."""

import importlib
import sys
from types import ModuleType, SimpleNamespace
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field
import pytest

import app.verification.runner as runner_module
from app.verification.repair_adapter import RepairVerificationAdapter


class ContractVerificationResult(BaseModel):
    """Test model matching app.repair.verifier_interface.VerificationResult."""

    passed: bool = Field(...)
    stage: Literal["syntax", "lint", "tests", "none"] = "none"
    error: str = ""
    output: str = ""


@runtime_checkable
class ContractVerifier(Protocol):
    def verify(
        self,
        patched_code: str,
        file_path: str,
    ) -> ContractVerificationResult: ...


@pytest.fixture
def install_local_verifier(monkeypatch):
    """Install a test double that follows the real repair-interface contract."""
    repair_package = ModuleType("app.repair")
    repair_package.__path__ = []
    verifier_module = ModuleType("app.repair.local_verifier")
    calls = []

    class LocalVerifier:
        def __init__(self, test_code: str | None = None) -> None:
            self.test_code = test_code

        def verify(
            self,
            patched_code: str,
            file_path: str = "snippet.py",
        ) -> ContractVerificationResult:
            calls.append((self.test_code, patched_code, file_path))
            if patched_code == "bad":
                return ContractVerificationResult(
                    passed=False,
                    stage="syntax",
                    error="SyntaxError",
                    output="invalid source",
                )
            return ContractVerificationResult(
                passed=True,
                stage="none",
                output="All verification checks passed successfully.",
            )

    verifier_module.LocalVerifier = LocalVerifier
    monkeypatch.setitem(sys.modules, "app.repair", repair_package)
    monkeypatch.setitem(sys.modules, "app.repair.local_verifier", verifier_module)
    return calls


def test_adapter_implements_repair_verifier_call_contract(
    install_local_verifier,
) -> None:
    adapter = RepairVerificationAdapter(test_code="test source")

    assert isinstance(adapter, ContractVerifier)

    result = adapter.verify(
        patched_code="patched source",
        file_path="src/example.py",
    )

    assert isinstance(result, ContractVerificationResult)
    assert result.passed is True
    assert install_local_verifier == [
        ("test source", "patched source", "src/example.py")
    ]


def test_adapter_returns_verification_failures_unchanged(
    install_local_verifier,
) -> None:
    result = RepairVerificationAdapter().verify(patched_code="bad")

    assert isinstance(result, ContractVerificationResult)
    assert result.passed is False
    assert result.stage == "syntax"
    assert result.error == "SyntaxError"
    assert result.output == "invalid source"


def test_verify_patch_forwards_patch_and_returns_complete_result_unchanged(
    monkeypatch,
) -> None:
    patch = SimpleNamespace(fixed_code="patched project source")
    report = {
        "status": "failed",
        "baseline_tests": {"status": "passed", "passed": True},
        "comparison": {
            "baseline_status": "passed",
            "patched_status": "failed",
            "assessment": "baseline_passed_patched_failed",
        },
    }
    calls = []

    def fake_run_patch_verification(**kwargs):
        calls.append(kwargs)
        return report

    monkeypatch.setattr(
        runner_module,
        "run_patch_verification",
        fake_run_patch_verification,
    )

    result = RepairVerificationAdapter().verify_patch(
        patch,
        original_file="app/example.py",
        workspace="/project",
        test_timeout=12,
    )

    assert result is report
    assert calls == [
        {
            "patched_code": patch.fixed_code,
            "original_file": "app/example.py",
            "workspace": "/project",
            "test_timeout": 12,
        }
    ]


def test_verify_patch_uses_default_timeout(monkeypatch) -> None:
    calls = []

    def fake_run_patch_verification(**kwargs):
        calls.append(kwargs)
        return {"status": "passed"}

    monkeypatch.setattr(
        runner_module,
        "run_patch_verification",
        fake_run_patch_verification,
    )

    result = RepairVerificationAdapter().verify_patch(
        SimpleNamespace(fixed_code="patched source"),
        original_file="app/example.py",
        workspace="/project",
    )

    assert result == {"status": "passed"}
    assert calls[0]["test_timeout"] == 60


def test_missing_optional_repair_modules_raise_actionable_error(
    monkeypatch,
) -> None:
    original_import = __import__

    def missing_optional_module(name, *args, **kwargs):
        if name == "app.repair.local_verifier":
            raise ModuleNotFoundError(
                "No module named 'app.repair.local_verifier'",
                name="app.repair.local_verifier",
            )
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", missing_optional_module)

    with pytest.raises(RuntimeError, match="requires Member 1's"):
        RepairVerificationAdapter().verify(patched_code="source")


def test_unrelated_import_errors_are_not_hidden(
    monkeypatch,
) -> None:
    def raise_dependency_error(name, *args, **kwargs):
        if name == "app.repair.local_verifier":
            raise ModuleNotFoundError(
                "No module named 'unrelated_dependency'",
                name="unrelated_dependency",
            )
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", raise_dependency_error)

    with pytest.raises(ModuleNotFoundError, match="unrelated_dependency"):
        RepairVerificationAdapter().verify(patched_code="source")


def test_real_local_verifier_integration_when_available() -> None:
    """Run against Member 1's implementation when it is in this checkout."""
    try:
        interface = importlib.import_module("app.repair.verifier_interface")
        importlib.import_module("app.repair.local_verifier")
    except ModuleNotFoundError as exc:
        if exc.name in {
            "app.repair",
            "app.repair.local_verifier",
            "app.repair.verifier_interface",
        }:
            pytest.skip("Member 1's repair modules are not integrated in this checkout.")
        raise

    from app.repair.verifier_interface import Verifier

    adapter = RepairVerificationAdapter(
        test_code=(
            "from snippet import add\n\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
        )
    )
    result = adapter.verify(
        patched_code="def add(a, b):\n    return a + b\n",
        file_path="snippet.py",
    )

    assert isinstance(adapter, Verifier)
    assert isinstance(result, interface.VerificationResult)
    assert result.passed is True
    assert result.stage == "none"
