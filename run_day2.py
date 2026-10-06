import sys

from app.code_engine.diff import parse_patch, FileDiff, build_file_diffs

# Built line by line so the leading diff-space on context lines is exact
SAMPLE_PATCH = "\n".join([
    "@@ -10,4 +10,5 @@ def calculate_total(items):",
    "     total = 0",
    "     for item in items:",
    "-        total += item.price",
    "+        total += item.price * item.qty",
    "+        # include quantity",
    "     return total",
])


def test_sample():
    diff = FileDiff("sample.py", "modified", parse_patch(SAMPLE_PATCH))
    print("=== Sample test ===")
    print("added_lines       :", diff.added_lines)          # expect [12, 13]
    print("removed_lines     :", diff.removed_lines)        # expect [12]
    print("changed_new_lines :", diff.changed_new_lines)    # expect [12, 13]
    assert diff.added_lines == [12, 13]
    assert diff.removed_lines == [12]
    print("Sample test PASSED\n")


def test_real_pr(pr_url):
    from app.github.client import GitHubClient
    from app.github.pull_request import fetch_pull_request

    pr = fetch_pull_request(GitHubClient(), pr_url)
    diffs = build_file_diffs(pr["changed_files"])
    print(f"=== {pr['repository']} PR #{pr['pr_number']} ===")
    for d in diffs:
        print(f"\n{d.filename} ({d.status})")
        print("  added   :", d.added_lines)
        print("  removed :", d.removed_lines)
        print("  changed :", d.changed_new_lines)


if __name__ == "__main__":
    test_sample()
    if len(sys.argv) > 1:
        test_real_pr(sys.argv[1])