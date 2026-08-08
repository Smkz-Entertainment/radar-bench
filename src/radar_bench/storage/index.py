"""SQLite metadata index for cached public evidence."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class EvidenceIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("""CREATE TABLE IF NOT EXISTS evidence (
          source_uri TEXT PRIMARY KEY, canonical_identity TEXT NOT NULL,
          retrieved_at TEXT NOT NULL, http_status INTEGER, etag TEXT,
          last_modified TEXT, digest TEXT, media_type TEXT, cutoff_relation TEXT,
          visibility TEXT NOT NULL, parser_version TEXT NOT NULL,
          error_state TEXT, retry_count INTEGER NOT NULL DEFAULT 0
        )""")
        self.connection.commit()

    def upsert(self, **record: Any) -> None:
        keys = [
            "source_uri",
            "canonical_identity",
            "retrieved_at",
            "http_status",
            "etag",
            "last_modified",
            "digest",
            "media_type",
            "cutoff_relation",
            "visibility",
            "parser_version",
            "error_state",
            "retry_count",
        ]
        values = [record.get(key) for key in keys]
        self.connection.execute(
            """INSERT INTO evidence
          (source_uri, canonical_identity, retrieved_at, http_status, etag,
           last_modified, digest, media_type, cutoff_relation, visibility,
           parser_version, error_state, retry_count)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(source_uri) DO UPDATE SET
           canonical_identity=excluded.canonical_identity,
           retrieved_at=excluded.retrieved_at, http_status=excluded.http_status,
           etag=excluded.etag, last_modified=excluded.last_modified,
           digest=excluded.digest, media_type=excluded.media_type,
           cutoff_relation=excluded.cutoff_relation, visibility=excluded.visibility,
           parser_version=excluded.parser_version, error_state=excluded.error_state,
           retry_count=excluded.retry_count""",
            values,
        )
        self.connection.commit()

    def get(self, source_uri: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM evidence WHERE source_uri = ?", (source_uri,)
        ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self.connection.close()
