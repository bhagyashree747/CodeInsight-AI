import sys
from pathlib import Path

from app.verification.test_runner import run_tests


def test_run_tests_supports_node_ids_custom_python_and_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    target = tmp_path / "target"
    tests_dir = workspace / "tests"

    tests_dir.mkdir(parents=True)
    target.mkdir()

    test_file = tests_dir / "test_selection.py"
    test_file.write_text(
        "def test_selected():\n"
        "    assert True\n\n"
        "def test_not_selected():\n"
        "    assert False\n",
        encoding="utf-8",
    )

    result = run_tests(
        target=target,
        timeout=15,
        tests=["tests/test_selection.py::test_selected"],
        python=sys.executable,
        workspace=workspace,
    )

    assert result["passed"] is True, result
    assert "1 passed" in (result["stdout"] + result["stderr"])
