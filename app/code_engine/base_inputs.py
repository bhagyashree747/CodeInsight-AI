from app.code_engine.context_builder import _file_units, _function_units, _window_units
from app.code_engine.diff import build_file_diffs
from app.code_engine.review_input import (
    DEFAULT_MAX_CHARS,
    DEFAULT_MAX_FILES,
    _entry,
    _functions_for,
    _pick_window,
)


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


def build_hint(level, source, changed):
    """Extra context for the AI at a given level, built from the BASE (pre-fix) code only.
    It never contains the PR's real patch: that would give away the answer."""
    lines = source.splitlines()
    if level == "diff":          # "localized region": only the lines the fix touches, plus 3 around
        units = _window_units(lines, changed, 3)
    elif level == "function":
        units = _function_units(source, changed, True)
    elif level == "file":
        units = _file_units(source, changed)
    else:
        return None
    return "\n\n".join(u["text"] for u in units)


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