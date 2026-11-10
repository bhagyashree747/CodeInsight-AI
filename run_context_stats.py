import csv

from app.code_engine.interface import get_all_levels

OUT = "docs/context_sizes.csv"


def load_urls(path="docs/eval_prs.txt"):
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.startswith("http")]


def main():
    rows = []
    for url in load_urls():
        print("Processing", url)
        try:
            results = get_all_levels(url)
        except Exception as error:
            print("  ERROR:", error)
            continue
        for level, ctx in results.items():
            chars = len(ctx["text"])
            rows.append({
                "pr": ctx["pr_number"],
                "title": ctx["title"],
                "level": level,
                "chars": chars,
                "approx_tokens": chars // 4,
                "files": len(ctx["files"]),
                "fell_back_to_diff": sum(1 for f in ctx["files"] if f["level"] != f["requested_level"]),
            })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved {len(rows)} rows to {OUT}\n")
    for level in ("diff", "function", "file"):
        sizes = [r["chars"] for r in rows if r["level"] == level]
        if sizes:
            print(f"{level:9} average {sum(sizes) // len(sizes):>6} chars | max {max(sizes):>6} | PRs: {len(sizes)}")


if __name__ == "__main__":
    main()