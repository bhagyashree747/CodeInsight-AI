import csv
import glob
import json
import os
import re

ORDER = {"none": 0, "diff": 1, "function": 2, "file": 3}
rows = []

for path in glob.glob("results/integration_pr*_*.json"):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "results" not in data:
        continue
    pr, level = data.get("pr"), data.get("level")
    totals = {"issues": 0, "kept": 0, "noise": 0, "verified": 0, "failed": 0, "retried": 0}
    for r in data["results"]:
        counts = r.get("counts") or {}
        summary = r.get("summary") or {}
        totals["issues"] += counts.get("issues_detected", 0)
        totals["kept"] += counts.get("kept", 0)
        totals["noise"] += counts.get("filtered_as_noise", 0)
        for key in ("verified", "failed", "retried"):
            totals[key] += summary.get(key, 0)

    rate_limited = api_failed = dropped = ""
    status = "no-log"
    log_path = f"logs/pr{pr}_{level}.log"
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as f:
            log = f.read()
        rate_limited = len(re.findall(r"HTTP error 429", log))
        api_failed = len(re.findall(r"failed after retry|HTTP error 413", log))
        dropped = len(re.findall(r"Dropping finding", log))
        status = "REDO" if api_failed else "ok"
    rows.append({"pr": pr, "level": level, **totals, "rate_limited": rate_limited,
                 "api_failed": api_failed, "dropped_lines": dropped, "status": status})

if not rows:
    raise SystemExit("No result files found in results/")
rows.sort(key=lambda r: (r["pr"] or 0, ORDER.get(r["level"], 9)))

print(f"{'PR':>5} {'level':<9} {'issues':>6} {'kept':>5} {'noise':>6} {'verified':>9} {'failed':>7} "
      f"{'429s':>5} {'apifail':>8} {'status':>7}")
for r in rows:
    print(f"{r['pr']:>5} {r['level']:<9} {r['issues']:>6} {r['kept']:>5} {r['noise']:>6} "
          f"{r['verified']:>9} {r['failed']:>7} {str(r['rate_limited']):>5} {str(r['api_failed']):>8} {r['status']:>7}")

with open("results/integration_summary.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
print("\nSaved results/integration_summary.csv  (status REDO = an API call failed, re-run that cell)")