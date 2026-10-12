# CodeInsight: Code Context Interface (Member 2 -> Member 1 / Member 3)

## How to call it

```python
from app.code_engine.interface import get_context, get_all_levels

# One level (Member 1: put ctx["text"] in the LLM prompt)
ctx = get_context("https://github.com/psf/requests/pull/6700", level="function")

# All three levels at once (Member 3: for the evaluation comparison)
results = get_all_levels("https://github.com/psf/requests/pull/6700")
# -> {"diff": ctx, "function": ctx, "file": ctx}
```

Run from the project root. Needs `GITHUB_TOKEN` in `.env`.

## Levels

| level | what the AI sees |
|---|---|
| `diff` | Only the raw patch (changed lines, with the @@ headers) |
| `function` | The whole function (plus class name) around each change. Python only. Non-Python files get a small window of lines instead. |
| `file` | The whole file. Files over 40,000 characters are trimmed to a window around the changes (`file_trimmed`). |

Code in `function` and `file` levels has line numbers in front (`2724: code here`), so the AI can point at exact lines.

## What you get back

```json
{
  "repository": "psf/requests",
  "pr_number": 6700,
  "title": "Use an invalid URI that will not cause httpbin to throw 500",
  "level": "function",
  "text": "### File: tests/test_requests.py (modified)\n# function test_redirecting_to_bad_url ...",
  "skipped_files": [],
  "files": [
    {
      "filename": "tests/test_requests.py",
      "status": "modified",
      "level": "function",
      "requested_level": "function",
      "note": null,
      "changed_lines": [2724],
      "text": "### File: tests/test_requests.py (modified)\n...",
      "units": [
        {
          "kind": "function",
          "function": "test_redirecting_to_bad_url",
          "class": "TestPreparingURLs",
          "start_line": 2724,
          "end_line": 2727,
          "changed_lines": [2724],
          "text": "# function test_redirecting_to_bad_url (class TestPreparingURLs), lines 2724-2727, changed: [2724]\n2724: ..."
        }
      ]
    }
  ]
}
```

(`text` values are shortened here.)

## Fields

| field | meaning |
|---|---|
| `text` (top level) | Everything for the PR, ready to paste into a prompt |
| `files[].text` | The same, for one file |
| `files[].level` | Level actually used. Can differ from `requested_level`. |
| `files[].note` | Why it fell back to `diff` (deleted file, file couldn't be fetched, no changed lines). `null` if no problem. |
| `files[].changed_lines` | Changed line numbers in the NEW version of the file |
| `units[].kind` | `function`, `window` (lines around a change), `file`, `file_trimmed`, or `diff` |
| `skipped_files` | Files left out because the PR had more than 30 files (`max_files`) |

## Things to know
- Deleted files, binary files, and pure renames always come back at `diff` level, with a `note`.
- A function-level change at the top of a file (imports, constants) comes back as a `window` unit, not a function.
- Errors for one file never crash the whole PR. Check `note` on each file.