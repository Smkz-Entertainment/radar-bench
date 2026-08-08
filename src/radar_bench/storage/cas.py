"""Atomic SHA-256 content-addressed storage with bounded object sizes."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from radar_bench.errors import SecurityError


class CASStore:
    def __init__(self, root: Path, max_bytes: int = 10 * 1024 * 1024) -> None:
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def object_path(self, digest: str) -> Path:
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise SecurityError("invalid CAS digest")
        hex_digest = digest[7:]
        if any(char not in "0123456789abcdef" for char in hex_digest):
            raise SecurityError("invalid CAS digest")
        path = (
            self.root / "objects" / "sha256" / hex_digest[:2] / hex_digest[2:]
        ).resolve()
        if self.root not in path.parents:
            raise SecurityError("CAS path escaped root")
        return path

    def put_bytes(self, payload: bytes) -> str:
        if len(payload) > self.max_bytes:
            raise SecurityError("evidence object exceeds configured size limit")
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        target = self.object_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            fd, temporary = tempfile.mkstemp(prefix=".object-", dir=str(target.parent))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return digest

    def read_bytes(self, digest: str) -> bytes:
        path = self.object_path(digest)
        payload = path.read_bytes()
        if "sha256:" + hashlib.sha256(payload).hexdigest() != digest:
            raise SecurityError("CAS digest mismatch")
        return payload
