"""Read-only public GitHub REST client using the standard library."""

from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from radar_bench.errors import ExternalBlocked, SecurityError
from radar_bench.github.urls import ALLOWED_HOSTS


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Request | None:
        return None


class GitHubClient:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retries: int = 3,
        user_agent: str = "radar-bench/0.1.0 (read-only)",
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.etags: dict[str, str] = {}
        self.opener = build_opener(_NoRedirect)

    def _check_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise SecurityError("GitHub client rejected non-allowlisted URL")

    def get_json(
        self, url: str
    ) -> tuple[int, dict[str, Any] | list[Any] | None, dict[str, str]]:
        if os.environ.get("RADAR_BENCH_NETWORK") == "denied":
            raise ExternalBlocked("network is disabled during v0.3 blind inference")
        current = url
        for redirect_count in range(3):
            self._check_url(current)
            headers = {
                "Accept": "application/vnd.github+json",
                "User-Agent": self.user_agent,
            }
            token = os.environ.get("GITHUB_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            if current in self.etags:
                headers["If-None-Match"] = self.etags[current]
            request = Request(current, headers=headers, method="GET")
            for attempt in range(self.retries + 1):
                try:
                    with self.opener.open(request, timeout=self.timeout) as response:
                        response_headers = {
                            key.lower(): value
                            for key, value in response.headers.items()
                        }
                        if response_headers.get("etag"):
                            self.etags[current] = response_headers["etag"]
                        return (
                            response.status,
                            json.loads(response.read(5 * 1024 * 1024).decode("utf-8")),
                            response_headers,
                        )
                except HTTPError as exc:
                    if exc.code == 304:
                        return (
                            304,
                            None,
                            {key.lower(): value for key, value in exc.headers.items()},
                        )
                    if (
                        exc.code in {403, 429} or exc.code >= 500
                    ) and attempt < self.retries:
                        time.sleep(
                            min(
                                8.0,
                                0.25 * (2**attempt)
                                + secrets.SystemRandom().random() * 0.1,
                            )
                        )
                        continue
                    if exc.code in {401, 403, 429}:
                        raise ExternalBlocked(
                            f"GitHub request blocked with HTTP {exc.code}"
                        ) from exc
                    raise ExternalBlocked(
                        f"GitHub request failed with HTTP {exc.code}"
                    ) from exc
                except (URLError, TimeoutError, OSError) as exc:
                    if attempt < self.retries:
                        time.sleep(
                            min(
                                8.0,
                                0.25 * (2**attempt)
                                + secrets.SystemRandom().random() * 0.1,
                            )
                        )
                        continue
                    raise ExternalBlocked("GitHub request unavailable") from exc
            raise ExternalBlocked("GitHub retry budget exhausted")
        raise SecurityError("redirect chain exceeded limit")

    def get_pages(
        self, url: str, *, max_pages: int = 20
    ) -> list[dict[str, Any] | list[Any]]:
        """Fetch allowlisted Link-header pages without following arbitrary hosts."""
        pages: list[dict[str, Any] | list[Any]] = []
        current = url
        for _ in range(max_pages):
            status, payload, headers = self.get_json(current)
            if status == 304 or payload is None:
                break
            pages.append(payload)
            next_url = _next_link(headers.get("link", ""))
            if not next_url:
                break
            self._check_url(next_url)
            current = next_url
        return pages


def _next_link(value: str) -> str | None:
    for part in value.split(","):
        if 'rel="next"' in part:
            start, end = part.find("<"), part.find(">")
            if start >= 0 and end > start:
                return part[start + 1 : end]
    return None
