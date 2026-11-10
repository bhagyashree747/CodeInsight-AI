# CodeInsight-AI

CodeInsight-AI is a Python code-review and repair prototype. It uses a configurable language-model client to identify likely defects, filters and ranks findings, generates source patches, and checks those patches with local or project-level verification.

The repository currently provides Python modules, scripts, tests, and evaluation artifacts. It does not contain a frontend or dashboard.

## Problem and motivation

Reviewing code changes requires finding substantive defects among noisy suggestions, understanding enough context to propose a fix, and checking that a change does not break existing behavior. CodeInsight-AI explores an automated workflow for these steps: structured review findings, relevance filtering, iterative patch generation, and test-based verification.

Generated findings and patches are aids for developers, not substitutes for human review. Verification executes project code and tests; it is not a security sandbox.

## Objectives

- Identify potential bugs, security issues, performance problems, and logic errors in Python source.
- Reduce review noise by filtering duplicates, non-actionable or low-confidence findings, style-only suggestions, and (when supplied) findings outside changed lines.
- Generate a minimal patch for a selected finding and explain the change.
- Feed verification failures back into bounded repair retries.
- Compare project test outcomes before and after a patch and retain structured verification reports.
- Evaluate filtering and repair behavior on a small, locally defined benchmark.

## Features

- **Structured review:** parses model responses into validated findings with a file, 1-indexed line number, category, severity, confidence, description, and fix hint.
- **Relevance filtering and scoring:** records kept and discarded findings with reasons, and ranks kept findings using confidence, severity, actionability, and changed-line location.
- **Patch generation:** returns the corrected source, unified diff, explanation, and attempt number. Function-level repair can splice a corrected function into the original file.
- **Iterative repair:** retries failed patches up to a configured attempt limit, passing verification feedback to the next generation request.
- **Local verification:** checks Python syntax, optionally runs Ruff when installed, and can execute a supplied pytest suite.
- **Project-level patch verification:** compares baseline and patched project test runs in temporary workspace copies; checks patched-workspace Python syntax and retains the complete report.
- **Mock and remote/local model clients:** mock mode works offline; OpenAI-compatible and Ollama providers are also implemented.
- **Verification metrics:** aggregates pass/failure counts and rates, and average duration from verification reports.

## End-to-end workflow

1. **Review:** `review()` sends source (or selected function context) to the configured model and validates the returned findings.
2. **Filter and rank:** `filter_findings()` removes duplicates and findings that fail the configured relevance rules, then scores the remaining findings.
3. **Generate a patch:** the repair agent asks the model for a corrected source file or function and creates a `Patch` containing the complete corrected source and diff.
4. **Verify:** local mode checks the patch with `LocalVerifier`. Project mode passes the `Patch` to `RepairVerificationAdapter`, which verifies the complete patched workspace against the project test suite.
5. **Retry:** if verification fails or is inconclusive, the error and useful report details are sent as feedback to the next patch-generation attempt. Retries stop at `max_attempts`.
6. **Accept or reject the repair result:** a repair is marked `verified` only when its configured verifier reports success. Failed repairs remain in the returned result with their attempt history; source files are not changed by the pipeline.

## Architecture

```text
run_pipeline()
  ├─ app.review        model client, prompts, finding schemas, review parsing
  ├─ app.relevance     duplicate/actionability/confidence/diff/style rules, scoring
  └─ app.repair        patch generation, repair agent, retries, verifier interface
       ├─ LocalVerifier
       └─ RepairVerificationAdapter
            └─ app.verification
                 ├─ syntax scanning
                 ├─ bounded pytest execution
                 ├─ baseline-versus-patched workspace verification
                 └─ verification metrics
```

`run_pipeline()` returns a JSON-serializable dictionary with findings, discarded findings, per-finding repair outcomes, a summary, and any pipeline errors. Project-mode repair entries also include `project_verification_reports`, one report for each verification attempt.

## Technologies

The dependencies declared in `requirements.txt` are:

| Dependency | Use |
|---|---|
| Python | Application and scripts |
| Pydantic | Validating review, patch, and verification data |
| HTTPX | Requests to OpenAI-compatible model endpoints |
| pytest | Project and local test execution |
| python-dotenv | Loading local `.env` configuration |
| matplotlib | Evaluation charts |

Ruff is used by `LocalVerifier` only when the `ruff` executable is available; it is not listed in `requirements.txt`. The Ollama Python client is imported only for the Ollama provider and is also not listed in `requirements.txt`.

## Repository structure

| Path | Purpose |
|---|---|
| `app/pipeline.py` | End-to-end review, filtering, repair, and result assembly |
| `app/review/` | LLM client implementations, prompts, finding schemas, and review parsing |
| `app/relevance/` | Finding filters, relevance scores, and their configuration |
| `app/repair/` | Patch schemas and generation, local verifier, repair agent, and retry orchestration |
| `app/verification/` | Syntax scanner, pytest runner, project patch verifier, adapter, and metrics |
| `evaluation/benchmark.py` | Small benchmark of buggy and clean Python snippets |
| `evaluation/metrics.py` | Evaluation precision, recall, false-positive, and repair metrics |
| `evaluation/run_experiments.py` | Command-line evaluation runner and CSV/chart generation |
| `tests/` | Unit and integration tests for review, filtering, repair, verification, demos, and evaluation |
| `docs/review_repair_interface.md` | Review and repair interface details |
| `results/` | Example output JSON, CSV snapshots, charts, and evaluation notes |
| `run_demo.py` | Review and relevance-filter demo |
| `run_demo_patch.py` | Review, patch generation, diff display, and temporary patch-file demo |
| `run_demo_repair.py` | Local verification and retry-loop demo |
| `run_pipeline_demo.py` | End-to-end pipeline demo; writes `results/demo_output.json` |
| `run_pr_integration.py` | PR-review wrapper and mock-file smoke test |
| `.env.example` | Example model-provider configuration |
| `requirements.txt` | Python dependency list |

Run commands from the repository root; the project does not define a package installer or console entry point.

## Prerequisites

- Python **3.10 or later**. The source uses Python 3.10 union type syntax.
- Git.
- Internet access and a valid provider configuration only when using a hosted model. Mock mode needs no API key or network access.
- For the Ollama provider, an available Ollama service and the separately installed `ollama` Python package.

## Installation and setup

### Windows PowerShell

```powershell
git clone https://github.com/bhagyashree747/CodeInsight-AI.git
Set-Location CodeInsight-AI

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Copy-Item .env.example .env
```

If PowerShell blocks virtual-environment activation, either adjust the execution policy for your user according to your organization's guidance or invoke the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run_demo.py
```

### General Python environments

```bash
git clone https://github.com/bhagyashree747/CodeInsight-AI.git
cd CodeInsight-AI

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
```

On systems where the interpreter is named `python` rather than `python3`, use that command to create the environment. `.env` is ignored by Git; keep credentials there or in environment variables, and do not commit secrets.

## Model-provider configuration

The application defaults to `mock` when `LLM_PROVIDER` is unset. `get_client()` also reads `.env` when `python-dotenv` is installed. The example file contains placeholder values only; replace them locally as appropriate.

| `LLM_PROVIDER` | Behavior | Configuration |
|---|---|---|
| `mock` | Offline canned responses for development and tests. These responses are synthetic and do not measure real model capability. | No key required. |
| `openai_compat` | Sends requests through HTTPX to an OpenAI-compatible chat-completions endpoint. | Set `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL`. `.env.example` includes example URL/model comments for Gemini-compatible and Groq endpoints. |
| `ollama` | Uses the Ollama Python client to call a local Ollama service. | Install the `ollama` Python package separately, make the service/model available, and set `LLM_MODEL`. `LLM_BASE_URL` can specify the Ollama host. The example model is `qwen2.5-coder:7b`. |

`LLM_TIMEOUT` is provided in `.env.example` as the OpenAI-compatible request timeout setting. The Ollama client uses its own constructor timeout default in the current implementation.

Example local configuration for offline use:

```dotenv
LLM_PROVIDER=mock
```

To use a hosted provider, set the API key only in your local `.env` or process environment. Never paste a real key into README files, source control, or issue reports.

## Demo scripts

Run any demo from the repository root after installing the declared dependencies. By default, demos use the mock provider unless configuration selects another provider.

### Review and filter

```powershell
python run_demo.py
```

Runs four review/filter examples (three buggy snippets and one clean snippet) and prints kept and discarded findings.

### Patch generation

```powershell
python run_demo_patch.py
```

Reviews three buggy snippets, generates a patch for the top finding, displays the diff and explanation, and writes the candidate to a temporary file. The script removes that temporary file after displaying it; it does not overwrite the original snippet.

### Repair and local verification

```powershell
python run_demo_repair.py
```

With mock mode, runs three scripted retry scenarios, including an intentionally failing test contract. With another configured provider, it runs the snippets through the real review/repair calls and local verification. This demo uses `LocalVerifier`, not project-workspace verification.

### Full pipeline

```powershell
python run_pipeline_demo.py
```

Runs three snippets through review, filtering, repair, and local verification. It writes the resulting JSON to `results/demo_output.json`, replacing that output file.

### PR integration wrapper

```powershell
python run_pr_integration.py
```

Runs the script's built-in mock-file smoke test. The wrapper also accepts a list of already extracted file records through `run_pr_review_and_repair()`. Passing a PR URL requires `app.code_engine.interface.get_review_inputs`; that module is not present in this checkout, so URL-based extraction is not available here. The wrapper defaults to `LocalVerifier` unless a verifier is supplied.

## Project-level patch verification

`run_pipeline()` can verify each generated repair against a project's test suite instead of using `LocalVerifier`.

- **`project_workspace`** is the root directory of the existing project.
- **`project_file`** selects the existing Python source file within that workspace to replace in the temporary patched copy. It can be absolute or workspace-relative and must resolve to a `.py` file within the workspace. If omitted, `file` is used as the path; `file` continues to serve as the logical review filename.
- **Baseline and patched workspaces** are copied to separate temporary directories. The baseline suite runs against one copy. The generated `Patch.fixed_code` is written at the corresponding relative path in the other copy.
- **Syntax validation** scans Python files in the patched copy before the patched test suite is run. Patched tests are skipped if syntax validation fails.
- **Test execution** uses pytest against each copied project workspace, so pytest discovers the project suite rather than only testing the patched source file. Each run has the configured timeout.
- **Comparison and outcomes:** a passing baseline with failing patched tests is a regression. If baseline tests fail or either run times out/cannot complete, the comparison is not treated as a successful verification. Inconclusive or failed verification is returned to the retry loop as feedback.
- **Reports:** each attempt retains its complete project report in the repair result's `project_verification_reports` list. Reports contain syntax and test checks, baseline results, comparison assessment, durations, and failed checks.
- **Original files:** verification writes only to temporary copies and cleans those temporary directories after the run. The pipeline does not apply the generated patch to the original workspace.

Example:

```python
from pathlib import Path

from app.pipeline import run_pipeline

workspace = Path(r"C:\path\to\your\project")
source = workspace / "src" / "module.py"
source_code = source.read_text(encoding="utf-8")

result = run_pipeline(
    code=source_code,
    file="src/module.py",
    project_workspace=workspace,
    project_file="src/module.py",
    project_test_timeout=120,
    max_attempts=3,
)

print(result["summary"])
for repair in result["repairs"]:
    print(repair["status"], repair.get("project_verification_reports", []))
```

**Trust boundary:** pytest imports and executes code from the project. Temporary copies protect the original workspace from patch writes, but they do not isolate execution from the host. Run verification only on code and test suites you trust.

## Testing

Run the complete test suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Or, in an activated general Python environment:

```bash
python -m pytest -q
```

Tests use temporary fixtures and mocked model responses for offline coverage; running the suite does not require an API key or live LLM.

## Evaluation methodology and available results

The benchmark in `evaluation/benchmark.py` contains **12 buggy snippets** with known bug lines, hand-written fixes, and associated test code, plus **3 clean snippets** used to measure false positives. `evaluation/run_experiments.py` runs three comparisons:

1. **Filter on/off:** per-bug precision and recall, where a finding within ±2 lines of the known bug line counts as a hit; clean snippets are used for false-positive rate.
2. **One-shot versus retrying repair:** maximum attempt budgets of one and three; repair success is based on the bundled test code passing. API errors are tracked separately in repair metrics.
3. **Context-level repair:** records results for the configured `diff`, `function`, and `file` context cases.

Run a short mock evaluation:

```powershell
python evaluation/run_experiments.py --limit 3
```

`--limit 3` means the first three buggy snippets plus all three clean snippets. The runner also accepts `--provider`, `--sleep`, and `--out`; see:

```powershell
python evaluation/run_experiments.py --help
```

The runner writes CSVs, charts, and an evaluation README to the selected output directory (default `results/`). The checked-in evaluation CSV snapshots identify their provider as `mock`; they are synthetic canned-response outputs, not evidence of real-provider performance. No general accuracy or success-rate claim is made here. Use a configured non-mock provider and report its provider/model and run settings when producing meaningful model evaluations.

## Limitations

- Model findings and generated patches can be incorrect, incomplete, or provider-dependent; inspect changes before use.
- Mock responses are canned and are not representative of a live model.
- Project verification runs pytest code without a security boundary and may be expensive for large projects.
- Project-level syntax scanning is for Python files, and project tests are run with pytest.
- `LocalVerifier` runs Ruff only if it is installed; Ruff is not included in the declared dependencies.
- Ollama support requires an extra Python package not listed in `requirements.txt`.
- PR URL ingestion depends on a code-engine module that is absent from this checkout; the provided PR wrapper can still process already extracted file records.
- No frontend, dashboard, or automatic pull-request submission workflow is implemented in this repository.

## Future enhancements

Potential future work, not claimed as implemented:

- Add and integrate a repository/PR code-extraction component for URL-based review.
- Add broader language support and language-aware verification.
- Improve context extraction and test selection for large repositories.
- Add reproducible evaluation reports using real providers, with explicit model versions and run configuration.
- Consider additional review UX, such as a frontend, only if it is separately implemented.

## Team contributions

Names were not available in the repository documentation; replace these placeholders with the contributors' preferred names.

| Contributor | Responsibility |
|---|---|
| `[Teammate 1 name]` | AI patch generation, repair agent, and retry workflow |
| `[Teammate 2 name]` | Code intelligence / code-engine integration |
| `[Teammate 3 name]` | Automated verification, test execution, verification metrics, and repair-workflow integration |

## License

No license has been specified in this repository. All rights and permissions should be confirmed with the project maintainers before reuse or redistribution.
