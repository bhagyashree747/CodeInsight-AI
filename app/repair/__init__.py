"""Repair module for CodeInsight AI."""

from app.repair.agent import RepairAgent
from app.repair.local_verifier import LocalVerifier
from app.repair.patch_generator import (
    PatchGenerationError,
    apply_patch,
    generate_patch,
)
from app.repair.prompts import REPAIR_SYSTEM_PROMPT, build_repair_prompt
from app.repair.retry import RepairAttempt, RepairOutcome, repair_with_retries
from app.repair.schema import ApplyResult, Patch
from app.repair.verifier_interface import VerificationResult, Verifier

__all__ = [
    "ApplyResult",
    "LocalVerifier",
    "Patch",
    "PatchGenerationError",
    "REPAIR_SYSTEM_PROMPT",
    "RepairAgent",
    "RepairAttempt",
    "RepairOutcome",
    "VerificationResult",
    "Verifier",
    "apply_patch",
    "build_repair_prompt",
    "generate_patch",
    "repair_with_retries",
]
