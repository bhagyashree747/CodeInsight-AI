import re

from app.code_engine.base_inputs import HINT_MAX_CHARS, build_hint


def test_no_line_numbers():
    source = "\n".join(f"x{i} = {i}" for i in range(1, 301))
    for level in ("diff", "function", "file"):
        hint = build_hint(level, source, [150])
        assert hint, level
        assert not re.search(r"^\d+: ", hint, re.M), level      # no "150: code" prefixes
        assert not re.search(r"lines \d+", hint), level          # no "lines 140-160" headers
    print("hints carry no line numbers                  : OK")


def test_file_hint_is_capped():
    source = "\n".join(f"x{i} = {i}" for i in range(1, 3001))
    hint = build_hint("file", source, [1500, 2800])
    assert len(hint) <= HINT_MAX_CHARS + 200
    assert "x1500 = 1500" in hint and "x2800 = 2800" in hint
    print("file hint stays under the cap, both changes  : OK")


if __name__ == "__main__":
    print("=== Hint tests (no internet needed) ===")
    test_no_line_numbers()
    test_file_hint_is_capped()
    print("ALL TESTS PASSED")