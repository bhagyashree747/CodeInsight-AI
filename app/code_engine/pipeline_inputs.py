def make_pipeline_inputs(entry, source, scope="window", max_chars=12000):
    """Arguments for Member 1's run_pipeline, with line numbers RELATIVE to `code`
    (line 1 = first line of code), because their splicer indexes into code.splitlines().

    scope "window":   code = the window sent to the AI (or the whole file if it fits)
    scope "function": code = only the span of the changed functions (cleanest for the context ablation)
    Returns code, changed_lines (set), functions (re-based), window (start, end) or None if code is the
    whole file, dropped_functions (names of functions that fall outside code) and note."""
    lines = source.splitlines()
    functions = entry["functions"]
    note = None

    start, end = entry["start_line"], entry["end_line"]
    if scope == "function" and functions:
        f_start = min(f["start_line"] for f in functions)
        f_end = max(f["end_line"] for f in functions)
        if len("\n".join(lines[f_start - 1:f_end])) <= max_chars:
            start, end = f_start, f_end
        else:
            note = "function span over the size limit, fell back to the window"

    kept, dropped = [], []
    for f in functions:
        inside = f["start_line"] >= start and f["end_line"] <= end
        (kept if inside else dropped).append(f)

    offset = start - 1
    rebased = [
        dict(f,
             start_line=f["start_line"] - offset,
             end_line=f["end_line"] - offset,
             changed_lines=[n - offset for n in f["changed_lines"]])
        for f in kept
    ]
    changed = {n - offset for n in entry["all_changed_lines"] if start <= n <= end}
    whole = start == 1 and end == len(lines)

    return {
        "code": source if whole else "\n".join(lines[start - 1:end]),
        "changed_lines": changed,
        "functions": rebased,
        "window": None if whole else (start, end),
        "dropped_functions": [f["name"] for f in dropped],
        "note": note,
    }