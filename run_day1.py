import json
import sys

from app.github.client import GitHubClient
from app.github.pull_request import fetch_pull_request


def main():
    pr_url = sys.argv[1] if len(sys.argv) > 1 else input("Paste a GitHub PR URL: ")

    client = GitHubClient()
    pr = fetch_pull_request(client, pr_url)

    # Shorten the diffs so the printout is readable
    for f in pr["changed_files"]:
        f["patch"] = f["patch"][:200] + ("..." if len(f["patch"]) > 200 else "")

    print(json.dumps(pr, indent=2))
    print(f"\nTotal changed files: {len(pr['changed_files'])}")


if __name__ == "__main__":
    main()