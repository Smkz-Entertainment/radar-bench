"""Allowlisted canonical GitHub URL parsing."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from radar_bench.errors import SecurityError

ALLOWED_HOSTS = {"github.com", "api.github.com"}


@dataclass(frozen=True)
class GitHubResource:
    owner: str
    repo: str
    kind: str
    number: int | None = None
    suffix: str | None = None

    @property
    def identity(self) -> str:
        tail = f"/{self.number}" if self.number is not None else ""
        return f"github:{self.owner}/{self.repo}:{self.kind}{tail}"


def parse_github_url(value: str) -> GitHubResource:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise SecurityError("only https://github.com public URLs are accepted")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise SecurityError("GitHub URL lacks owner/repository")
    owner, repo = parts[0], parts[1]
    if any(ch in owner + repo for ch in "\\\x00") or repo.endswith(".git"):
        repo = repo[:-4]
    if len(parts) >= 4 and parts[2] in {"issues", "pull", "commit", "releases"}:
        kind = {
            "pull": "pull_request",
            "issues": "issue",
            "commit": "commit",
            "releases": "release",
        }[parts[2]]
        number = (
            None
            if kind in {"release", "commit"}
            else int(parts[3])
            if parts[3].isdigit()
            else None
        )
        if kind not in {"release", "commit"} and number is None:
            raise SecurityError("resource number is invalid")
        suffix = (
            parts[3]
            if kind == "commit"
            else parts[4]
            if kind == "release" and len(parts) >= 5 and parts[3] == "tag"
            else parsed.fragment or None
        )
        if parsed.fragment and parsed.fragment.startswith("issuecomment-"):
            kind, suffix = (
                "issue_comment",
                parsed.fragment.removeprefix("issuecomment-"),
            )
        elif parsed.fragment and parsed.fragment.startswith(("discussion_r", "review")):
            kind, suffix = (
                "review_comment",
                parsed.fragment.removeprefix("discussion_r").removeprefix("review"),
            )
        return GitHubResource(owner, repo, kind, number, suffix)
    if (
        len(parts) >= 4
        and parts[2] == "actions"
        and parts[3] == "runs"
        and len(parts) >= 5
        and parts[4].isdigit()
    ):
        return GitHubResource(owner, repo, "workflow_run", int(parts[4]))
    if len(parts) >= 4 and parts[2] == "tree":
        return GitHubResource(owner, repo, "tag", None, "/".join(parts[3:]))
    raise SecurityError("unsupported or non-canonical GitHub URL")


def api_url(resource: GitHubResource) -> str:
    base = f"https://api.github.com/repos/{resource.owner}/{resource.repo}"
    if resource.kind == "issue":
        return f"{base}/issues/{resource.number}"
    if resource.kind == "pull_request":
        return f"{base}/pulls/{resource.number}"
    if resource.kind == "commit":
        return f"{base}/commits/{resource.suffix}"
    if resource.kind == "issue_comment":
        return f"{base}/issues/{resource.number}/comments/{resource.suffix}"
    if resource.kind == "review_comment":
        return f"{base}/pulls/{resource.number}/comments/{resource.suffix}"
    if resource.kind == "workflow_run":
        return f"{base}/actions/runs/{resource.number}"
    if resource.kind == "release":
        return (
            f"{base}/releases/tags/{resource.suffix}"
            if resource.suffix
            else f"{base}/releases"
        )
    return f"{base}/tags/{resource.suffix}"
