"""High-level RepairAgent orchestrating code repairs across single or multiple findings."""

from typing import Any
from app.repair.retry import RepairOutcome, repair_with_retries
from app.repair.verifier_interface import Verifier
from app.review.llm_client import LLMClient
from app.review.schema import Finding


class RepairAgent:
    """Agent driving automated code repair with iterative verification."""

    def __init__(
        self,
        verifier: Verifier,
        client: LLMClient | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.verifier = verifier
        self.client = client
        self.max_attempts = max_attempts

    def repair(
        self,
        code: str,
        finding: Finding,
        file_path: str = "snippet.py",
    ) -> RepairOutcome:
        """Repair a single code finding with verification and retry loops.

        Args:
            code: Source code to repair.
            finding: Finding describing the issue.
            file_path: Path of the source code file.

        Returns:
            RepairOutcome with verification status and attempt history.
        """
        return repair_with_retries(
            code=code,
            finding=finding,
            verifier=self.verifier,
            client=self.client,
            max_attempts=self.max_attempts,
            file_path=file_path,
        )

    def repair_all(
        self,
        code: str,
        scored_findings: list[Any],
        file_path: str = "snippet.py",
    ) -> list[RepairOutcome]:
        """Sequentially repair a collection of findings, updating code baseline after each verified fix.

        Args:
            code: Initial source code.
            scored_findings: List of Finding or ScoredFinding instances.
            file_path: Path of the source code file.

        Returns:
            List of RepairOutcome objects corresponding to each finding repaired.
        """
        outcomes: list[RepairOutcome] = []
        current_code = code

        for item in scored_findings:
            finding: Finding = item.finding if hasattr(item, "finding") else item
            outcome = self.repair(
                code=current_code,
                finding=finding,
                file_path=file_path,
            )
            outcomes.append(outcome)
            if outcome.status == "verified" and outcome.final_code:
                current_code = outcome.final_code

        return outcomes
