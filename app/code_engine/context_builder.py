from app.code_engine.diff import build_file_diffs
from app.code_engine.tree_context import get_change_contexts
from app.github.client import GitHubClient
from app.github.pull_request import fetch_file_at_head

LEVELS = ("diff", "function", "file")

MODULE_WINDOW = 5        # lines of padding around changes that are outside any function
NON_PY_WINDOW = 15       # padding for non-Python files at "function" level
MAX_FILE_CHARS = 40000   # "file" level: bigger files are trimmed to about this size
TRIM_RADIUS = 200        # starting padding when trimming a big file (shrinks if it does not fit)
DEFAULT_MAX_FILES = 30   # PRs with more changed files than this get cut off


def _number(lines, start, end):
    """Return lines start..end (1-based) with line numbers in front."""
    end = min(end, len(lines))
    return "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))


def _cost(lines, n):
    """Characters that line n adds to the text ("12: code" plus a newline)."""
    return len(lines[n - 1]) + len(str(n)) + 3


def _clusters(changed, gap):
    """Group line numbers into runs. A new run starts when the gap to the previous line is > gap."""
    runs = []
    for n in sorted(set(changed)):
        if runs and n - runs[-1][1] <= gap:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return runs


def _ranges(numbers):
    """[540, 541, 542, 600] -> '540-542, 600' (keeps headers short when many lines changed)."""
    parts = []
    for start, end in _clusters(numbers, 1):
        parts.append(str(start) if start == end else f"{start}-{end}")
    return ", ".join(parts)


def _make_unit(kind, function, cls, start, end, changed_lines, lines):
    """One chunk of code to show the AI, with a small header and line numbers."""
    label = kind
    if function:
        label += f" {function}"
    if cls:
        label += f" (class {cls})"
    header = f"# {label}, lines {start}-{end}, changed: [{_ranges(changed_lines)}]"
    return {
        "kind": kind,
        "function": function,
        "class": cls,
        "start_line": start,
        "end_line": end,
        "changed_lines": changed_lines,
        "text": header + "\n" + _number(lines, start, end),
    }


def _diff_unit(changed_file):
    patch = changed_file.get("patch") or "(no diff available)"
    return {
        "kind": "diff",
        "function": None,
        "class": None,
        "start_line": None,
        "end_line": None,
        "changed_lines": [],
        "text": patch,
    }


def _window_units(lines, changed, radius):
    """One small 'window' unit per cluster of nearby changed lines (never one giant span)."""
    units = []
    for s, e in _clusters(changed, 2 * radius):
        start, end = max(1, s - radius), min(len(lines), e + radius)
        units.append(_make_unit("window", None, None, start, end,
                                [n for n in changed if s <= n <= e], lines))
    return units


def _function_units(source, changed, is_python):
    lines = source.splitlines()

    if not is_python:
        return _window_units(lines, changed, NON_PY_WINDOW)

    units = []
    for group in get_change_contexts(source, changed):
        func, cls = group["function"], group["class"]
        if func:
            units.append(_make_unit(
                "function", func["name"], cls["name"] if cls else None,
                func["start_line"], func["end_line"], group["changed_lines"], lines,
            ))
        else:
            units.extend(_window_units(lines, group["changed_lines"], MODULE_WINDOW))
    return units


def _merge_windows(runs, radius, total):
    """Pad each run of changed lines by `radius` and merge windows that touch or overlap."""
    windows = []
    for s, e in runs:
        s, e = max(1, s - radius), min(total, e + radius)
        if windows and s <= windows[-1][1] + 1:
            windows[-1][1] = max(windows[-1][1], e)
        else:
            windows.append([s, e])
    return windows


def _file_units(source, changed):
    """Whole file if small. Otherwise windows around the changes, kept within MAX_FILE_CHARS."""
    lines = source.splitlines()
    if len(source) <= MAX_FILE_CHARS:
        return [_make_unit("file", None, None, 1, len(lines), changed, lines)]

    runs = _clusters(changed, 2)
    radius = TRIM_RADIUS
    while True:
        windows = _merge_windows(runs, radius, len(lines))
        size = sum(_cost(lines, n) for s, e in windows for n in range(s, e + 1))
        if size <= MAX_FILE_CHARS or radius == 0:
            break
        radius //= 2

    # if it still does not fit, cut the windows to the budget (in order)
    units, used = [], 0
    for s, e in windows:
        end, room = s - 1, MAX_FILE_CHARS - used
        while end < e and _cost(lines, end + 1) <= room:
            room -= _cost(lines, end + 1)
            end += 1
        if end < s:
            break
        units.append(_make_unit("file_trimmed", None, None, s, end,
                                [n for n in changed if s <= n <= end], lines))
        used = MAX_FILE_CHARS - room
    return units


def build_file_context(changed_file, file_diff, source, level):
    """Context for ONE changed file at the requested level."""
    filename = changed_file["filename"]
    changed = file_diff.changed_new_lines
    is_python = filename.endswith(".py")

    used = level
    note = None
    if level != "diff" and (source is None or not changed):
        used = "diff"
        note = "Fell back to diff level: file content or changed lines unavailable."

    if used == "diff":
        units = [_diff_unit(changed_file)]
    elif used == "function":
        units = _function_units(source, changed, is_python)
    else:
        units = _file_units(source, changed)

    text = f"### File: {filename} ({changed_file['status']})\n"
    text += "\n\n".join(u["text"] for u in units)

    return {
        "filename": filename,
        "status": changed_file["status"],
        "level": used,
        "requested_level": level,
        "note": note,
        "changed_lines": changed,
        "units": units,
        "text": text,
    }


def build_context(pr, level="function", client=None, max_files=DEFAULT_MAX_FILES):
    """Context for a whole PR. Input: the dict from fetch_pull_request().

    One bad file never crashes the whole PR: if anything goes wrong for a file,
    that file falls back to diff level and the reason goes in its 'note'.
    max_files=None means no limit."""
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")

    client = client or GitHubClient()
    diffs = build_file_diffs(pr["changed_files"])

    files = []
    skipped = []
    for changed_file, file_diff in zip(pr["changed_files"], diffs):
        if max_files is not None and len(files) >= max_files:
            skipped.append(changed_file["filename"])
            continue

        try:
            source = None
            if level != "diff" and changed_file["status"] != "removed":
                source = fetch_file_at_head(client, pr, changed_file["filename"])
            file_ctx = build_file_context(changed_file, file_diff, source, level)
        except Exception as error:
            file_ctx = build_file_context(changed_file, file_diff, None, "diff")
            file_ctx["requested_level"] = level
            file_ctx["note"] = (
                f"Fell back to diff level after error: {type(error).__name__}: {error}"
            )
        files.append(file_ctx)

    text = "\n\n".join(f["text"] for f in files)
    if skipped:
        text += f"\n\n(+{len(skipped)} more files not included: {', '.join(skipped)})"

    return {
        "repository": pr["repository"],
        "pr_number": pr["pr_number"],
        "title": pr["title"],
        "level": level,
        "files": files,
        "skipped_files": skipped,
        "text": text,
    }