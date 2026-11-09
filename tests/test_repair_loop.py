"""Tests for the repair loop, retry orchestration, and verifiers."""

import json
import pytest

from app.repair.agent import RepairAgent
from app.repair.local_verifier import LocalVerifier
from app.repair.retry import repair_with_retries
from app.repair.verifier_interface import VerificationResult
from app.review.llm_client import LLMClient, MockLLMClient
from app.review.schema import Finding


class TrackingFakeLLMClient(LLMClient):
    """Client tracking prompts and returning configurable canned responses."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.call_count = 0
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.call_count += 1
        self.calls.append((system, user))
        if self.responses:
            return self.responses.pop(0)
        return json.dumps({"fixed_code": "# Default\n", "explanation": "Default"})


SQL_SNIPPET = '''def fetch_user_record(cursor, username: str):
    # Query constructed via direct string interpolation (vulnerable to SQLi)
    query = f"SELECT * FROM users WHERE username = '{username}'"
    cursor.execute(query)
    return cursor.fetchone()
'''

DIV_ZERO_SNIPPET = '''def compute_average_latency(measurements: list[float]) -> float:
    # Unchecked division by collection length
    total = sum(measurements)
    return total / len(measurements)
'''


def make_finding(file: str = "snippet.py", line: int = 1, desc: str = "Bug") -> Finding:
    return Finding(
        file=file,
        line=line,
        category="bug",  # type: ignore[arg-type]
        severity="high",  # type: ignore[arg-type]
        confidence=0.9,
        description=desc,
        suggested_fix_hint="Fix it",
        actionable=True,
    )


# --- 1. Good patch verifies on attempt 1 ---

def test_good_patch_verifies_on_attempt_1():
    finding = make_finding(file="app/db/users.py", line=3, desc="SQL injection")
    verifier = LocalVerifier()
    # MockLLMClient returns valid parameterized SQL for SQL_SNIPPET on attempt 1
    outcome = repair_with_retries(SQL_SNIPPET, finding, verifier=verifier)

    assert outcome.status == "verified"
    assert outcome.total_attempts == 1
    assert len(outcome.attempts) == 1
    assert outcome.attempts[0].verification is not None
    assert outcome.attempts[0].verification.passed is True
    assert outcome.final_patch is not None
    assert "%s" in outcome.final_code


# --- 2. Broken first patch is fixed on attempt 2 ---

def test_broken_first_patch_fixed_on_attempt_2():
    finding = make_finding(file="app/metrics/latency.py", line=4, desc="Zero division")
    verifier = LocalVerifier()
    # MockLLMClient returns a syntax error on attempt 1, and correct code on attempt 2
    outcome = repair_with_retries(DIV_ZERO_SNIPPET, finding, verifier=verifier)

    assert outcome.status == "verified"
    assert outcome.total_attempts == 2
    assert len(outcome.attempts) == 2

    # Attempt 1 failed at syntax stage
    assert outcome.attempts[0].verification.passed is False
    assert outcome.attempts[0].verification.stage == "syntax"

    # Attempt 2 passed
    assert outcome.attempts[1].verification.passed is True
    assert outcome.attempts[1].verification.stage == "none"
    assert "if not measurements:" in outcome.final_code


# --- 3. Patch that never passes ends "failed" after max_attempts ---

def test_patch_that_never_passes_ends_failed_after_max_attempts():
    finding = make_finding(file="test.py", line=1)

    # Verifier that always rejects code
    class AlwaysFailingVerifier:
        def verify(self, patched_code: str, file_path: str) -> VerificationResult:
            return VerificationResult(
                passed=False,
                stage="tests",
                error="Tests failed",
                output="AssertionError: condition unmet",
            )

    verifier = AlwaysFailingVerifier()
    outcome = repair_with_retries(
        SQL_SNIPPET,
        finding,
        verifier=verifier,
        max_attempts=3,
    )

    assert outcome.status == "failed"
    assert outcome.total_attempts == 3
    assert len(outcome.attempts) == 3
    for att in outcome.attempts:
        assert att.verification.passed is False


# --- 4. LocalVerifier catches syntax errors ---

def test_local_verifier_catches_syntax_errors():
    verifier = LocalVerifier()
    broken_code = "def bad_syntax(x\n    return x + 1\n"
    res = verifier.verify(broken_code, "test.py")

    assert res.passed is False
    assert res.stage == "syntax"
    assert "SyntaxError" in res.error
    assert "line 1" in res.error


# --- 5. Failure message really appears in the second repair prompt ---

def test_failure_message_really_appears_in_second_repair_prompt():
    finding = make_finding(file="calc.py", line=1)
    broken_resp = json.dumps({
        "fixed_code": "def bad(x\n    return x",
        "explanation": "Broken syntax",
    })
    fixed_resp = json.dumps({
        "fixed_code": "def good(x):\n    return x\n",
        "explanation": "Fixed syntax",
    })

    client = TrackingFakeLLMClient([broken_resp, fixed_resp])
    verifier = LocalVerifier()

    outcome = repair_with_retries(
        code="def bad(x):\n    pass\n",
        finding=finding,
        verifier=verifier,
        client=client,
        max_attempts=2,
    )

    assert outcome.status == "verified"
    assert client.call_count == 2

    # Second repair call prompt must contain the feedback
    second_user_prompt = client.calls[1][1]
    assert "Your last fix failed, correct it." in second_user_prompt
    assert "SyntaxError" in second_user_prompt


# --- 6. RepairAgent single and repair_all ---

def test_repair_agent_repair_all():
    f1 = make_finding(file="app/db/users.py", line=3, desc="SQL injection")
    agent = RepairAgent(verifier=LocalVerifier(), max_attempts=2)
    outcomes = agent.repair_all(SQL_SNIPPET, [f1])

    assert len(outcomes) == 1
    assert outcomes[0].status == "verified"
