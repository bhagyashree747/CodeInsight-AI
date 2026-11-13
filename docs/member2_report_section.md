## Code Intelligence and Evaluation (Member 2)

### Module
Given a GitHub pull request URL, the code engine fetches the changed files and diffs (GitHub API), parses the diffs
into hunks with old and new line numbers, and uses Tree-sitter to find the function and class that contain each
changed line. It builds context at three levels (diff only, function, file; files over the cap are trimmed to
windows around the changes) and exposes a Python interface (`get_review_inputs`) that returns one record per changed
file: text, changed lines, language and the changed functions. A second mode returns the code as it was before the
fix, with the changed lines and functions mapped to that version, which is what the repair evaluation uses.

### Evaluation set
13 bug-fix pull requests from psf/requests (auth, adapters, sessions, cookies, utils, models). Each was verified
fail-to-pass on Windows with Python 3.13: with the PR's tests added to the base commit at least one test fails, and
adding the PR's fix makes it pass, with no new failures in the changed test files. The changed source functions are
78 to 5,131 characters. One Windows-only baseline failure (a TLS certificate symlink test) fails before and after
in every PR and is ignored.

### Context sizes
Whole-PR contexts for the 13 PRs, in characters: diff averages 2,072 (max 5,488); function averages 5,361 (max
11,175); file averages 18,841 (max 25,153), with each file capped at 12,000 characters. Text actually sent to the
model in the experiment (5 PRs): the changed function (`code`) is 774 to 4,501 characters (average 2,535); extra
context is none (0), changed region (224 to 794, average 369) or file excerpt (6,140 to 7,262, average 6,716).
The excerpt is capped at 8,000 characters because the free API tier rejected larger requests.

### Experiment
For 5 PRs (7332, 7205, 7309, 7502, 7553) the model (openai/gpt-oss-120b on the Groq free tier) receives the pre-fix
changed function and the lines the human fix touched, with no bug report and no tests. The human patch is never
shown. A repair counts as verified if it passes a syntax check and the PR's fail-to-pass tests, run in a temporary
copy of the base checkout, within 3 attempts; failures are fed back to the model between attempts. Three
conditions: (a) function only, (b) plus the touched lines with 3 lines of surroundings (no line numbers), (c) plus
a file excerpt. One run per cell.

### Results
| PR | Changed function | Function only | + changed region | + file excerpt |
|---|---|---|---|---|
| 7332 | HTTPDigestAuth.build_digest_header | other issue | other issues | other issues |
| 7205 | get_netrc_auth | other issue | nothing | nothing |
| 7309 | _parse_content_type_header | nothing | nothing | verified (2 attempts) |
| 7502 | RequestEncodingMixin._encode_files | verified (1 attempt) | verified (2 attempts) | other issue |
| 7553 | HTTPAdapter.send | verified (2 attempts) | nothing | nothing |
| **Verified** | | **2/5** | **1/5** | **1/5** |

"Other issue" means the model reported a problem elsewhere in the function, and the relevance filter discarded it
because it was outside the changed lines. Of the 15 runs, 4 produced a verified repair, 5 only flagged other issues
and 6 found nothing. Three of the four verified repairs needed a second attempt, so the failure feedback mattered.
PR 7332 was never solved. With one run per cell and five PRs, the differences between the three conditions are not
statistically meaningful. [AI patch vs human fix: 7502 ___, 7553 ___ (equivalent / different but valid / partial)]

### Limitations
1. One repository (psf/requests), Windows, Python 3.13.
2. Function detection is Python-only; other languages get plain windows.
3. The model is told which lines changed, so this measures repair, not bug localization.
4. A verified repair passed only the targeted tests; regressions elsewhere were not checked (future work: the
   project-level verification in Member 3's module).
5. The free-tier limit (8,000 tokens per minute) forced an 8,000-character cap on the file excerpt and caused retries.
6. The model is non-deterministic and each cell was run once.
7. Five of the 13 PRs touch cookies.py, and two pairs (7332/7296, 7346/7303) change the same function.
8. For large files the text sent is a window around the changed functions, not the whole file.