"""Main entry point for CodeInsight-AI verification."""

import json
import sys
from pathlib import Path

try:
    from .syntax import check_python_syntax
except ImportError:
    from syntax import check_python_syntax


def run_verification(target: str | Path) -> dict:
    """
    Run the currently implemented verification checks.

    Version 1 checks Python syntax only. Linting and automated test
    execution will be added as separate checks.
    """
    syntax_result = check_python_syntax(target)

    return {
        "status": "passed" if syntax_result["passed"] else "failed",
        "target": str(Path(target).resolve()),
        "checks": {
            "syntax": syntax_result,
        },
    }


def main() -> int:
    """Run verification from the command line."""
    target = sys.argv[1] if len(sys.argv) > 1 else "."

    result = run_verification(target)
    print(json.dumps(result, indent=2))

    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())