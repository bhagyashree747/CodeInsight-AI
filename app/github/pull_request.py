from app.github.repository import parse_pr_url, get_repository_info


def fetch_pull_request(client, pr_url):
    """
    Input : GitHub PR URL
    Output: dict with repository, pr_number, changed_files, etc.
    """
    ref = parse_pr_url(pr_url)

    repo_info = get_repository_info(client, ref.owner, ref.repo)
    pr = client.get(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}")
    files = client.get_paginated(
        f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/files"
    )

    changed_files = [
        {
            "filename": f["filename"],
            "status": f["status"],          # added / modified / removed / renamed
            "additions": f["additions"],
            "deletions": f["deletions"],
            "patch": f.get("patch", ""),    # the diff text (used on Day 2)
        }
        for f in files
    ]

    return {
        "repository": ref.full_name,
        "language": repo_info["language"],
        "pr_number": ref.number,
        "title": pr["title"],
        "state": pr["state"],
        "base_sha": pr["base"]["sha"],      # code before the PR
        "head_sha": pr["head"]["sha"],      # code after the PR (needed for Day 3-4)
        "changed_files": changed_files,
    }


def fetch_file_at_head(client, pr, filename):
    """Get the NEW version of a file (after the PR). Returns None if unavailable."""
    owner, repo = pr["repository"].split("/")
    for ref in (pr["head_sha"], f"refs/pull/{pr['pr_number']}/head"):
        text = client.get_file_text(owner, repo, filename, ref)
        if text is not None:
            return text
    return None