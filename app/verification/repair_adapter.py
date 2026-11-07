"""Adapter connecting verification tools to the AI repair interface."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.repair.verifier_interface import VerificationResult


class PatchLike(Protocol):
    fixed_code: str


class RepairVerificationAdapter:
    """Compatibility adapter delegating verification to Member 1's LocalVerifier."""

    def __init__(self, test_code: str | None = None) -> None:
        self.test_code = test_code

    def verify(
        self,
        patched_code: str,
        file_path: str = "snippet.py",
    ) -> VerificationResult:
        """Return the actual result model produced by Member 1's LocalVerifier.

        Repair integration is optional at import time, but the repair modules
        must be integrated before this adapter can verify code.
        """
        try:
            from app.repair.local_verifier import LocalVerifier
        except ModuleNotFoundError as exc:
            if exc.name not in {
                "app.repair",
                "app.repair.local_verifier",
                "app.repair.verifier_interface",
            }:
                raise
            raise RuntimeError(
                "Repair verification requires Member 1's "
                "app.repair.verifier_interface and LocalVerifier modules."
            ) from exc

        return LocalVerifier(test_code=self.test_code).verify(
            patched_code=patched_code,
            file_path=file_path,
        )

    def verify_patch(
        self,
        patch: PatchLike,
        original_file: str | Path,
        workspace: str | Path,
        test_timeout: float = 60,
    ) -> dict:
        """Verify a generated patch against the project's full test suite."""
        from app.verification.runner import run_patch_verification

        return run_patch_verification(
            patched_code=patch.fixed_code,
            original_file=original_file,
            workspace=workspace,
            test_timeout=test_timeout,
        )