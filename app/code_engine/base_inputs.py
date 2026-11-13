from app.code_engine.context_builder import _function_units, _window_units
from app.code_engine.diff import build_file_diffs
from app.code_engine.review_input import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_FILES,
    _entry,
    _functions_for,
    _pick_window,
)

# The Groq free tier rejects requests above about 8,000 tokens per minute, so the extra
# context is capped lower than the 12,000 chars agreed earlier.
HINT_MAX_CHARS = 8000


def is_test_file(path):
    return path.endswith(".py") and "test" in path.lower()


def base_changed_lines(file_diff):
    """Lines of the OLD (pre-fix) file that the PR touches.
    Removed lines count directly. For a pure insertion we take the old line just before it."""
    touched = set()
    for hunk in file_diff.hunks:
        last_old = hunk.old_start
        for line in hunk.lines:
            if line.kind == "removed":
                touched.add(line.old_line)
                last_old = line.old_line
            elif line.kind == "context":
                last_old = line.old_line
            else:  # added
                touched.add(last_old)
    return sorted(n for n in touched if n and n > 0)


def _plain(units, lines):
    """Unit texts WITHOUT line numbers: `code` is numbered from 1, so numbers in the hint would confuse the model."""
    parts = []
    for u in units:
        label = u["kind"]
        if u["function"]:
            label += f" {u['function']}"
        if u["class"]:
            label += f" (class {u['class']})"
        parts.append(f"# {label}\n" + "\n".join(lines[u["start_line"] - 1:u["end_line"]]))
    return "\n\n".join(parts)


def _file_hint_units(lines, changed, cap):
    """Windows around the changes, with the padding halved until the text fits the cap."""
    radius = 200
    while True:
        units = _window_units(lines, changed, radius)
        size = sum(len(l) + 1 for u in units for l in lines[u["start_line"] - 1:u["end_line"]])
        if size <= cap or radius <= 3:
            return units
        radius //= 2


def build_hint(level, source, changed, max_chars=HINT_MAX_CHARS):
    """Extra context for the AI at a given level, built from the BASE (pre-fix) code only.
    It never contains the PR's real patch (that would give away the answer) and has no line numbers."""
    lines = source.splitlines()
    if level == "diff":          # "changed region": only the lines the fix touches, plus 3 around
        units = _window_units(lines, changed, 3)
        for u in units:
            u["kind"] = "changed region"
    elif level == "function":
        units = _function_units(source, changed, True)
    elif level == "file":
        units = _file_hint_units(lines, changed, max_chars)
        for u in units:
            u["kind"] = "file excerpt"
    else:
        return None
    return _plain(units, lines)


def build_base_inputs(pr, client, max_chars=DEFAULT_MAX_CHARS, max_files=DEFAULT_MAX_FILES):
    """Review inputs for the code BEFORE the PR (the base commit): the buggy version the AI must repair.
    Returns (entries, sources). Entries have the same shape as get_review_inputs(), plus
    'all_changed_lines'. sources maps file name -> the full base file text."""
    owner, repo = pr["repository"].split("/")
    diffs = build_file_diffs(pr["changed_files"])
    entries, sources = [], {}
    included = 0

    for changed_file, file_diff in zip(pr["changed_files"], diffs):
        name, status = changed_file["filename"], changed_file["status"]

        def skip(reason, changed=None):
            entries.append(_entry(name, status, changed=changed, skipped=True, skip_reason=reason))

        if is_test_file(name):
            skip("test file (goes into the workspace, not reviewed)")
            continue
        if not name.endswith(".py"):
            skip("not a Python file")
            continue
        if status in ("added", "renamed", "removed"):
            skip(f"file is {status}, no base version to repair")
            continue

        changed = base_changed_lines(file_diff)
        if not changed:
            skip("no changed lines")
            continue
        if included >= max_files:
            skip(f"over the {max_files}-file limit", changed)
            continue

        try:
            source = client.get_file_text(owner, repo, name, pr["base_sha"])
        except Exception as error:
            skip(f"fetch error: {type(error).__name__}", changed)
            continue
        if source is None:
            skip("could not fetch base file", changed)
            continue

        functions, too_large = _functions_for(source, changed, "python", max_chars)
        lines = source.splitlines()
        if len(source) <= max_chars:
            entry = _entry(name, status, text=source, changed=changed,
                           start_line=1, end_line=len(lines),
                           functions=functions, skipped_functions=too_large)
        else:
            anchor = [n for f in functions for n in (f["start_line"], f["end_line"])] or changed
            start, end = _pick_window(lines, anchor, max_chars)
            entry = _entry(name, status, text="\n".join(lines[start - 1:end]),
                           changed=[n for n in changed if start <= n <= end],
                           truncated=True, start_line=start, end_line=end,
                           functions=functions, skipped_functions=too_large)
        entry["all_changed_lines"] = changed
        entries.append(entry)
        sources[name] = source
        included += 1

    return entries, sources