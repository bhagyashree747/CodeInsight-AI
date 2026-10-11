import sys

from app.code_engine.diff import parse_patch, FileDiff
from app.code_engine.context_builder import build_context, build_file_context, LEVELS

# New version of the file (after the change). Built line by line so indentation is exact.
SAMPLE_SOURCE = "\n".join([
    "import os",                                  # 1
    "",                                           # 2
    "class Cart:",                                # 3
    "    def total(self, items):",                # 4
    "        total = 0",                          # 5
    "        for item in items:",                 # 6
    "            total += item.price * item.qty", # 7
    "        return total",                       # 8
    "",                                           # 9
    "",                                           # 10
    "def helper():",                              # 11
    "    return 1",                               # 12
])

# The diff that produced it (line 7 changed)
SAMPLE_PATCH = "\n".join([
    "@@ -5,4 +5,4 @@ class Cart:",
    "         total = 0",
    "         for item in items:",
    "-            total += item.price",
    "+            total += item.price * item.qty",
    "         return total",
])


def test_sample():
    print("=== Sample test ===")
    changed_file = {"filename": "cart.py", "status": "modified", "patch": SAMPLE_PATCH}
    diff = FileDiff("cart.py", "modified", parse_patch(SAMPLE_PATCH))

    d = build_file_context(changed_file, diff, SAMPLE_SOURCE, "diff")
    assert d["level"] == "diff"
    print("diff     :", len(d["text"]), "characters")

    f = build_file_context(changed_file, diff, SAMPLE_SOURCE, "function")
    unit = f["units"][0]
    assert unit["function"] == "total" and unit["class"] == "Cart"
    assert (unit["start_line"], unit["end_line"]) == (4, 8)
    print("function :", len(f["text"]), "characters ->", unit["function"], unit["start_line"], "-", unit["end_line"])

    full = build_file_context(changed_file, diff, SAMPLE_SOURCE, "file")
    assert full["units"][0]["start_line"] == 1 and full["units"][0]["end_line"] == 12
    print("file     :", len(full["text"]), "characters")

    fallback = build_file_context(changed_file, diff, None, "function")
    assert fallback["level"] == "diff" and fallback["note"]
    print("fallback : OK (missing file falls back to diff)")

    print("Sample test PASSED\n")
    print("--- function-level text the AI would receive ---")
    print(f["text"])
    print()


def test_real_pr(pr_url, show="function"):
    from app.github.client import GitHubClient
    from app.github.pull_request import fetch_pull_request

    client = GitHubClient()
    pr = fetch_pull_request(client, pr_url)
    print(f"=== {pr['repository']} PR #{pr['pr_number']}: {pr['title']} ===\n")

    shown = None
    for level in LEVELS:
        ctx = build_context(pr, level=level, client=client)
        print(f"{level:9} -> {len(ctx['text']):>7} characters")
        if level == show:
            shown = ctx

    print(f"\n--- {show}-level text ---")
    text = shown["text"]
    print(text if len(text) <= 3000 else text[:3000] + "\n... (cut for display)")


if __name__ == "__main__":
    test_sample()
    if len(sys.argv) > 1:
        level = sys.argv[2] if len(sys.argv) > 2 else "function"
        test_real_pr(sys.argv[1], level)