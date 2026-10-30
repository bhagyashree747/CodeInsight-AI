import os
import subprocess

WORKSPACE = "workspace"


def _git(args, cwd):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def checkout_pr_base(pr, workspace=WORKSPACE):
    """Clone the repo at the PR's BASE commit (the code BEFORE the change).
    Input : the dict from fetch_pull_request()
    Output: the folder path. If the folder already exists, it is reused.
    If a clone fails halfway, delete that folder and run again."""
    owner, repo = pr["repository"].split("/")
    folder = os.path.abspath(
        os.path.join(workspace, f"{owner}__{repo}__pr{pr['pr_number']}")
    )
    if os.path.isdir(os.path.join(folder, ".git")):
        return folder

    os.makedirs(folder, exist_ok=True)
    _git(["init"], folder)
    _git(["remote", "add", "origin", f"https://github.com/{owner}/{repo}.git"], folder)
    _git(["fetch", "--depth", "1", "origin", pr["base_sha"]], folder)
    _git(["checkout", "--detach", "FETCH_HEAD"], folder)
    return folder