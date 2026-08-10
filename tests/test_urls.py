from __future__ import annotations

import pytest

from radar_bench.errors import SecurityError
from radar_bench.github.urls import api_url, parse_github_url


def test_github_url_canonicalization() -> None:
    issue = parse_github_url("https://github.com/pandas-dev/pandas/issues/55137")
    assert issue.identity == "github:pandas-dev/pandas:issue/55137"
    assert api_url(issue).endswith("/issues/55137")
    assert parse_github_url("https://github.com/a/b.git").repo == "b"
    assert parse_github_url("https://github.com/a/b/commit/abc123").kind == "commit"
    assert parse_github_url("https://api.github.com/repos/a/b").kind == "repository"
    assert parse_github_url("https://github.com/a/b/").kind == "repository"
    assert parse_github_url("https://github.com/a/b/issues/1#issuecomment-9").kind == "issue_comment"
    assert parse_github_url("https://github.com/a/b/pull/2#discussion_r3").kind == "review_comment"
    assert parse_github_url("https://github.com/a/b/releases").kind == "release"
    assert parse_github_url("https://github.com/a/b/releases/tag/v1").suffix == "v1"
    assert parse_github_url("https://github.com/a/b/actions/runs/4").kind == "workflow_run"
    assert parse_github_url("https://github.com/a/b/tree/main/docs").suffix == "main/docs"
    assert api_url(parse_github_url("https://github.com/a/b/releases")) .endswith("/releases")
    assert api_url(parse_github_url("https://github.com/a/b/actions/runs/4")).endswith("/runs/4")
    assert api_url(parse_github_url("https://github.com/a/b/tree/main")).endswith("/tags/main")


@pytest.mark.parametrize(
    "value",
    [
        "http://github.com/a/b",
        "https://github.com/a/b?redirect=evil",
        # Deliberately inert credential-shaped input; no real credential.
        "https://" + "user:pass" + "@github.com/a/b",
        "https://github.com:443/a/b",
        "https://github.com/a/b%2Fissues/1",
        "https://github.com/a/b\\\\issues/1",
        "https://github.com/a//b",
        "https://github.com/a/b/issues/not-a-number",
        "https://github.com:bad/a/b",
        "https://github.com/a",
        "https://api.github.com/a/b",
        "https://github.com/a!/b",
        "https://github.com/a/.git",
        "https://github.com/a/b/issues/1#bad%20fragment",
        "https://github.com/a/b/unknown/1",
        "https://github.com/a/b/releases/nope",
        "https://github.com/a/b/actions/nope/4",
        "https://github.com/a/b/tree/main%2Fdocs",
    ],
)
def test_github_url_rejects_unsafe_forms(value: str) -> None:
    with pytest.raises(SecurityError):
        parse_github_url(value)
