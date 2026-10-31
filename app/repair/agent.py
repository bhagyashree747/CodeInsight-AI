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
        functions: list[Any] | None = None,
    ) -> None:
        self.verifier = verifier
        self.client = client
        self.max_attempts = max_attempts
        self.functions = functions

    def repair(
        self,
        code: str,
        finding: Finding,
        file_path: str = "snippet.py",
        function_info: dict[str, Any] | Any | None = None,
    ) -> RepairOutcome:
        """Repair a single code finding with verification and retry loops.

        Args:
            code: Source code to repair.
            finding: Finding describing the issue.
            file_path: Path of the source code file.
            function_info: Optional function dict or object if repairing at function-level.

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
            function_info=function_info,
        )

    def repair_all(
        self,
        code: str,
        scored_findings: list[Any],
        file_path: str = "snippet.py",
        functions: list[Any] | None = None,
    ) -> list[RepairOutcome]:
        """Sequentially repair a collection of findings, updating code baseline after each verified fix.

        Args:
            code: Initial source code.
            scored_findings: List of Finding or ScoredFinding instances.
            file_path: Path of the source code file.
            functions: Optional list of function dicts or objects for function-level repair.

        Returns:
            List of RepairOutcome objects corresponding to each finding repaired.
        """
        funcs = functions if functions is not None else self.functions
        working_funcs = None
        if funcs:
            working_funcs = [
                dict(f) if isinstance(f, dict) else {
                    "name": getattr(f, "name", ""),
                    "start_line": getattr(f, "start_line", 1),
                    "end_line": getattr(f, "end_line", 1),
                    "text": getattr(f, "text", ""),
                    "too_large": getattr(f, "too_large", False),
                }
                for f in funcs
            ]

        outcomes: list[RepairOutcome] = []
        current_code = code

        for item in scored_findings:
            finding: Finding = item.finding if hasattr(item, "finding") else item
            func_info = None
            if working_funcs:
                for f in working_funcs:
                    if f["start_line"] <= finding.line <= f["end_line"]:
                        func_info = f
                        break

            prev_len = len(current_code.splitlines())
            outcome = self.repair(
                code=current_code,
                finding=finding,
                file_path=file_path,
                function_info=func_info,
            )
            outcomes.append(outcome)
            if outcome.status == "verified" and outcome.final_code:
                current_code = outcome.final_code
                new_len = len(current_code.splitlines())
                delta = new_len - prev_len
                if delta != 0 and func_info and working_funcs:
                    for f in working_funcs:
                        if f["start_line"] > func_info["end_line"]:
                            f["start_line"] += delta
                            f["end_line"] += delta
                    func_info["end_line"] += delta

        return outcomes
