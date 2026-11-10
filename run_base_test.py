from app.code_engine.base_inputs import base_changed_lines, build_base_inputs, build_hint
from app.code_engine.diff import FileDiff, parse_patch
from app.integration.verifier import FailToPassVerifier

SAMPLE = "\n".join([
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


class FakeClient:
    def get_file_text(self, owner, repo, path, ref):
        return SAMPLE


def test_base_changed_lines():
    patch = "\n".join([
        "@@ -7,3 +7,3 @@",
        "     keep1",
        "-    old_line",
        "+    new_line",
        "     keep2",
        "@@ -20,2 +20,3 @@",
        "     before",
        "+    inserted",
        "     after",
    ])
    assert base_changed_lines(FileDiff("a.py", "modified", parse_patch(patch))) == [8, 20]
    print("base line numbers (removed + insertion points) : OK")


def test_base_inputs():
    patch = "\n".join(["@@ -7,1 +7,1 @@",
                       "-            total += item.price",
                       "+            total += item.price * item.qty"])
    files = [{"filename": n, "status": "modified", "additions": 1, "deletions": 1, "patch": patch}
             for n in ("cart.py", "tests/test_cart.py", "config.yml")]
    pr = {"repository": "o/r", "pr_number": 1, "title": "t", "head_sha": "h",
          "base_sha": "b", "changed_files": files}
    entries, sources = build_base_inputs(pr, FakeClient())
    by = {e["file"]: e for e in entries}
    assert not by["cart.py"]["skipped"] and by["cart.py"]["changed_lines"] == [7]
    assert [f["name"] for f in by["cart.py"]["functions"]] == ["total"]
    assert by["tests/test_cart.py"]["skipped"] and by["config.yml"]["skipped"]
    assert sources["cart.py"] == SAMPLE
    print("base inputs (source kept, tests/yml skipped)    : OK")


def test_hints():
    assert build_hint("none", SAMPLE, [7]) is None
    region = build_hint("diff", SAMPLE, [7])
    assert "total += item.price * item.qty" in region and "helper" not in region
    assert "def total" in build_hint("function", SAMPLE, [7])
    assert build_hint("file", SAMPLE, [7]).count("\n") >= 11
    print("context hints (never the real patch)            : OK")


def test_window_reconstruction():
    orig = [f"l{i}" for i in range(1, 101)]
    original = "\n".join(orig) + "\n"
    v = FailToPassVerifier(None, "python", [], "a.py", original, window=(40, 60))

    patched_window = [f"w{i}" for i in range(40, 61)]
    full = v._to_full_file("\n".join(patched_window))
    lines = full.splitlines()
    assert lines[:39] == orig[:39] and lines[39:60] == patched_window and lines[60:] == orig[60:]
    assert full.endswith("\n")

    whole = "\n".join(orig[:50] + ["extra"] + orig[50:])
    assert v._to_full_file(whole) == whole
    print("verifier accepts a window or a whole file       : OK")


def test_syntax_stage():
    v = FailToPassVerifier(None, "python", [], "a.py", "x = 1\n", window=None)
    r = v.verify("def broken(:\n")
    assert r.passed is False and r.stage == "syntax"
    print("syntax errors are caught before running tests   : OK")


if __name__ == "__main__":
    print("=== Base-version and verifier tests (no internet needed) ===")
    test_base_changed_lines()
    test_base_inputs()
    test_hints()
    test_window_reconstruction()
    test_syntax_stage()
    print("ALL TESTS PASSED")