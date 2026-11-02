import argparse
import os
import re
import subprocess
import sys

from app.github.client import GitHubClient
from app.github.pull_request import fetch_pull_request
from app.github.checkout import checkout_pr_base, _git


def is_test_file(path):
    return path.endswith(".py") and "test" in path.lower()


def run_pytest(python, folder, test_files):
    """Run pytest on the given files. Returns (exit code, set of failing test ids, output)."""
    cmd = [python, "-m", "pytest", *test_files, "-q", "--tb=no", "-rfE", "-p", "no:cacheprovider"]
    result = subprocess.run(cmd, cwd=folder, capture_output=True, text=True)
    output = result.stdout + result.stderr
    failed = set()
    for line in output.splitlines():
        match = re.match(r"^(FAILED|ERROR) (\S+)", line)
        if match:
            failed.add(match.group(2))
    return result.returncode, failed, output


def tail(text, n=15):
    return "\n".join(text.splitlines()[-n:])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pr_url")
    parser.add_argument("--python", default=sys.executable,
                        help="python.exe of an environment that has pytest + the repo's dependencies")
    args = parser.parse_args()

    pr = fetch_pull_request(GitHubClient(), args.pr_url)
    print(f"PR #{pr['pr_number']}: {pr['title']}")

    tests = [f["filename"] for f in pr["changed_files"]
             if is_test_file(f["filename"]) and f["status"] != "removed"]
    fixes = [f for f in pr["changed_files"] if not is_test_file(f["filename"])]
    if not tests:
        print("RESULT: no test files changed -> cannot prove fail-to-pass.")
        return
    if not fixes:
        print("RESULT: only test files changed -> there is no fix to verify.")
        return

    folder = checkout_pr_base(pr)
    assert os.path.isdir(os.path.join(folder, ".git")), "clone folder is missing its .git"

    # make the test environment use THIS clone's code (editable install, no dependencies)
    install = subprocess.run(
        [args.python, "-m", "pip", "install", "-e", ".", "--no-deps", "-q"],
        cwd=folder, capture_output=True, text=True)
    if install.returncode != 0:
        print("Could not install this PR's code into the environment:\n" + tail(install.stderr))
        return

    # start from a clean base commit, and get the PR's final code
    _git(["fetch", "--depth", "1", "origin", f"pull/{pr['pr_number']}/head"], folder)
    _git(["reset", "--hard", pr["base_sha"]], folder)
    _git(["clean", "-fdq"], folder)

    # BEFORE: base code + the PR's tests
    _git(["checkout", "FETCH_HEAD", "--", *tests], folder)
    code_a, failed_a, out_a = run_pytest(args.python, folder, tests)
    print(f"\nBEFORE the fix: pytest exit code {code_a}, {len(failed_a)} failing")

    # AFTER: base code + the PR's tests + the PR's fix
    for f in fixes:
        if f["status"] == "removed":
            _git(["rm", "-q", "-f", "--ignore-unmatch", f["filename"]], folder)
        else:
            _git(["checkout", "FETCH_HEAD", "--", f["filename"]], folder)
    code_b, failed_b, out_b = run_pytest(args.python, folder, tests)
    print(f"AFTER the fix : pytest exit code {code_b}, {len(failed_b)} failing")

    fail_to_pass = sorted(failed_a - failed_b)
    regressions = sorted(failed_b - failed_a)

    print()
    if code_a in (4, 5) or code_b in (4, 5):
        print("RESULT: could not run the tests (usage error or no tests collected).")
        print("Check the python path / environment. Last output:\n" + tail(out_a))
    elif fail_to_pass:
        print(f"RESULT: GOOD, {len(fail_to_pass)} test(s) fail before the fix and pass after:")
        for name in fail_to_pass[:10]:
            print("   ", name)
    else:
        print("RESULT: NOT PROVEN, no test went from failing to passing.")
        print("(Tests may already pass without the fix, or the environment is not set up.)")
        print("Last output of the BEFORE run:\n" + tail(out_a))

    if regressions:
        print("WARNING: these tests fail only AFTER the fix:", regressions[:5])


if __name__ == "__main__":
    main()