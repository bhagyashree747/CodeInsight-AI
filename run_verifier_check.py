import argparse

from app.github.pull_request import fetch_file_at_head
from app.integration.verifier import FailToPassVerifier
from run_integration import prepare


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pr_url")
    parser.add_argument("--python", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    client, pr, test_ids, entries, sources, ws = prepare(args.pr_url)
    try:
        for e in entries:
            if e["skipped"]:
                continue
            name = e["file"]
            window = (e["start_line"], e["end_line"]) if e["truncated"] else None
            verifier = FailToPassVerifier(ws, args.python, test_ids, name, sources[name],
                                          window=window, timeout=args.timeout)
            fixed = fetch_file_at_head(client, pr, name)

            base = verifier.verify(sources[name])
            human = verifier.verify(fixed)
            broken = verifier.verify(sources[name] + "\ndef broken(:\n")

            print(f"\n{name}   (result class: {type(base).__name__})")
            print(f"  base code    : passed={base.passed} stage={base.stage}      (expected False, tests)")
            print(f"  human fix    : passed={human.passed} stage={human.stage}       (expected True, none)")
            print(f"  syntax error : passed={broken.passed} stage={broken.stage}      (expected False, syntax)")
    finally:
        ws.cleanup()


if __name__ == "__main__":
    main()