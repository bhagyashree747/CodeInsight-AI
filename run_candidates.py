import sys

from app.github.client import GitHubClient
from app.github.pull_request import fetch_pull_request, fetch_file_at_head

MAX_CHARS = 12000


def is_test(path):
    return "test" in path.lower()


def check(client, url):
    pr = fetch_pull_request(client, url)
    files = pr["changed_files"]
    py = [f for f in files if f["filename"].endswith(".py")]
    src = [f for f in py if not is_test(f["filename"])]
    tests = [f for f in py if is_test(f["filename"])]

    biggest = 0
    for f in src:
        if f["status"] != "removed":
            text = fetch_file_at_head(client, pr, f["filename"])
            if text:
                biggest = max(biggest, len(text))

    ok = bool(src) and bool(tests) and len(files) <= 5
    print(f"\n{'GOOD' if ok else 'skip'}  {pr['repository']} #{pr['pr_number']}: {pr['title']}")
    print(f"      files: {len(files)} | source .py: {len(src)} | test .py: {len(tests)} "
          f"| non-.py: {len(files) - len(py)}")
    print(f"      biggest source file: {biggest} chars"
          + ("  (over 12,000: review only, no auto-repair)" if biggest > MAX_CHARS else ""))


def load_urls(args):
    if len(args) == 1 and args[0].endswith(".txt"):
        with open(args[0], encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return args


if __name__ == "__main__":
    urls = load_urls(sys.argv[1:])
    if not urls:
        print("Usage: python run_candidates.py <url> <url> ...   or   python run_candidates.py candidates.txt")
        sys.exit(1)
    client = GitHubClient()
    for url in urls:
        try:
            check(client, url)
        except Exception as error:
            print(f"\nERROR {url}: {error}")