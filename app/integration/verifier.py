import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass

try:  # Member 1's class (a pydantic model: passed, stage in syntax/lint/tests/none, error, output)
    from app.repair.verifier_interface import VerificationResult
except ImportError:
    @dataclass
    class VerificationResult:
        passed: bool
        stage: str = "none"
        error: str = ""
        output: str = ""


class Workspace:
    """A throw-away copy of the PR's base checkout, with the PR's test files added.
    The original checkout is never touched."""

    def __init__(self, base_folder, test_files):
        self.root = tempfile.mkdtemp(prefix="codeinsight_ws_")
        self.path = os.path.join(self.root, "repo")
        shutil.copytree(base_folder, self.path,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        for rel, text in test_files.items():
            self.write(rel, text)

    def write(self, rel, text):
        full = os.path.join(self.path, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="") as f:
            f.write(text)

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _env(cwd):
    """Make Python import the WORKSPACE's code, not another checkout installed in the env."""
    env = dict(os.environ)
    src = os.path.join(cwd, "src")
    first = src if os.path.isdir(src) else cwd
    env["PYTHONPATH"] = first + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def check_import(python, cwd, import_name="requests"):
    """Returns None if the tests will import the workspace's code, otherwise a message."""
    result = subprocess.run(
        [python, "-c", f"import {import_name}; print({import_name}.__file__)"],
        cwd=cwd, env=_env(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    if result.returncode != 0:
        return f"Cannot import {import_name} in the test environment:\n{result.stderr[-500:]}"
    lines = result.stdout.strip().splitlines()
    path = os.path.normcase(os.path.realpath(lines[-1])) if lines else ""
    root = os.path.normcase(os.path.realpath(cwd))
    if not path.startswith(root):
        return (f"The tests would import {import_name} from {path}, not from the workspace {root}. "
                "Check that --python points to the test environment.")
    return None


def run_pytest(python, cwd, test_ids, timeout=300):
    """Run pytest on the given node ids. Returns (exit code, output, seconds)."""
    cmd = [python, "-m", "pytest", *test_ids, "-q", "--tb=short", "-p", "no:cacheprovider"]
    start = time.time()
    try:
        result = subprocess.run(cmd, cwd=cwd, env=_env(cwd), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
        code, output = result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        code, output = -1, f"TIMEOUT after {timeout}s"
    return code, output, round(time.time() - start, 1)


def _tail(text, n=40):
    return "\n".join(text.splitlines()[-n:])


def _summary(output):
    """A short failure message for the repair loop (failed test names and assertion lines)."""
    keep = [l for l in output.splitlines() if l.startswith(("FAILED ", "ERROR ", "E  "))]
    return "\n".join(keep[:10]) or _tail(output, 8)[-500:]


class FailToPassVerifier:
    """Plugs into Member 1's retry loop: verify(patched_code, file_path) -> VerificationResult.
    Stage 1: syntax check. Stage 2: run the fail-to-pass tests in the temp workspace.
    Result stages follow Member 1's convention: 'syntax' or 'tests' when failing, 'none' when passed."""

    def __init__(self, workspace, python, test_ids, file_path, original_source,
                 window=None, timeout=300, import_name="requests"):
        self.workspace = workspace
        self.python = python
        self.test_ids = test_ids
        self.file_path = file_path
        self.original_text = original_source
        self.original_lines = original_source.splitlines()
        self.ends_with_newline = original_source.endswith("\n")
        self.window = window            # (start_line, end_line) if the AI only saw a window
        self.timeout = timeout
        self.import_name = import_name
        self.setup_checked = False
        self.last = {}

    def _to_full_file(self, patched):
        """The AI may send back the whole file or only the window it was shown.
        Decide by line count, and put a window back into the original file."""
        if not self.window:
            return patched
        lines = patched.splitlines()
        total = len(self.original_lines)
        start, end = self.window
        if abs(len(lines) - total) <= abs(len(lines) - (end - start + 1)):
            return patched                                  # looks like the whole file
        merged = self.original_lines[:start - 1] + lines + self.original_lines[end:]
        return "\n".join(merged) + ("\n" if self.ends_with_newline else "")

    def verify(self, patched_code, file_path=None):
        full = self._to_full_file(patched_code)

        try:
            compile(full, self.file_path, "exec")
        except SyntaxError as error:
            return VerificationResult(passed=False, stage="syntax",
                                      error=f"SyntaxError on line {error.lineno}: {error.msg}", output="")

        if not self.setup_checked:
            problem = check_import(self.python, self.workspace.path, self.import_name)
            if problem:
                return VerificationResult(passed=False, stage="tests",
                                          error=f"SETUP PROBLEM: {problem}", output="")
            self.setup_checked = True

        self.workspace.write(self.file_path, full)
        try:
            code, output, seconds = run_pytest(self.python, self.workspace.path,
                                               self.test_ids, self.timeout)
        finally:
            self.workspace.write(self.file_path, self.original_text)   # always restore

        self.last = {
            "exit_code": code,
            "duration_s": seconds,
            "failed_tests": [l.split(" ")[1] for l in output.splitlines()
                             if l.startswith("FAILED ") and len(l.split(" ")) > 1],
        }
        if code == 0:
            return VerificationResult(passed=True, stage="none", error="", output=_tail(output))
        return VerificationResult(passed=False, stage="tests",
                                  error=_summary(output), output=_tail(output))