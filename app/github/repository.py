import re
from dataclasses import dataclass

PR_URL_PATTERN = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)"
)


@dataclass
class PRReference:
    owner: str
    repo: str
    number: int

    @property
    def full_name(self):
        return f"{self.owner}/{self.repo}"


def parse_pr_url(url):
    """'https://github.com/apache/kafka/pull/42' -> PRReference"""
    match = PR_URL_PATTERN.search(url.strip())
    if not match:
        raise ValueError(
            "Invalid PR URL. Expected: https://github.com/<owner>/<repo>/pull/<number>"
        )
    return PRReference(
        owner=match.group("owner"),
        repo=match.group("repo"),
        number=int(match.group("number")),
    )


def get_repository_info(client, owner, repo):
    """Basic repo details (we'll use language / default branch later)."""
    data = client.get(f"/repos/{owner}/{repo}")
    return {
        "full_name": data["full_name"],
        "default_branch": data["default_branch"],
        "language": data["language"],
    }