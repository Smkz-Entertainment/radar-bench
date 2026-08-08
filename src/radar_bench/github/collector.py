"""Resumable public GitHub collection into CAS plus SQLite metadata."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from radar_bench.errors import RadarError
from radar_bench.github.client import GitHubClient
from radar_bench.github.urls import api_url, parse_github_url
from radar_bench.normalize.redaction import redact
from radar_bench.storage.cas import CASStore
from radar_bench.storage.index import EvidenceIndex
from radar_bench.storage.manifests import mark_queue_item


def collect_url(
    url: str, output: Path, cutoff: str, *, client: GitHubClient | None = None
) -> dict[str, Any]:
    resource = parse_github_url(url)
    store = CASStore(output)
    index = EvidenceIndex(output / "index.sqlite3")
    status, payload, headers = (client or GitHubClient()).get_json(api_url(resource))
    raw = (
        redact(
            json.dumps(payload, sort_keys=True, separators=(",", ":"))
            .encode("utf-8")
            .decode("utf-8")
        ).encode("utf-8")
        if payload is not None
        else b""
    )
    digest = store.put_bytes(raw) if raw else None
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    index.upsert(
        source_uri=url,
        canonical_identity=resource.identity,
        retrieved_at=now,
        http_status=status,
        etag=headers.get("etag"),
        last_modified=headers.get("last-modified"),
        digest=digest,
        media_type="application/json",
        cutoff_relation="unknown",
        visibility="public",
        parser_version="0.1",
        error_state=None,
        retry_count=0,
    )
    index.close()
    return {
        "url": url,
        "identity": resource.identity,
        "status": status,
        "digest": digest,
    }


def collect_manifest(manifest: Path, output: Path, cutoff: str) -> dict[str, Any]:
    queue_path = output / "collection-queue.json"
    completed, blocked = [], []
    import csv

    with manifest.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            for url in row["source_urls"].split(";"):
                try:
                    completed.append(collect_url(url, output, cutoff))
                    mark_queue_item(queue_path, url, status="completed")
                except (
                    OSError,
                    ValueError,
                    RadarError,
                ) as exc:  # external failures are resumable, not fabricated success
                    blocked.append(
                        {"url": url, "error": type(exc).__name__ + ": " + str(exc)}
                    )
                    mark_queue_item(queue_path, url, status="blocked", detail=str(exc))
    return {"completed": completed, "blocked": blocked, "queue": str(queue_path)}
