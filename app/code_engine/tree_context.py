from app.code_engine.parser import parse_python

FUNCTION_TYPES = {"function_definition"}
CLASS_TYPES = {"class_definition"}


def _walk(node):
    """Visit every node in the tree, parents before children."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


def _with_decorators(node):
    """If a function/class has @decorators, include them in its range."""
    parent = node.parent
    if parent is not None and parent.type == "decorated_definition":
        return parent
    return node


def _describe(node, lines):
    """Turn a tree node into a simple dict (lines are 1-based)."""
    name_node = node.child_by_field_name("name")
    start = node.start_point[0]
    end = node.end_point[0]
    return {
        "name": name_node.text.decode("utf8") if name_node else "?",
        "start_line": start + 1,
        "end_line": end + 1,
        "code": "\n".join(lines[start:end + 1]),
    }


def find_enclosing(tree, line, lines):
    """For a 1-based line number, return (function, class) it sits inside.
    Either can be None (e.g. a line at module level)."""
    row = line - 1
    func = cls = None
    for node in _walk(tree.root_node):
        if node.type not in FUNCTION_TYPES | CLASS_TYPES:
            continue
        span = _with_decorators(node)
        if span.start_point[0] <= row <= span.end_point[0]:
            # parents come before children, so the last match is the innermost
            if node.type in FUNCTION_TYPES:
                func = _describe(span if span is not node else node, lines)
                func["name"] = _describe(node, lines)["name"]
            else:
                cls = _describe(span if span is not node else node, lines)
                cls["name"] = _describe(node, lines)["name"]
    return func, cls


def get_change_contexts(source, changed_lines):
    """Main function. Input: full file text + list of changed line numbers.
    Output: one entry per changed function (changes in the same function are grouped)."""
    tree = parse_python(source)
    lines = source.splitlines()
    groups = {}

    for line in changed_lines:
        func, cls = find_enclosing(tree, line, lines)
        key = (func["start_line"], func["name"]) if func else ("module", 0)
        if key not in groups:
            groups[key] = {"function": func, "class": cls, "changed_lines": []}
        groups[key]["changed_lines"].append(line)

    return list(groups.values())