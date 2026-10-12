from app.code_engine.diff import build_file_diffs
from app.code_engine.tree_context import get_change_contexts
from app.github.client import GitHubClient
from app.github.pull_request import fetch_file_at_head

LEVELS = ("diff", "function", "file")

MODULE_WINDOW = 5        # lines of padding around changes that are outside any function
NON_PY_WINDOW = 15       # padding for non-Python files at "function" level
MAX_FILE_CHARS = 40000   # files bigger than this get trimmed at "file" level
TRIM_RADIUS = 200        # padding used when trimming a big file
DEFAULT_MAX_FILES = 30   # PRs with more changed files than this get cut off


def _number(lines, start, end):
    """Return lines start..end (1-based) with line numbers in front."""
    end = min(end, len(lines))
    return "\n".join(f"{n}: {lines[n - 1]}" for n in range(start, end + 1))


def _window(total, changed, radius):
    """A range of lines around the changed lines, kept inside the file."""
    start = max(1, min(changed) - radius)
    end = min(total, max(changed) + radius)
    return start, end


def _make_unit(kind, function, cls, start, end, changed_lines, lines):
    """One chunk of code to show the AI, with a small header and line numbers."""
    label = kind
    if function:
        label += f" {function}"
    if cls:
        label += f" (class {cls})"
    header = f"# {label}, lines {start}-{end}, changed: {changed_lines}"
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


def _function_units(source, changed, is_python):
    lines = source.splitlines()

    if not is_python:
        start, end = _window(len(lines), changed, NON_PY_WINDOW)
        return [_make_unit("window", None, None, start, end, changed, lines)]

    units = []
    for group in get_change_contexts(source, changed):
        func, cls = group["function"], group["class"]
        if func:
            start, end, kind = func["start_line"], func["end_line"], "function"
        else:
            start, end = _window(len(lines), group["changed_lines"], MODULE_WINDOW)
            kind = "window"
        units.append(_make_unit(
            kind,
            func["name"] if func else None,
            cls["name"] if cls else None,
            start, end, group["changed_lines"], lines,
        ))
    return units


def _file_unit(source, changed):
    lines = source.splitlines()
    if len(source) <= MAX_FILE_CHARS:
        start, end, kind = 1, len(lines), "file"
    else:
        start, end = _window(len(lines), changed, TRIM_RADIUS)
        kind = "file_trimmed"
    return _make_unit(kind, None, None, start, end, changed, lines)


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
        units = [_file_unit(source, changed)]

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