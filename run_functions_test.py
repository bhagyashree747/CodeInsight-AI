import sys

import app.code_engine.review_input as ri

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

# two hunks: line 7 and line 12 changed
SAMPLE_PATCH = "\n".join([
    "@@ -7,1 +7,1 @@",
    "-            total += item.price",
    "+            total += item.price * item.qty",
    "@@ -12,1 +12,1 @@",
    "-    return 0",
    "+    return 1",
])


def fake_pr(filename, patch, status="modified"):
    return {
        "repository": "o/r", "pr_number": 1, "title": "test",
        "head_sha": "abc", "base_sha": "def",
        "changed_files": [{"filename": filename, "status": status,
                           "additions": 1, "deletions": 1, "patch": patch}],
    }


def run_review(filename, patch, source, **kwargs):
    """Run build_review_inputs with a fake file-fetcher (no internet)."""
    original = ri.fetch_file_at_head
    ri.fetch_file_at_head = lambda client, pr_, name: source
    try:
        return ri.build_review_inputs(fake_pr(filename, patch), None, **kwargs)[0]
    finally:
        ri.fetch_file_at_head = original


def test_functions_basic():
    e = run_review("cart.py", SAMPLE_PATCH, SAMPLE_SOURCE)
    fn = e["functions"]
    assert [f["name"] for f in fn] == ["total", "helper"]
    assert (fn[0]["start_line"], fn[0]["end_line"]) == (4, 8)
    assert (fn[1]["start_line"], fn[1]["end_line"]) == (11, 12)
    assert fn[0]["class"] == "Cart" and fn[1]["class"] is None
    assert fn[0]["changed_lines"] == [7] and fn[1]["changed_lines"] == [12]
    assert fn[0]["text"] == "\n".join(SAMPLE_SOURCE.splitlines()[3:8])
    assert fn[0]["text"].splitlines()[0] == "    def total(self, items):"   # indentation kept
    print("changed functions found      : OK (name, lines, class, text)")


def test_functions_survive_truncation():
    source = "\n".join([f"x{i} = {i}" for i in range(1, 2001)]
                       + ["", "def target():", "    return 1", "y = 2"])
    patch = "@@ -2003,1 +2003,1 @@\n-    return 0\n+    return 1"
    e = run_review("big.py", patch, source, max_chars=12000)
    assert e["truncated"] is True and len(e["text"]) <= 12000
    f = e["functions"][0]
    assert f["name"] == "target" and (f["start_line"], f["end_line"]) == (2002, 2003)
    assert f["text"] == "def target():\n    return 1"
    print("functions complete in a cut file: OK")


def test_function_too_large():
    e = run_review("cart.py", SAMPLE_PATCH, SAMPLE_SOURCE, max_chars=60)
    assert "total" in e["skipped_functions"]
    assert [f["name"] for f in e["functions"]] == ["helper"]
    print("oversized function skipped   : OK (listed in skipped_functions)")


def test_non_python():
    source = "\n".join(f"k{i}: v" for i in range(1, 11))
    e = run_review("config.yml", "@@ -3,1 +3,1 @@\n-a: 1\n+a: 2", source)
    assert e["functions"] == [] and e["skipped_functions"] == []
    print("non-Python file              : OK (functions is empty)")


def test_module_level_change():
    patch = "@@ -1,1 +1,1 @@\n-import sys\n+import os"
    e = run_review("cart.py", patch, SAMPLE_SOURCE)
    assert e["functions"] == []
    print("change outside any function  : OK (functions is empty)")


def run_offline_tests():
    print("=== Function-field tests (no internet needed) ===")
    test_functions_basic()
    test_functions_survive_truncation()
    test_function_too_large()
    test_non_python()
    test_module_level_change()
    print("ALL TESTS PASSED\n")


def show_real(url):
    from app.code_engine.interface import get_review_inputs

    print(f"=== get_review_inputs({url}) ===")
    for e in get_review_inputs(url):
        print(f"\n{e['file']} | skipped={e['skipped']} | truncated={e['truncated']} "
              f"| text chars={len(e['text'])} | changed={e['changed_lines']}")
        if e["skip_reason"]:
            print(f"    reason: {e['skip_reason']}")
        for f in e["functions"]:
            where = f"class {f['class']}, " if f["class"] else ""
            print(f"    function {f['name']} ({where}lines {f['start_line']}-{f['end_line']}, "
                  f"{len(f['text'])} chars, changed {f['changed_lines']})")
        if e["skipped_functions"]:
            print(f"    too large, left out: {e['skipped_functions']}")


if __name__ == "__main__":
    run_offline_tests()
    if len(sys.argv) > 1:
        show_real(sys.argv[1])