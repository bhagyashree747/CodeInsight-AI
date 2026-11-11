import argparse
import json
import os

from app.code_engine.base_inputs import build_base_inputs, build_hint, is_test_file
from app.code_engine.pipeline_inputs import make_pipeline_inputs
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


def prepare(pr_url, need_workspace=True):
    client = GitHubClient()
    pr = fetch_pull_request(client, pr_url)
    test_ids = load_test_ids(pr["pr_number"])
    entries, sources = build_base_inputs(pr, client)

    ws = None
    if need_workspace:
        base_folder = checkout_pr_base(pr)
        test_files = {}
        for f in pr["changed_files"]:
            if is_test_file(f["filename"]) and f["status"] != "removed":
                text = fetch_file_at_head(client, pr, f["filename"])
                if text is not None:
                    test_files[f["filename"]] = text
        ws = Workspace(base_folder, test_files)
    return client, pr, test_ids, entries, sources, ws


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


def cmd_inputs(args):
    """Show exactly what would be sent to run_pipeline. No AI, no tests, no tokens spent."""
    client, pr, test_ids, entries, sources, _ = prepare(args.pr_url, need_workspace=False)
    print(f"PR #{pr['pr_number']}: {pr['title']}   (level={args.level}, code-scope={args.code_scope})")
    for e in entries:
        if e["skipped"]:
            print(f"\nskipped  {e['file']}  ({e['skip_reason']})")
            continue
        source = sources[e["file"]]
        inputs = make_pipeline_inputs(e, source, args.code_scope)
        hint = build_hint(args.level, source, e["all_changed_lines"])
        print(f"\n{e['file']}")
        print(f"  code: {len(inputs['code'])} chars, window in the file = {inputs['window']}")
        print(f"  changed_lines (relative to code): {sorted(inputs['changed_lines'])}")
        code_lines = inputs["code"].splitlines()
        for f in inputs["functions"]:
            same = "\n".join(code_lines[f["start_line"] - 1:f["end_line"]]) == f["text"]
            print(f"  function {f['name']}: relative lines {f['start_line']}-{f['end_line']}, "
                  f"{len(f['text'])} chars, matches code: {'OK' if same else 'MISMATCH'}")
        if inputs["dropped_functions"]:
            print(f"  dropped (outside code): {inputs['dropped_functions']}")
        if inputs["note"]:
            print(f"  note: {inputs['note']}")
        print(f"  extra_context: {len(hint) if hint else 0} chars")


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
            inputs = make_pipeline_inputs(e, source, args.code_scope)
            if inputs["window"]:
                print(f"NOTE: {e['file']}: code is lines {inputs['window'][0]}-{inputs['window'][1]} "
                      "of the file; numbers sent to the pipeline are relative to it.")
            if inputs["dropped_functions"]:
                print(f"NOTE: dropped functions outside code: {inputs['dropped_functions']}")
            if not inputs["functions"]:
                print(f"SKIP {e['file']}: no changed function inside the code to repair.")
                continue

            verifier = FailToPassVerifier(ws, args.python, test_ids, e["file"], source,
                                          window=inputs["window"], timeout=args.timeout,
                                          import_name=args.import_name)
            hint = build_hint(args.level, source, e["all_changed_lines"])
            result = run_pipeline(
                code=inputs["code"],
                file=e["file"],
                changed_lines=inputs["changed_lines"],
                functions=inputs["functions"],
                verifier=verifier,
                max_attempts=args.attempts,
                context_level=None if args.level == "none" else args.level,
                extra_context=hint,
                test_code=None,
            )
            outputs.append(result)
            print(f"\n{e['file']}: {result.get('summary')}")

        out_path = f"results/integration_pr{pr['pr_number']}_{args.level}_{args.code_scope}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"pr": pr["pr_number"], "level": args.level,
                       "code_scope": args.code_scope, "results": outputs},
                      f, indent=2, default=str)
        print("\nSaved", out_path)
    finally:
        if not args.keep:
            ws.cleanup()


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(s, with_python=True):
        s.add_argument("pr_url")
        if with_python:
            s.add_argument("--python", required=True, help="python.exe of the test environment")
            s.add_argument("--timeout", type=int, default=300)
            s.add_argument("--import-name", default="requests")
            s.add_argument("--keep", action="store_true", help="keep the temp workspace")

    check = sub.add_parser("check")
    run = sub.add_parser("run")
    inputs = sub.add_parser("inputs")
    common(check)
    common(run)
    common(inputs, with_python=False)
    for s in (run, inputs):
        s.add_argument("--level", choices=["none", "diff", "function", "file"], default="none")
        s.add_argument("--code-scope", choices=["window", "function"], default="window")
    run.add_argument("--attempts", type=int, default=3)
    run.add_argument("--file", help="only this file")

    args = parser.parse_args()
    {"check": cmd_check, "run": cmd_run, "inputs": cmd_inputs}[args.cmd](args)


if __name__ == "__main__":
    main()