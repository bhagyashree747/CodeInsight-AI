"""Benchmark dataset: 12 buggy Python snippets + 3 clean snippets for evaluation.

Each buggy snippet has:
  - id          : unique string identifier
  - code        : the buggy Python source
  - known_bug_line : 1-indexed line the canonical bug lives on
  - category    : one of "bug", "security", "performance", "logic"
  - test_code   : pytest test that FAILS on the buggy code and PASSES on correct fix
  - fixed_code  : hand-written correct fix (passes test_code)

Each clean snippet has:
  - id, code, known_bug_line=None, category=None, test_code=None, fixed_code=None
    (used only for false-positive measurement)
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkSnippet:
    """A single benchmark entry."""
    id: str
    code: str
    known_bug_line: int | None          # None for clean snippets
    category: str | None                # None for clean snippets
    test_code: str | None = None        # None for clean snippets
    fixed_code: str | None = None       # Hand-written correct fix
    is_clean: bool = False              # True => clean / no-bug snippet


# ---------------------------------------------------------------------------
# 12 Buggy Snippets
# ---------------------------------------------------------------------------

_BUGGY: list[BenchmarkSnippet] = [

    # 1 - SQL Injection (security)
    BenchmarkSnippet(
        id="sql_injection",
        category="security",
        known_bug_line=5,
        code="""\
import sqlite3

def get_user(db_path: str, username: str):
    conn = sqlite3.connect(db_path)
    query = f"SELECT * FROM users WHERE name = '{username}'"
    cur = conn.execute(query)
    row = cur.fetchone()
    conn.close()
    return row
""",
        fixed_code="""\
import sqlite3

def get_user(db_path: str, username: str):
    conn = sqlite3.connect(db_path)
    query = "SELECT * FROM users WHERE name = ?"
    cur = conn.execute(query, (username,))
    row = cur.fetchone()
    conn.close()
    return row
""",
        test_code="""\
import sys, os, sqlite3, tempfile
sys.path.insert(0, os.getcwd())
try:
    from snippet import get_user
except ModuleNotFoundError:
    from sql_injection import get_user

def _make_db():
    tmp = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(tmp)
    conn.execute("CREATE TABLE users (name TEXT)")
    conn.execute("INSERT INTO users VALUES ('alice')")
    conn.commit()
    conn.close()
    return tmp

def test_sql_injection_cannot_exfiltrate():
    db = _make_db()
    result = get_user(db, "' OR '1'='1")
    assert result is None, "SQL injection succeeded — parameterized query required"
    try:
        os.unlink(db)
    except OSError:
        pass
""",
    ),

    # 2 - Division by Zero (bug)
    BenchmarkSnippet(
        id="division_by_zero",
        category="bug",
        known_bug_line=3,
        code="""\
def average(values: list[float]) -> float:
    total = sum(values)
    return total / len(values)
""",
        fixed_code="""\
def average(values: list[float]) -> float:
    if not values:
        return 0.0
    total = sum(values)
    return total / len(values)
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import average
except ModuleNotFoundError:
    from division_by_zero import average

def test_empty_list_returns_zero():
    assert average([]) == 0.0

def test_nonempty_works():
    assert average([2.0, 4.0]) == 3.0
""",
    ),

    # 3 - Mutable Default Argument (bug)
    BenchmarkSnippet(
        id="mutable_default",
        category="bug",
        known_bug_line=1,
        code="""\
def append_item(item: str, collection: list[str] = []) -> list[str]:
    collection.append(item)
    return collection
""",
        fixed_code="""\
def append_item(item: str, collection: list[str] | None = None) -> list[str]:
    if collection is None:
        collection = []
    collection.append(item)
    return collection
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import append_item
except ModuleNotFoundError:
    from mutable_default import append_item

def test_independent_calls():
    r1 = append_item("a")
    r2 = append_item("b")
    assert r2 == ["b"], f"State leaked between calls: {r2}"
""",
    ),

    # 4 - Off-by-one in slice (logic)
    BenchmarkSnippet(
        id="off_by_one",
        category="logic",
        known_bug_line=2,
        code="""\
def last_n(items: list, n: int) -> list:
    return items[len(items) - n + 1:]
""",
        fixed_code="""\
def last_n(items: list, n: int) -> list:
    return items[len(items) - n:]
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import last_n
except ModuleNotFoundError:
    from off_by_one import last_n

def test_last_two():
    assert last_n([1, 2, 3, 4, 5], 2) == [4, 5], "Off-by-one in slice"

def test_last_one():
    assert last_n([10, 20, 30], 1) == [30]
""",
    ),

    # 5 - None attribute access (bug)
    BenchmarkSnippet(
        id="none_handling",
        category="bug",
        known_bug_line=2,
        code="""\
def get_username(user: dict | None) -> str:
    return user["name"].strip()
""",
        fixed_code="""\
def get_username(user: dict | None) -> str:
    if not user or "name" not in user:
        return ""
    return user["name"].strip()
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import get_username
except ModuleNotFoundError:
    from none_handling import get_username

def test_none_input():
    assert get_username(None) == ""

def test_normal():
    assert get_username({"name": "  alice  "}) == "alice"
""",
    ),

    # 6 - Wrong comparison (is vs ==) (logic)
    BenchmarkSnippet(
        id="identity_vs_equality",
        category="logic",
        known_bug_line=3,
        code="""\
def is_admin(role: str) -> bool:
    ADMIN = "admin"
    return role is ADMIN
""",
        fixed_code="""\
def is_admin(role: str) -> bool:
    ADMIN = "admin"
    return role == ADMIN
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import is_admin
except ModuleNotFoundError:
    from identity_vs_equality import is_admin

def test_constructed_string():
    role = "".join(["adm", "in"])
    assert is_admin(role) is True, "is vs == comparison failed"

def test_non_admin():
    assert is_admin("user") is False
""",
    ),

    # 7 - Resource not closed (file handle leak) (bug)
    BenchmarkSnippet(
        id="resource_leak",
        category="bug",
        known_bug_line=2,
        code="""\
def read_file(path: str) -> str:
    f = open(path, "r", encoding="utf-8")
    return f.read()
""",
        fixed_code="""\
def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
""",
        test_code="""\
import sys, os, tempfile
sys.path.insert(0, os.getcwd())
try:
    from snippet import read_file
except ModuleNotFoundError:
    from resource_leak import read_file

def test_file_is_closed_after_read(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
    tmp.write("hello")
    tmp.close()

    opened = []
    real_open = open
    def mock_open(*args, **kwargs):
        fh = real_open(*args, **kwargs)
        opened.append(fh)
        return fh

    monkeypatch.setattr("builtins.open", mock_open)
    try:
        content = read_file(tmp.name)
        assert content == "hello"
        assert len(opened) == 1
        assert opened[0].closed, "File was not closed after reading"
    finally:
        if opened and not opened[0].closed:
            opened[0].close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

def test_content_correct():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8")
    tmp.write("world")
    tmp.close()
    try:
        assert read_file(tmp.name) == "world"
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
""",
    ),

    # 8 - Index out of bounds (logic)
    BenchmarkSnippet(
        id="index_out_of_bounds",
        category="logic",
        known_bug_line=2,
        code="""\
def first_and_last(items: list):
    return items[0], items[len(items)]
""",
        fixed_code="""\
def first_and_last(items: list):
    return items[0], items[len(items) - 1]
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import first_and_last
except ModuleNotFoundError:
    from index_out_of_bounds import first_and_last

def test_nonempty():
    assert first_and_last([10, 20, 30]) == (10, 30)

def test_single():
    assert first_and_last([42]) == (42, 42)
""",
    ),

    # 9 - Silent data loss: integer division instead of float (logic)
    BenchmarkSnippet(
        id="integer_division",
        category="logic",
        known_bug_line=2,
        code="""\
def percentage(part: int, total: int) -> float:
    return (part // total) * 100
""",
        fixed_code="""\
def percentage(part: int, total: int) -> float:
    return (part / total) * 100
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import percentage
except ModuleNotFoundError:
    from integer_division import percentage

def test_fractional():
    result = percentage(1, 3)
    assert abs(result - 33.333) < 0.01, f"Got {result}"

def test_zero_total():
    import pytest
    with pytest.raises((ZeroDivisionError, ValueError)):
        percentage(1, 0)
""",
    ),

    # 10 - Wrong default: function mutates caller's list (bug)
    BenchmarkSnippet(
        id="in_place_mutation",
        category="bug",
        known_bug_line=2,
        code="""\
def sorted_copy(items: list) -> list:
    items.sort()
    return items
""",
        fixed_code="""\
def sorted_copy(items: list) -> list:
    return sorted(items)
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import sorted_copy
except ModuleNotFoundError:
    from in_place_mutation import sorted_copy

def test_original_unchanged():
    original = [3, 1, 2]
    result = sorted_copy(original)
    assert result == [1, 2, 3]
    assert original == [3, 1, 2], f"Original was mutated: {original}"
""",
    ),

    # 11 - Swallowed exception hides error (bug)
    BenchmarkSnippet(
        id="swallowed_exception",
        category="bug",
        known_bug_line=4,
        code="""\
def safe_parse(text: str) -> int:
    try:
        return int(text)
    except:
        return 0
""",
        fixed_code="""\
def safe_parse(text: str) -> int:
    return int(text)
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import safe_parse
except ModuleNotFoundError:
    from swallowed_exception import safe_parse
import pytest

def test_valid_int():
    assert safe_parse("42") == 42

def test_invalid_raises():
    with pytest.raises(ValueError):
        safe_parse("not_a_number")
""",
    ),

    # 12 - Missing None guard on dict lookup (bug)
    BenchmarkSnippet(
        id="missing_none_guard",
        category="bug",
        known_bug_line=2,
        code="""\
def get_value(mapping: dict, key: str) -> str:
    return mapping.get(key).upper()
""",
        fixed_code="""\
def get_value(mapping: dict, key: str) -> str:
    val = mapping.get(key)
    if val is None:
        return ""
    return val.upper()
""",
        test_code="""\
import sys, os
sys.path.insert(0, os.getcwd())
try:
    from snippet import get_value
except ModuleNotFoundError:
    from missing_none_guard import get_value

def test_missing_key():
    assert get_value({"a": "hello"}, "missing") == ""

def test_existing_key():
    assert get_value({"a": "hello"}, "a") == "HELLO"
""",
    ),
]


# ---------------------------------------------------------------------------
# 3 Clean Snippets (no bugs — measure false positives)
# ---------------------------------------------------------------------------

_CLEAN: list[BenchmarkSnippet] = [

    BenchmarkSnippet(
        id="clean_factorial",
        category=None,
        known_bug_line=None,
        is_clean=True,
        code="""\
def factorial(n: int) -> int:
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return 1
    return n * factorial(n - 1)
""",
    ),

    BenchmarkSnippet(
        id="clean_binary_search",
        category=None,
        known_bug_line=None,
        is_clean=True,
        code="""\
def binary_search(arr: list[int], target: int) -> int:
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
""",
    ),

    BenchmarkSnippet(
        id="clean_word_count",
        category=None,
        known_bug_line=None,
        is_clean=True,
        code="""\
def word_count(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for word in text.lower().split():
        counts[word] = counts.get(word, 0) + 1
    return counts
""",
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

BENCHMARK: list[BenchmarkSnippet] = _BUGGY + _CLEAN

BUGGY_SNIPPETS: list[BenchmarkSnippet] = _BUGGY
CLEAN_SNIPPETS: list[BenchmarkSnippet] = _CLEAN
