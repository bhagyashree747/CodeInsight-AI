import argparse
import json
import os

from app.code_engine.base_inputs import build_base_inputs, build_hint, is_test_file
from app.github.checkout import checkout_pr_base
from app.github.client import GitHubClient
from app.github.pull_request import fetch_file_at_head, fetch_pull_request
from app.integration.verifier import FailToPassVerifier, Workspace, check_import, run_pytest


def load_test_ids(pr_number, path="docs/eval_prs.json"):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for item in data["prs"]:
        if item["pr"] == pr_number:
            return item["fail_to_pass"]
    raise SystemExit(f"PR {pr_number} is not in {path}")


def prepare(pr_url):
    client = GitHubClient()
    pr = fetch_pull_request(client, pr_url)
    test_ids = load_test_ids(pr["pr_number"])
    base_folder = checkout_pr_base(pr)

    test_files = {}
    for f in pr["changed_files"]:
        if is_test_file(f["filename"]) and f["status"] != "removed":
            text = fetch_file_at_head(client, pr, f["filename"])
            if text is not None:
                test_files[f["filename"]] = text

    entries, sources = build_base_inputs(pr, client)
    workspace = Workspace(base_folder, test_files)
    return client, pr, test_ids, entries, sources, workspace


def tail(text, n=15):
    return "\n".join(text.splitlines()[-n:])


def cmd_check(args):
    """No AI. Baseline (base code + PR tests) must FAIL, then the human fix must make it PASS."""
    client, pr, test_ids, entries, sources, ws = prepare(args.pr_url)
    try:
        print(f"PR #{pr['pr_number']}: {pr['title']}")
        print("AI would get these files:")
        for e in entries:
            if e["skipped"]:
                print(f"   skipped  {e['file']}  ({e['skip_reason']})")
            else:
                names = ", ".join(f["name"] for f in e["functions"]) or "(none)"
                print(f"   {e['file']} | functions: {names} | text {len(e['text'])} chars | truncated={e['truncated']}")
        print("Tests:", *test_ids, sep="\n   ")

        problem = check_import(args.python, ws.path, args.import_name)
        if problem:
            print("\nSETUP PROBLEM:", problem)
            return

        code, out, secs = run_pytest(args.python, ws.path, test_ids, args.timeout)
        print(f"\nBASELINE (base code + PR tests): exit {code} in {secs}s -> "
              + ("FAILS as expected" if code != 0 else "PASSES (unexpected!)"))

        applied = []
        for f in pr["changed_files"]:
            name = f["filename"]
            if name.endswith(".py") and not is_test_file(name) and f["status"] != "removed":
                text = fetch_file_at_head(client, pr, name)
                if text is not None:
                    ws.write(name, text)
                    applied.append(name)
        code2, out2, secs2 = run_pytest(args.python, ws.path, test_ids, args.timeout)
        print(f"WITH THE HUMAN FIX ({', '.join(applied)}): exit {code2} in {secs2}s -> "
              + ("PASSES as expected" if code2 == 0 else "FAILS (unexpected!)"))

        if code != 0 and code2 == 0:
            print("\nRESULT: OK. The workspace, tests and verifier setup work for this PR.")
        else:
            print("\nRESULT: something is off. Last output:\n" + tail(out2 if code2 != 0 else out))
    finally:
        if not args.keep:
            ws.cleanup()


def cmd_run(args):
    try:
        from app.pipeline import run_pipeline
    except ImportError:
        raise SystemExit("Cannot import app.pipeline. Merge Member 1's branch "
                         "(feature/member1-ai-repair) into your working branch first.")

    client, pr, test_ids, entries, sources, ws = prepare(args.pr_url)
    try:
        problem = check_import(args.python, ws.path, args.import_name)
        if problem:
            raise SystemExit("SETUP PROBLEM: " + problem)

        os.makedirs("results", exist_ok=True)
        outputs = []
        for e in entries:
            if e["skipped"] or (args.file and e["file"] != args.file):
                continue
            source = sources[e["file"]]
            window = (e["start_line"], e["end_line"]) if e["truncated"] else None
            if e["truncated"]:
                print(f"NOTE: {e['file']} is only sent as a window (lines {window[0]}-{window[1]}).")

            verifier = FailToPassVerifier(ws, args.python, test_ids, e["file"], source,
                                          window=window, timeout=args.timeout,
                                          import_name=args.import_name)
            hint = build_hint(args.level, source, e["all_changed_lines"])
            result = run_pipeline(
                code=e["text"],
                file=e["file"],
                changed_lines=set(e["changed_lines"]),
                functions=e["functions"],
                verifier=verifier,
                max_attempts=args.attempts,
                context_level=None if args.level == "none" else args.level,
                extra_context=hint,
            )
            outputs.append(result)
            print(f"\n{e['file']}: {result.get('summary')}")

        out_path = f"results/integration_pr{pr['pr_number']}_{args.level}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(outputs, f, indent=2, default=str)
        print("\nSaved", out_path)
    finally:
        if not args.keep:
            ws.cleanup()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("check", "run"):
        s = sub.add_parser(name)
        s.add_argument("pr_url")
        s.add_argument("--python", required=True, help="python.exe of the test environment")
        s.add_argument("--timeout", type=int, default=300)
        s.add_argument("--import-name", default="requests")
        s.add_argument("--keep", action="store_true", help="keep the temp workspace")
        if name == "run":
            s.add_argument("--level", choices=["none", "diff", "function", "file"], default="none")
            s.add_argument("--attempts", type=int, default=3)
            s.add_argument("--file", help="only this file")
    args = parser.parse_args()
    {"check": cmd_check, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()