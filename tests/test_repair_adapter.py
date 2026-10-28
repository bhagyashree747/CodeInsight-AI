"""Tests for the repair verification adapter."""

import sys
from pathlib import Path

import pytest

from app.verification.repair_adapter import RepairVerificationAdapter


@pytest.fixture
def repair_interface_stub(monkeypatch):
    """Provide Member 1's result model without merging their branch."""
    from pydantic import BaseModel

    class VerificationResult(BaseModel):
        passed: bool
        stage: str = "none"
        error: str = ""
        output: str = ""

    class FakeVerifierInterface:
        pass

    FakeVerifierInterface.VerificationResult = VerificationResult

    monkeypatch.setitem(
        sys.modules,
        "app.repair.verifier_interface",
        FakeVerifierInterface,
    )

    return VerificationResult


def test_valid_python_passes_without_tests(repair_interface_stub):
    adapter = RepairVerificationAdapter()

    result = adapter.verify(
        "def add(a, b):\n    return a + b\n",
        "snippet.py",
    )

    assert result.passed is True
    assert result.stage == "none"
    assert "Syntax verification passed" in result.output
    assert "not requested" in result.output


def test_invalid_python_fails_syntax(repair_interface_stub):
    adapter = RepairVerificationAdapter()

    result = adapter.verify(
        "def add(a, b)\n    return a + b\n",
        "snippet.py",
    )

    assert result.passed is False
    assert result.stage == "syntax"
    assert result.error


def test_valid_python_and_tests_pass(repair_interface_stub):
    adapter = RepairVerificationAdapter(
        test_code=(
            "from snippet import add\n"
            "\n"
            "def test_add():\n"
            "    assert add(2, 3) == 5\n"
        )
    )

    result = adapter.verify(
        "def add(a, b):\n    return a + b\n",
        "snippet.py",
    )

    assert result.passed is True
    assert result.stage == "none"
    assert "Automated tests passed" in result.output


def test_failing_tests_return_failure(repair_interface_stub):
    adapter = RepairVerificationAdapter(
        test_code=(
            "from snippet import add\n"
            "\n"
            "def test_add():\n"
            "    assert add(2, 3) == 99\n"
        )
    )

    result = adapter.verify(
        "def add(a, b):\n    return a + b\n",
        "snippet.py",
    )

    assert result.passed is False
    assert result.stage == "tests"
    assert "failed" in result.error.lower()


def test_nonpositive_timeout_is_rejected():
    with pytest.raises(ValueError):
        RepairVerificationAdapter(test_timeout=0)