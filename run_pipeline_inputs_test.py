from app.code_engine.base_inputs import build_base_inputs
from app.code_engine.pipeline_inputs import make_pipeline_inputs

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


def sample_entry():
    patch = "\n".join(["@@ -7,1 +7,1 @@",
                       "-            total += item.price",
                       "+            total += item.price * item.qty"])
    pr = {"repository": "o/r", "pr_number": 1, "title": "t", "head_sha": "h", "base_sha": "b",
          "changed_files": [{"filename": "cart.py", "status": "modified",
                             "additions": 1, "deletions": 1, "patch": patch}]}
    entries, sources = build_base_inputs(pr, FakeClient())
    return entries[0], sources["cart.py"]


def test_whole_file():
    entry, source = sample_entry()
    r = make_pipeline_inputs(entry, source, "window")
    f = r["functions"][0]
    assert r["code"] == source and r["window"] is None
    assert (f["start_line"], f["end_line"]) == (4, 8) and r["changed_lines"] == {7}
    print("whole file as code (numbers unchanged)        : OK")


def test_function_scope():
    entry, source = sample_entry()
    r = make_pipeline_inputs(entry, source, "function")
    f = r["functions"][0]
    assert r["code"] == "\n".join(SAMPLE.splitlines()[3:8]) and r["window"] == (4, 8)
    assert (f["start_line"], f["end_line"]) == (1, 5)
    assert f["changed_lines"] == [4] and r["changed_lines"] == {4}
    assert "\n".join(r["code"].splitlines()[0:5]) == f["text"]
    print("function span as code (numbers re-based)      : OK")


def test_window_is_relative():
    source = "\n".join(f"x{i} = {i}" for i in range(1, 3001))
    entry = {
        "functions": [
            {"name": "f", "start_line": 2000, "end_line": 2001,
             "text": "x2000 = 2000\nx2001 = 2001", "class": None, "changed_lines": [2001]},
            {"name": "far", "start_line": 100, "end_line": 101,
             "text": "x100 = 100\nx101 = 101", "class": None, "changed_lines": [100]},
        ],
        "start_line": 1500, "end_line": 2600, "all_changed_lines": [100, 2001],
    }
    r = make_pipeline_inputs(entry, source, "window")
    code_lines = r["code"].splitlines()
    f = r["functions"][0]
    assert r["window"] == (1500, 2600) and len(code_lines) == 1101
    assert (f["start_line"], f["end_line"]) == (501, 502)
    assert "\n".join(code_lines[f["start_line"] - 1:f["end_line"]]) == f["text"]
    assert r["changed_lines"] == {502}
    assert r["dropped_functions"] == ["far"]
    print("window: numbers relative, far function dropped: OK")

    r2 = make_pipeline_inputs(entry, source, "function")   # span 100..2001 is too big
    assert r2["window"] == (1500, 2600) and "fell back" in r2["note"]
    print("function span too big -> falls back to window : OK")


if __name__ == "__main__":
    print("=== Pipeline-input tests (no internet needed) ===")
    test_whole_file()
    test_function_scope()
    test_window_is_relative()
    print("ALL TESTS PASSED")