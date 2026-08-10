"""Allowlisted canonical GitHub URL parsing."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse
import re

from radar_bench.errors import SecurityError

ALLOWED_HOSTS = {"github.com", "api.github.com"}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


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
    if not isinstance(value, str) or not value or any(
        ord(char) < 0x20 or ord(char) == 0x7F for char in value
    ):
        raise SecurityError("GitHub URL contains invalid control characters")
    if "\\" in value or "\x00" in value or "%" in value:
        raise SecurityError("GitHub URL contains forbidden escaping")
    try:
        parsed = urlparse(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise SecurityError("GitHub URL is malformed") from exc
    if (
        parsed.scheme != "https"
        or hostname not in ALLOWED_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.params
    ):
        raise SecurityError("only https://github.com public URLs are accepted")
    if not parsed.path.startswith("/") or "//" in parsed.path:
        raise SecurityError("GitHub URL path is not canonical")
    parts = parsed.path.split("/")[1:]
    if parts and parts[-1] == "":
        parts.pop()
    if hostname == "api.github.com":
        if not parts or parts[0] != "repos":
            raise SecurityError("GitHub API URL lacks /repos prefix")
        parts = parts[1:]
    if len(parts) < 2:
        raise SecurityError("GitHub URL lacks owner/repository")
    owner, repo = parts[0], parts[1]
    if not _NAME.fullmatch(owner):
        raise SecurityError("GitHub owner is invalid")
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _NAME.fullmatch(repo):
        raise SecurityError("GitHub repository is invalid")
    if len(parts) == 2:
        return GitHubResource(owner, repo, "repository")
    section = parts[2]
    if section in {"issues", "pull"}:
        if len(parts) != 4 or not parts[3].isdigit() or int(parts[3]) <= 0:
            raise SecurityError("resource number is invalid")
        number = int(parts[3])
        kind = "pull_request" if section == "pull" else "issue"
        suffix = parsed.fragment or None
        if suffix and not re.fullmatch(r"[A-Za-z0-9_.-]+", suffix):
            raise SecurityError("GitHub fragment is invalid")
        if suffix and suffix.startswith("issuecomment-"):
            kind, suffix = "issue_comment", suffix.removeprefix("issuecomment-")
        elif suffix and suffix.startswith(("discussion_r", "review")):
            kind, suffix = (
                "review_comment",
                suffix.removeprefix("discussion_r").removeprefix("review"),
            )
        return GitHubResource(owner, repo, kind, number, suffix)
    if section == "commit":
        if len(parts) != 4 or not re.fullmatch(r"[0-9A-Fa-f]{4,64}", parts[3]):
            raise SecurityError("commit identifier is invalid")
        return GitHubResource(owner, repo, "commit", suffix=parts[3])
    if section == "releases":
        if len(parts) == 3:
            return GitHubResource(owner, repo, "release")
        if len(parts) == 5 and parts[3] == "tag" and _NAME.fullmatch(parts[4]):
            return GitHubResource(owner, repo, "release", suffix=parts[4])
        raise SecurityError("release URL is not canonical")
    if section == "actions":
        if len(parts) == 5 and parts[3] == "runs" and parts[4].isdigit():
            return GitHubResource(owner, repo, "workflow_run", int(parts[4]))
        raise SecurityError("workflow URL is not canonical")
    if section == "tree":
        if len(parts) < 4 or any(not _NAME.fullmatch(part) for part in parts[3:]):
            raise SecurityError("tree reference is invalid")
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
    if resource.kind == "repository":
        return base
    return f"{base}/tags/{resource.suffix}"
