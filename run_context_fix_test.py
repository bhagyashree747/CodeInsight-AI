import app.code_engine.review_input as ri
from app.code_engine.context_builder import build_file_context, MAX_FILE_CHARS
from app.code_engine.diff import parse_patch, FileDiff


def file_context(filename, status, patch, source, level):
    changed_file = {"filename": filename, "status": status, "patch": patch}
    diff = FileDiff(filename, status, parse_patch(patch))
    return build_file_context(changed_file, diff, source, level)


def test_spread_out_changes_are_not_one_giant_window():
    source = "\n".join(f"x{i} = {i}" for i in range(1, 3001))
    patch = "\n".join([
        "@@ -12,1 +12,1 @@", "-a", "+b",
        "@@ -2500,1 +2500,1 @@", "-a", "+b",
    ])
    r = file_context("m.py", "modified", patch, source, "function")
    assert len(r["units"]) == 2
    assert len(r["text"]) < 2000
    print("function level, far-apart changes : OK (2 small windows)")


def test_file_level_is_capped():
    source = "\n".join(f"x{i} = {i}" for i in range(1, 4001))
    assert len(source) > MAX_FILE_CHARS
    patch = "\n".join([
        "@@ -12,1 +12,1 @@", "-a", "+b",
        "@@ -3500,1 +3500,1 @@", "-a", "+b",
    ])
    r = file_context("m.py", "modified", patch, source, "file")
    assert len(r["text"]) <= MAX_FILE_CHARS + 500
    assert all(u["kind"] == "file_trimmed" for u in r["units"])
    covered = lambda n: any(u["start_line"] <= n <= u["end_line"] for u in r["units"])
    assert covered(12) and covered(3500)
    print("file level, big file              : OK (stays under the cap, both changes covered)")


def test_file_level_all_lines_changed():
    source = "\n".join(f"x{i} = {i}" for i in range(1, 4001))
    patch = "@@ -0,0 +1,4000 @@\n" + "\n".join(f"+x{i} = {i}" for i in range(1, 4001))
    r = file_context("new.py", "added", patch, source, "file")
    assert len(r["text"]) <= MAX_FILE_CHARS + 500
    assert r["units"][-1]["end_line"] < 4000
    print("file level, whole file changed    : OK (cut to the cap)")


def test_review_window_centres_on_function():
    head = [f"x{i} = {i}" for i in range(1, 2000)]                  # lines 1..1999
    source = "\n".join(head + ["def target():", "    return 1"]       # lines 2000, 2001
                       + [f"y{i} = {i}" for i in range(1, 1001)])
    patch = "\n".join([
        "@@ -12,1 +12,1 @@", "-a", "+b",
        "@@ -2001,1 +2001,1 @@", "-    return 0", "+    return 1",
    ])
    pr = {"repository": "o/r", "pr_number": 1, "title": "t", "head_sha": "a", "base_sha": "b",
          "changed_files": [{"filename": "big.py", "status": "modified",
                             "additions": 2, "deletions": 2, "patch": patch}]}
    original = ri.fetch_file_at_head
    ri.fetch_file_at_head = lambda client, pr_, name: source
    try:
        e = ri.build_review_inputs(pr, None)[0]
    finally:
        ri.fetch_file_at_head = original

    assert e["truncated"] is True
    assert [f["name"] for f in e["functions"]] == ["target"]
    assert 12 < e["start_line"] <= 2000 and 2001 <= e["end_line"]
    assert e["changed_lines"] == [2001]
    print("review window follows the function: OK (not the import at line 12)")


if __name__ == "__main__":
    print("=== Context fix tests (no internet needed) ===")
    test_spread_out_changes_are_not_one_giant_window()
    test_file_level_is_capped()
    test_file_level_all_lines_changed()
    test_review_window_centres_on_function()
    print("ALL TESTS PASSED")