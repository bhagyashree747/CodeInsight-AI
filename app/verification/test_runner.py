"""Automated test execution for CodeInsight-AI."""

from collections import deque
import math
import os
import signal
import subprocess
import sys
from pathlib import Path
import stat
from threading import Lock, Thread
import time

_OUTPUT_LIMIT = 4000
_OUTPUT_BUFFER_BYTES = _OUTPUT_LIMIT * 4
_READ_CHUNK_BYTES = 4096


def run_tests(
    target: str | Path,
    timeout: float = 60,
) -> dict:
    """
    Run pytest for a trusted project target and capture the results.
    Pytest imports and executes project code; this is not a security sandbox.

    Args:
        target: A Python test file or directory containing tests.
        timeout: Maximum execution time in seconds.

    Returns:
        A dictionary containing the test status, exit code,
        captured output, and error details.
    """
    try:
        path = Path(target).expanduser().resolve()
        target_stat = path.stat()
    except (OSError, RuntimeError) as exc:
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Could not access target {target}: {exc}",
            "duration_seconds": None,
        }

    if not (stat.S_ISREG(target_stat.st_mode) or stat.S_ISDIR(target_stat.st_mode)):
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Target must be a file or directory: {path}",
            "duration_seconds": None,
        }

    if path.is_file() and path.suffix != ".py":
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Expected a Python test file: {path}",
            "duration_seconds": None,
        }

    valid_timeout = not isinstance(timeout, bool) and isinstance(
        timeout, (int, float)
    )
    timeout_value = 0.0
    if valid_timeout:
        try:
            timeout_value = float(timeout)
        except OverflowError:
            valid_timeout = False
        else:
            valid_timeout = math.isfinite(timeout_value) and timeout_value > 0
    if not valid_timeout:
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": "Timeout must be greater than zero.",
            "duration_seconds": None,
        }

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        str(path),
    ]

    try:
        start_time = time.monotonic()
        process_options = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        process = subprocess.Popen(
            command,
            cwd=str(path if os.path.isdir(path) else path.parent),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=os.environ.copy(),
            **process_options,
        )
        output: dict[str, deque[bytes]] = {
            "stdout": deque(),
            "stderr": deque(),
        }
        output_lock = Lock()
        capture_errors: dict[str, str] = {}
        assert process.stdout is not None
        assert process.stderr is not None
        readers = [
            Thread(
                target=_drain_pipe,
                args=(
                    process.stdout,
                    output["stdout"],
                    output_lock,
                    capture_errors,
                    "stdout",
                ),
                daemon=True,
            ),
            Thread(
                target=_drain_pipe,
                args=(
                    process.stderr,
                    output["stderr"],
                    output_lock,
                    capture_errors,
                    "stderr",
                ),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()

        timed_out = False
        try:
            return_code = process.wait(timeout=timeout_value)
        except subprocess.TimeoutExpired:
            timed_out = True
            cleanup_errors = _terminate_process_tree(process)
            return_code = process.wait()
        finally:
            readers_deadline = time.monotonic() + 5
            for reader in readers:
                reader.join(timeout=max(0, readers_deadline - time.monotonic()))

        duration = round(time.monotonic() - start_time, 3)
        with output_lock:
            stdout = _captured_output(output["stdout"])
            stderr = _captured_output(output["stderr"])
        for name, reader in zip(("stdout", "stderr"), readers):
            if reader.is_alive():
                capture_errors[name] = (
                    f"Could not finish draining pytest {name} after process cleanup."
                )

        if timed_out:
            return {
                "passed": False,
                "status": "timeout",
                "exit_code": None,
                "stdout": stdout,
                "stderr": stderr,
                "error": "; ".join(
                    [f"Tests exceeded the {timeout}-second timeout."]
                    + cleanup_errors
                    + list(capture_errors.values())
                ),
                "duration_seconds": duration,
            }

        if capture_errors:
            status = "error"
        elif return_code == 0:
            status = "passed"
        elif return_code == 1 and "no module named pytest" not in stderr.lower():
            status = "failed"
        else:
            status = "error"

        return {
            "passed": return_code == 0 and not capture_errors,
            "status": status,
            "exit_code": return_code,
            "stdout": stdout,
            "stderr": stderr,
            "error": (
                None
                if status in {"passed", "failed"}
                else (
                    "; ".join(capture_errors.values())
                    if capture_errors
                    else f"Pytest could not complete successfully (exit code {return_code})."
                )
            ),
            "duration_seconds": duration,
        }

    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "passed": False,
            "status": "error",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "error": f"Could not start pytest: {exc}",
            "duration_seconds": None,
        }


def _drain_pipe(
    stream,
    chunks: deque[bytes],
    output_lock: Lock,
    capture_errors: dict[str, str],
    name: str,
) -> None:
    size = 0
    try:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            with output_lock:
                chunks.append(chunk)
                size += len(chunk)
                while size > _OUTPUT_BUFFER_BYTES:
                    excess = size - _OUTPUT_BUFFER_BYTES
                    first = chunks.popleft()
                    if len(first) > excess:
                        chunks.appendleft(first[excess:])
                        size -= excess
                    else:
                        size -= len(first)
    except OSError as exc:
        capture_errors[name] = f"Could not capture pytest {name}: {exc}"
    finally:
        stream.close()


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> list[str]:
    errors = []
    if os.name == "nt":
        try:
            terminated = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
                shell=False,
            )
            if terminated.returncode != 0 and process.poll() is None:
                errors.append("Windows taskkill could not terminate the process tree.")
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"Could not terminate the Windows process tree: {exc}")

        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            errors.append(f"Could not terminate the pytest process group: {exc}")
            if process.poll() is None:
                process.terminate()

        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass

        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            errors.append(f"Could not kill the pytest process group: {exc}")
            if process.poll() is None:
                process.kill()

    return errors


def _captured_output(chunks: deque[bytes]) -> str:
    output = b"".join(chunks).decode("utf-8", errors="replace")
    limit = _OUTPUT_LIMIT
    if len(output) <= limit:
        return output
    marker = "[...output truncated...]\n"
    return f"{marker}{output[-(limit - len(marker)):]}"