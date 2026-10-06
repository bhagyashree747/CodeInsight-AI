import re
from dataclasses import dataclass, field

# Matches headers like "@@ -46,7 +46,7 @@"
HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class DiffLine:
    kind: str                  # "added" | "removed" | "context"
    content: str               # the text of the line (without the +/-)
    old_line: int | None       # line number in the OLD file (None for added lines)
    new_line: int | None       # line number in the NEW file (None for removed lines)
    anchor: int | None = None  # for removed lines: the spot in the new file where it used to be


@dataclass
class Hunk:
    """One @@ block of a diff."""
    header: str
    old_start: int
    new_start: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    """All the changes for one file."""
    filename: str
    status: str
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def added_lines(self):
        return [l.new_line for h in self.hunks for l in h.lines if l.kind == "added"]

    @property
    def removed_lines(self):
        return [l.old_line for h in self.hunks for l in h.lines if l.kind == "removed"]

    @property
    def changed_new_lines(self):
        """Lines in the NEW file that were touched: the added lines, plus the
        spot where lines were removed. Tree-sitter uses this on Day 3."""
        lines = set(self.added_lines)
        for h in self.hunks:
            for l in h.lines:
                if l.kind == "removed" and l.anchor is not None:
                    lines.add(l.anchor)
        return sorted(lines)

    def to_dict(self):
        return {
            "filename": self.filename,
            "status": self.status,
            "added_lines": self.added_lines,
            "removed_lines": self.removed_lines,
            "changed_new_lines": self.changed_new_lines,
            "hunks": [
                {
                    "header": h.header,
                    "lines": [
                        {"kind": l.kind, "old": l.old_line, "new": l.new_line, "text": l.content}
                        for l in h.lines
                    ],
                }
                for h in self.hunks
            ],
        }


def parse_patch(patch: str) -> list[Hunk]:
    """Turn raw unified-diff text into a list of Hunks with line numbers."""
    hunks = []
    current = None
    old_no = new_no = 0

    for raw in patch.splitlines():
        match = HUNK_HEADER.match(raw)
        if match:
            # New hunk: reset both counters to the starting lines from the header
            old_no = int(match.group(1))
            new_no = int(match.group(3))
            current = Hunk(header=raw, old_start=old_no, new_start=new_no)
            hunks.append(current)
            continue

        # Skip anything before the first hunk and "\ No newline at end of file"
        if current is None or raw.startswith("\\"):
            continue

        tag, text = raw[:1], raw[1:]
        if tag == "+":
            current.lines.append(DiffLine("added", text, None, new_no))
            new_no += 1
        elif tag == "-":
            current.lines.append(DiffLine("removed", text, old_no, None, anchor=new_no))
            old_no += 1
        else:
            current.lines.append(DiffLine("context", text, old_no, new_no))
            old_no += 1
            new_no += 1

    return hunks


def build_file_diffs(changed_files: list[dict]) -> list[FileDiff]:
    """Takes pr['changed_files'] from Day 1 and returns structured diffs."""
    return [
        FileDiff(
            filename=f["filename"],
            status=f["status"],
            hunks=parse_patch(f.get("patch", "")),
        )
        for f in changed_files
    ]