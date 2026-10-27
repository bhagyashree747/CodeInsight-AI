"""Python syntax verification for CodeInsight-AI."""

import ast
from pathlib import Path


def check_python_syntax(target: str | Path) -> dict:
    """
    Check Python syntax in a single file or recursively in a directory.
    """
    path = Path(target).resolve()

    if not path.exists():
        return {
            "passed": False,
            "files_checked": 0,
            "errors": [f"Path does not exist: {path}"],
        }

    if path.is_file():
        if path.suffix != ".py":
            return {
                "passed": False,
                "files_checked": 0,
                "errors": [f"Expected a Python (.py) file: {path}"],
            }
        python_files = [path]
    else:
        excluded_dirs = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "site-packages",
        }

        python_files = [
            file
            for file in path.rglob("*.py")
            if not any(part in excluded_dirs for part in file.parts)
        ]

    errors = []

    for file in python_files:
        try:
            # utf-8-sig handles files with or without a UTF-8 BOM.
            source = file.read_text(encoding="utf-8-sig")
            ast.parse(source, filename=str(file))

        except SyntaxError as exc:
            errors.append({
                "file": str(file),
                "line": exc.lineno,
                "column": exc.offset,
                "message": exc.msg,
            })

        except (OSError, UnicodeError) as exc:
            errors.append({
                "file": str(file),
                "line": None,
                "column": None,
                "message": f"Could not read file: {exc}",
            })

    return {
        "passed": len(errors) == 0,
        "files_checked": len(python_files),
        "errors": errors,
    }