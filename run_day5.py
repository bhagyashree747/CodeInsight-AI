import sys

from app.code_engine import context_builder as cb
from app.code_engine.context_builder import build_context, build_file_context, LEVELS
from app.code_engine.diff import parse_patch, FileDiff


def run_file(filename, status, patch, source, level):
    changed_file = {"filename": filename, "status": status, "patch": patch}
    diff = FileDiff(filename, status, parse_patch(patch))
    return build_file_context(changed_file, diff, source, level)


def test_added_file():
    patch = "\n".join([
        "@@ -0,0 +1,3 @@",
        "+def a():",
        "+    return 1",
        "+x = 2",
    ])
    source = "\n".join(["def a():", "    return 1", "x = 2"])
    r = run_file("new.py", "added", patch, source, "function")
    assert r["level"] == "function"
    assert len(r["units"]) == 2                    # the function + the module-level line
    assert r["units"][0]["function"] == "a"
    print("added file             : OK")


def test_removed_file():
    patch = "\n".join(["@@ -1,2 +0,0 @@", "-a", "-b"])
    r = run_file("old.py", "removed", patch, None, "function")
    assert r["level"] == "diff" and r["note"]
    print("removed file           : OK (falls back to diff)")


def test_renamed_no_patch():
    r = run_file("b.py", "renamed", "", "x = 1", "function")
    assert r["level"] == "diff"
    assert "(no diff available)" in r["text"]
    print("renamed, no patch      : OK (falls back to diff)")


def test_non_python_file():
    source = "\n".join(f"k{i}: v" for i in range(1, 41))
    patch = "\n".join(["@@ -20,1 +20,1 @@", "-a: 1", "+a: 2"])
    r = run_file("config.yml", "modified", patch, source, "function")
    unit = r["units"][0]
    assert unit["kind"] == "window" and unit["function"] is None
    assert (unit["start_line"], unit["end_line"]) == (5, 35)
    print("non-Python file        : OK (plain window)")


def _fake_pr(filenames):
    return {
        "repository": "o/r",
        "pr_number": 1,
        "title": "test",
        "head_sha": "abc",
        "changed_files": [
            {"filename": n, "status": "modified", "additions": 1, "deletions": 1,
             "patch": "@@ -1,1 +1,1 @@\n-a\n+b"}
            for n in filenames
        ],
    }


def test_max_files():
    pr = _fake_pr([f"f{i}.py" for i in range(5)])
    ctx = build_context(pr, level="diff", max_files=2)
    assert len(ctx["files"]) == 2
    assert ctx["skipped_files"] == ["f2.py", "f3.py", "f4.py"]
    assert "not included" in ctx["text"]
    print("max_files limit        : OK")


def test_error_fallback():
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    original = cb.fetch_file_at_head
    cb.fetch_file_at_head = boom
    try:
        ctx = build_context(_fake_pr(["a.py"]), level="function")
    finally:
        cb.fetch_file_at_head = original

    f = ctx["files"][0]
    assert f["level"] == "diff" and f["requested_level"] == "function"
    assert "RuntimeError" in f["note"]
    print("error in one file      : OK (falls back, no crash)")


def test_bad_level():
    try:
        build_context(_fake_pr(["a.py"]), level="banana")
    except ValueError:
        print("invalid level          : OK (raises ValueError)")
        return
    raise AssertionError("expected ValueError")


def run_offline_tests():
    print("=== Edge-case tests (no internet needed) ===")
    test_added_file()
    test_removed_file()
    test_renamed_no_patch()
    test_non_python_file()
    test_max_files()
    test_error_fallback()
    test_bad_level()
    print("ALL EDGE-CASE TESTS PASSED\n")


DEFAULT_PRS = [
    "https://github.com/psf/requests/pull/6700",
    "https://github.com/psf/requests/pull/7539",
    "https://github.com/psf/requests/pull/7445",
]


def real_summary(urls):
    from app.code_engine.interface import get_all_levels

    print("=== Real PRs through get_all_levels() ===")
    for url in urls:
        results = get_all_levels(url)
        first = results["diff"]
        print(f"\n{first['repository']} PR #{first['pr_number']}: {first['title']}")
        for level in LEVELS:
            ctx = results[level]
            fell_back = sum(1 for f in ctx["files"] if f["level"] != f["requested_level"])
            print(f"  {level:9} {len(ctx['text']):>7} chars | files: {len(ctx['files'])}"
                  f" | fell back to diff: {fell_back}")
            assert ctx["text"].strip(), "empty context text"
    print("\nReal-PR check done")


if __name__ == "__main__":
    run_offline_tests()
    args = sys.argv[1:]
    if args == ["real"]:
        real_summary(DEFAULT_PRS)
    elif args:
        real_summary(args)