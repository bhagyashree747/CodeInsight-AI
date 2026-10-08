import sys

from app.code_engine.tree_context import get_change_contexts

# Built line by line so the indentation is exact
SAMPLE_SOURCE = "\n".join([
    "import os",                          # 1
    "",                                   # 2
    "class Cart:",                        # 3
    "    def total(self, items):",        # 4
    "        total = 0",                  # 5
    "        for item in items:",         # 6
    "            total += item.price",    # 7
    "        return total",               # 8
    "",                                   # 9
    "",                                   # 10
    "def helper():",                      # 11
    "    return 1",                       # 12
])


def test_sample():
    print("=== Sample test ===")
    results = get_change_contexts(SAMPLE_SOURCE, [1, 7, 12])
    for r in results:
        func = r["function"]["name"] if r["function"] else None
        cls = r["class"]["name"] if r["class"] else None
        print(f"lines {r['changed_lines']} -> function={func}, class={cls}")

    by_lines = {tuple(r["changed_lines"]): r for r in results}
    assert by_lines[(1,)]["function"] is None                  # module level
    assert by_lines[(7,)]["function"]["name"] == "total"
    assert by_lines[(7,)]["class"]["name"] == "Cart"
    assert by_lines[(12,)]["function"]["name"] == "helper"
    assert by_lines[(12,)]["class"] is None
    print("Sample test PASSED\n")


def test_real_pr(pr_url):
    from app.github.client import GitHubClient
    from app.github.pull_request import fetch_pull_request, fetch_file_at_head
    from app.code_engine.diff import build_file_diffs

    client = GitHubClient()
    pr = fetch_pull_request(client, pr_url)
    print(f"=== {pr['repository']} PR #{pr['pr_number']} ===")

    for d in build_file_diffs(pr["changed_files"]):
        if not d.filename.endswith(".py") or d.status == "removed":
            print(f"\n{d.filename}: skipped (not a .py file, or deleted)")
            continue

        source = fetch_file_at_head(client, pr, d.filename)
        if source is None:
            print(f"\n{d.filename}: could not fetch file")
            continue

        print(f"\n{d.filename}  (changed lines: {d.changed_new_lines})")
        for r in get_change_contexts(source, d.changed_new_lines):
            func, cls = r["function"], r["class"]
            print(f"  lines {r['changed_lines']}")
            print(f"    function: {func['name'] if func else '(module level)'}"
                  + (f"  [{func['start_line']}-{func['end_line']}]" if func else ""))
            print(f"    class   : {cls['name'] if cls else '(none)'}")


if __name__ == "__main__":
    test_sample()
    if len(sys.argv) > 1:
        test_real_pr(sys.argv[1])