"""Python syntax verification for CodeInsight-AI."""

import ast
import os
from pathlib import Path
import stat


def _make_error(
    file: str,
    message: str,
    line: int | None = None,
    column: int | None = None,
) -> dict:
    return {
        "file": file,
        "line": line,
        "column": column,
        "message": message,
    }


def check_python_syntax(target: str | Path) -> dict:
    """
    Check Python syntax in a single file or recursively in a directory.
    """
    errors = []
    try:
        path = Path(target).expanduser().resolve()
        target_stat = path.stat()
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "passed": False,
            "files_checked": 0,
            "errors": [
                _make_error(
                    str(target),
                    f"Could not access path {target}: {exc}",
                )
            ],
        }

    if stat.S_ISREG(target_stat.st_mode):
        if path.suffix != ".py":
            return {
                "passed": False,
                "files_checked": 0,
                "errors": [
                    _make_error(
                        str(path),
                        f"Expected a Python (.py) file: {path}",
                    )
                ],
            }
        python_files = [path]
    elif stat.S_ISDIR(target_stat.st_mode):
        excluded_dirs = {
            ".git",
            ".hg",
            ".mypy_cache",
            ".nox",
            ".pytest_cache",
            ".ruff_cache",
            ".svn",
            ".tox",
            ".venv",
            "__pycache__",
            "env",
            "node_modules",
            "site-packages",
            "venv",
        }
        python_files = []

        def record_walk_error(exc: OSError) -> None:
            errors.append(
                _make_error(
                    str(exc.filename or path),
                    f"Could not scan directory: {exc}",
                )
            )

        try:
            for root, directories, filenames in os.walk(
                path,
                topdown=True,
                followlinks=False,
                onerror=record_walk_error,
            ):
                directories[:] = [
                    name
                    for name in directories
                    if name not in excluded_dirs
                    and not (Path(root) / name).is_symlink()
                ]
                python_files.extend(
                    Path(root) / name
                    for name in filenames
                    if name.endswith(".py") and not (Path(root) / name).is_symlink()
                )
        except OSError as exc:
            record_walk_error(exc)
    else:
        return {
            "passed": False,
            "files_checked": 0,
            "errors": [
                _make_error(
                    str(path),
                    f"Expected a Python file or directory: {path}",
                )
            ],
        }

    for file in python_files:
        try:
            source = file.read_text(encoding="utf-8-sig")
            ast.parse(source, filename=str(file))

        except SyntaxError as exc:
            errors.append(
                _make_error(str(file), exc.msg, exc.lineno, exc.offset)
            )

        except (OSError, UnicodeError) as exc:
            errors.append(
                _make_error(
                    str(file),
                    f"Could not read file: {exc}",
                )
            )

    return {
        "passed": len(errors) == 0,
        "files_checked": len(python_files),
        "errors": errors,
    }