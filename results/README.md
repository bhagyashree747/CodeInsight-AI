# CodeInsight AI — Evaluation Results

## How to run

```bash
# Quick test with mock provider (first 3 snippets):
python evaluation/run_experiments.py --limit 3

# Full benchmark with a real provider:
python evaluation/run_experiments.py --provider openai_compat --sleep 3

# All options:
python evaluation/run_experiments.py --help
```

## Output files

| File | Description |
|---|---|
| `experiment_filter.csv` | Per-snippet filter precision/recall (ON vs OFF) |
| `experiment_repair.csv` | Per-snippet repair success (one-shot vs 3-attempt) |
| `filter_chart.png` | Bar chart: filter ON vs OFF metrics |
| `repair_chart.png` | Bar chart: repair one-shot vs self-correcting |

## Important: mock provider

When `--provider mock` (or `LLM_PROVIDER=mock`) is used, results are **synthetic
canned responses** and **do NOT reflect real LLM performance**. Mock mode is only
useful for testing the evaluation code itself (CI, offline development).

Use a real provider (`openai_compat` with `LLM_BASE_URL`/`LLM_API_KEY` set) for
meaningful benchmarks.

## Metrics

- **Precision**: fraction of kept findings that point at the known bug line (±2 lines).
- **Recall**: 1 if the known bug line was found in kept findings, else 0.
- **False Positive Rate**: fraction of clean snippets with >=1 kept finding.
- **Repair Success Rate**: fraction of snippets where the patched code passes its
  `test_code` suite (API errors are excluded from denominator).
