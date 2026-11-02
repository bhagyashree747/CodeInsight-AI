import os

from app.code_engine.diff import build_file_diffs
from app.code_engine.tree_context import get_change_contexts
from app.github.pull_request import fetch_file_at_head

DEFAULT_MAX_CHARS = 12000   # Member 1's limit per file
DEFAULT_MAX_FILES = 5       # Member 1's limit per PR

LANGUAGES = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".java": "java",
    ".c": "c", ".cpp": "cpp", ".go": "go", ".rs": "rust", ".rb": "ruby",
    ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".md": "markdown",
}


def detect_language(filename):
    return LANGUAGES.get(os.path.splitext(filename)[1].lower(), "text")


def _pick_window(lines, changed, max_chars):
    """Choose a range of lines (1-based, inclusive) around the changes that fits max_chars."""
    start, end = min(changed), max(changed)
    start = max(1, min(start, len(lines)))
    end = max(start, min(end, len(lines)))
    size = sum(len(line) + 1 for line in lines[start - 1:end])

    if size > max_chars:
        # the changes alone are too big: keep as much as fits, from the first change
        end, size = start, len(lines[start - 1]) + 1
        while end < len(lines) and size + len(lines[end]) + 1 <= max_chars:
            end += 1
            size += len(lines[end - 1]) + 1
        return start, end

    # grow outward (up and down) until the budget is used up
    while True:
        grew = False
        if start > 1 and size + len(lines[start - 2]) + 1 <= max_chars:
            start -= 1
            size += len(lines[start - 1]) + 1
            grew = True
        if end < len(lines) and size + len(lines[end]) + 1 <= max_chars:
            end += 1
            size += len(lines[end - 1]) + 1
            grew = True
        if not grew:
            return start, end


def _functions_for(source, changed, language, max_chars):
    """The functions that contain a changed line (Python only).
    Cut from the FULL file, so they stay complete even when the file text is truncated.
    Functions bigger than max_chars are left out and their names are returned separately."""
    if language != "python":
        return [], []

    functions, too_large = [], []
    for group in get_change_contexts(source, changed):
        func, cls = group["function"], group["class"]
        if func is None:            # change outside any function (imports, constants)
            continue
        if len(func["code"]) > max_chars:
            too_large.append(func["name"])
            continue
        functions.append({
            "name": func["name"],
            "start_line": func["start_line"],   # includes @decorators
            "end_line": func["end_line"],
            "text": func["code"],               # plain code, original indentation, no line numbers
            "class": cls["name"] if cls else None,
            "changed_lines": group["changed_lines"],
        })
    return functions, too_large


def _entry(filename, status, text="", changed=None, truncated=False,
           start_line=1, end_line=0, skipped=False, skip_reason=None,
           functions=None, skipped_functions=None):
    return {
        # the fields Member 1 asked for
        "file": filename,
        "text": text,
        "changed_lines": changed or [],
        "language": detect_language(filename),
        "truncated": truncated,
        "functions": functions or [],
        # extras
        "skipped_functions": skipped_functions or [],
        "start_line": start_line,
        "end_line": end_line,
        "status": status,
        "skipped": skipped,
        "skip_reason": skip_reason,
    }


def build_review_inputs(pr, client, max_chars=DEFAULT_MAX_CHARS, max_files=DEFAULT_MAX_FILES):
    """One dict per changed file, in the shape Member 1's module expects."""
    diffs = build_file_diffs(pr["changed_files"])
    pairs = list(zip(pr["changed_files"], diffs))
    # Python files first, so the file limit keeps the files the demo cares about
    pairs.sort(key=lambda pair: not pair[0]["filename"].endswith(".py"))

    results = []
    included = 0
    for changed_file, file_diff in pairs:
        name = changed_file["filename"]
        status = changed_file["status"]
        changed = file_diff.changed_new_lines

        if status == "removed":
            results.append(_entry(name, status, skipped=True, skip_reason="file deleted"))
            continue
        if not changed:
            results.append(_entry(name, status, skipped=True,
                                  skip_reason="no changed lines (binary, rename or empty diff)"))
            continue
        if included >= max_files:
            results.append(_entry(name, status, changed=changed, skipped=True,
                                  skip_reason=f"over the {max_files}-file limit"))
            continue

        try:
            source = fetch_file_at_head(client, pr, name)
        except Exception as error:
            results.append(_entry(name, status, changed=changed, skipped=True,
                                  skip_reason=f"fetch error: {type(error).__name__}"))
            continue
        if source is None:
            results.append(_entry(name, status, changed=changed, skipped=True,
                                  skip_reason="could not fetch file"))
            continue

        # functions come from the FULL file, before any truncation
        functions, too_large = _functions_for(source, changed, detect_language(name), max_chars)

        lines = source.splitlines()
        if len(source) <= max_chars:
            results.append(_entry(name, status, text=source, changed=changed,
                                  start_line=1, end_line=len(lines),
                                  functions=functions, skipped_functions=too_large))
        else:
            start, end = _pick_window(lines, changed, max_chars)
            kept = [n for n in changed if start <= n <= end]
            results.append(_entry(name, status, text="\n".join(lines[start - 1:end]),
                                  changed=kept, truncated=True,
                                  start_line=start, end_line=end,
                                  functions=functions, skipped_functions=too_large))
        included += 1

    return results