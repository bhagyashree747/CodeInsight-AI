import re
import sys

from app.github.client import GitHubClient

REPO = "psf/requests"
DEFAULT_PATHS = [
    "src/requests/utils.py",
    "src/requests/models.py",
    "src/requests/structures.py",
]
FIX_WORDS = re.compile(
    r"\b(fix|fixes|fixed|handle|preserve|correct|avoid|prevent|validate|respect)\b", re.I
)
SKIP_START = ("bump", "update", "merge branch", "release", "v2.")


def pr_number(title):
    match = re.search(r"\(#(\d+)\)", title) or re.search(r"Merge pull request #(\d+)", title)
    return int(match.group(1)) if match else None


def known_prs():
    """PR numbers already in docs/eval_prs.txt (including dropped ones)."""
    try:
        with open("docs/eval_prs.txt", encoding="utf-8") as f:
            return {int(n) for n in re.findall(r"/pull/(\d+)", f.read())}
    except FileNotFoundError:
        return set()


def main():
    paths = sys.argv[1:] or DEFAULT_PATHS
    client = GitHubClient()
    known = known_prs()
    found = {}

    for path in paths:
        commits = client.get(f"/repos/{REPO}/commits", params={"path": path, "per_page": 40})
        print(f"\n== {path} ==   (* = looks like a bug fix)")
        shown = 0
        for c in commits:
            title = c["commit"]["message"].splitlines()[0]
            number = pr_number(title)
            if number is None or number in known or number in found:
                continue
            if title.lower().startswith(SKIP_START):
                continue
            mark = "*" if FIX_WORDS.search(title) else " "
            print(f" {mark} #{number}: {title}")
            found[number] = (title, bool(FIX_WORDS.search(title)))
            shown += 1
            if shown >= 10:
                break

    urls = [f"https://github.com/{REPO}/pull/{n}" for n, (_, fix) in found.items() if fix]
    if urls:
        with open("candidates_new.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(urls) + "\n")
        print(f"\nWrote {len(urls)} fix-like PRs to candidates_new.txt")
    else:
        print("\nNo fix-like PRs found. Try other file paths.")


if __name__ == "__main__":
    main()