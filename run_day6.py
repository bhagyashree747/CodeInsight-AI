import subprocess
import sys

import app.code_engine.review_input as ri

REQUIRED_KEYS = {"file", "text", "changed_lines", "language", "truncated"}
PATCH = "@@ -1,1 +1,1 @@\n-a\n+b"


def fake_pr(files):
    return {
        "repository": "o/r", "pr_number": 1, "title": "test",
        "head_sha": "abc", "base_sha": "def",
        "changed_files": [
            {"filename": name, "status": status, "additions": 1, "deletions": 1, "patch": patch}
            for name, status, patch in files
        ],
    }


def run_review(pr, sources, **kwargs):
    """Run build_review_inputs with a fake file-fetcher (no internet)."""
    original = ri.fetch_file_at_head
    ri.fetch_file_at_head = lambda client, pr_, name: sources.get(name)
    try:
        return ri.build_review_inputs(pr, None, **kwargs)
    finally:
        ri.fetch_file_at_head = original


def test_small_file():
    source = "x = 1\ny = 2\nz = 3"
    patch = "@@ -2,1 +2,1 @@\n-y = 1\n+y = 2"
    e = run_review(fake_pr([("app/a.py", "modified", patch)]), {"app/a.py": source})[0]
    assert REQUIRED_KEYS <= e.keys()
    assert e["text"] == source and e["truncated"] is False
    assert e["changed_lines"] == [2] and e["language"] == "python"
    assert (e["start_line"], e["end_line"]) == (1, 3)
    print("small file sent whole      : OK")


def test_truncation():
    source = "\n".join(f"line {i}" for i in range(1, 3001))
    patch = "@@ -1500,1 +1500,1 @@\n-old\n+new"
    e = run_review(fake_pr([("big.py", "modified", patch)]), {"big.py": source},
                   max_chars=12000)[0]
    assert e["truncated"] is True
    assert len(e["text"]) <= 12000
    assert e["start_line"] <= 1500 <= e["end_line"]
    assert e["changed_lines"] == [1500]
    assert e["text"].splitlines()[1500 - e["start_line"]] == "line 1500"
    print("big file truncated         : OK (window keeps the changed line)")


def test_file_limit():
    names = [f"m{i}.py" for i in range(7)]
    out = run_review(fake_pr([(n, "modified", PATCH) for n in names]),
                     {n: "a = 1" for n in names}, max_files=5)
    skipped = [e for e in out if e["skipped"]]
    assert sum(1 for e in out if not e["skipped"]) == 5
    assert len(skipped) == 2 and "limit" in skipped[0]["skip_reason"]
    print("5-file limit               : OK")


def test_python_first():
    pr = fake_pr([("README.md", "modified", PATCH), ("a.py", "modified", PATCH)])
    by = {e["file"]: e for e in run_review(pr, {"README.md": "a", "a.py": "a = 1"}, max_files=1)}
    assert not by["a.py"]["skipped"] and by["README.md"]["skipped"]
    print("Python files kept first    : OK")


def test_removed_and_missing():
    pr = fake_pr([("gone.py", "removed", "@@ -1,1 +0,0 @@\n-a"),
                  ("ghost.py", "modified", PATCH)])
    by = {e["file"]: e for e in run_review(pr, {})}
    assert by["gone.py"]["skipped"] and "deleted" in by["gone.py"]["skip_reason"]
    assert by["ghost.py"]["skipped"] and "fetch" in by["ghost.py"]["skip_reason"]
    print("deleted / missing files    : OK (skipped with reason)")


def run_offline_tests():
    print("=== Review-input tests (no internet needed) ===")
    test_small_file()
    test_truncation()
    test_file_limit()
    test_python_first()
    test_removed_and_missing()
    print("ALL TESTS PASSED\n")


def show_real(url):
    from app.code_engine.interface import get_review_inputs

    print(f"=== get_review_inputs({url}) ===")
    for e in get_review_inputs(url):
        print(f"{e['file']} | {e['language']} | skipped={e['skipped']} | "
              f"truncated={e['truncated']} | chars={len(e['text'])} | "
              f"lines {e['start_line']}-{e['end_line']} | changed={e['changed_lines']}")
        if e["skip_reason"]:
            print(f"    reason: {e['skip_reason']}")


def show_checkout(url):
    from app.github.client import GitHubClient
    from app.github.pull_request import fetch_pull_request
    from app.github.checkout import checkout_pr_base

    pr = fetch_pull_request(GitHubClient(), url)
    folder = checkout_pr_base(pr)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=folder,
                          capture_output=True, text=True).stdout.strip()
    print("Cloned to :", folder)
    print("HEAD      :", head)
    print("base_sha  :", pr["base_sha"])
    print("match     :", head == pr["base_sha"])


if __name__ == "__main__":
    run_offline_tests()
    args = sys.argv[1:]
    if args[:1] == ["checkout"] and len(args) > 1:
        show_checkout(args[1])
    elif args:
        show_real(args[0])