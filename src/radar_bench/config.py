"""Cross-platform project and cache paths."""

from __future__ import annotations

import os
import hashlib
import json
import sys
import time
from importlib import resources
from pathlib import Path


def project_root(start: Path | None = None) -> Path:
    """Find the repository root without relying on a shell or cwd global."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    return package_resource_root()


def cache_root(root: Path | None = None) -> Path:
    """Return a user-local cache path; callers create it explicitly."""
    if value := os.environ.get("RADAR_BENCH_CACHE"):
        return Path(value).expanduser().resolve()
    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA")
        base = Path(local_appdata) if local_appdata else Path.home() / "AppData/Local"
    else:
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        base = Path(xdg_cache) if xdg_cache else Path.home() / ".cache"
    return (base / "radar-bench").resolve()


def package_resource_root() -> Path:
    """Materialize resources using a verified content-addressed cache.

    Installed wheels and sdists do not have a repository checkout or a stable
    current working directory.  ``importlib.resources`` is therefore the
    source of truth.  The destination is keyed by a manifest digest and is
    published atomically only after every file has been checked.  A marker
    file is intentionally not used as an integrity proof.
    """

    source = resources.files("radar_bench").joinpath("resources")
    entries: list[dict[str, str | int]] = []
    with resources.as_file(source) as source_path:
        for item in sorted(source_path.rglob("*")):
            if item.is_symlink():
                raise RuntimeError(f"packaged resource symlink is not allowed: {item}")
            if not item.is_file():
                continue
            relative = item.relative_to(source_path).as_posix()
            digest = hashlib.sha256(item.read_bytes()).hexdigest()
            entries.append({"path": relative, "bytes": item.stat().st_size, "sha256": digest})
    manifest = {"schema_version": "1", "files": entries}
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    root = cache_root() / "package-resources" / manifest_digest
    manifest_path = root / "resource-manifest.json"

    def valid_destination() -> bool:
        if not root.is_dir() or not manifest_path.is_file() or manifest_path.is_symlink():
            return False
        try:
            observed = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if observed != manifest:
            return False
        expected = {str(item["path"]): item for item in entries}
        actual: dict[str, Path] = {}
        for item in root.rglob("*"):
            relative = item.relative_to(root).as_posix()
            if relative == "resource-manifest.json":
                continue
            if item.is_dir():
                continue
            if item.is_symlink() or not item.is_file():
                return False
            actual[relative] = item
        if set(actual) != set(expected):
            return False
        for relative, record in expected.items():
            path = actual[relative]
            if path.stat().st_size != record["bytes"]:
                return False
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                return False
        return True

    if valid_destination():
        return root
    root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = root.parent / f"{manifest_digest}.lock"
    lock_fd: int | None = None
    try:
        deadline = time.monotonic() + 15
        while lock_fd is None:
            try:
                lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out acquiring resource materialization lock")
                time.sleep(0.05)
        if valid_destination():
            return root
        staging = root.parent / f".{manifest_digest}.{secrets_token()}"
        staging.mkdir(mode=0o700)
        try:
            with resources.as_file(source) as source_path:
                for entry in entries:
                    relative_path = Path(str(entry["path"]))
                    destination = staging / relative_path
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source_item = source_path / relative_path
                    if source_item.is_symlink() or not source_item.is_file():
                        raise RuntimeError(f"packaged resource changed during materialization: {relative_path}")
                    destination.write_bytes(source_item.read_bytes())
            (staging / "resource-manifest.json").write_bytes(manifest_bytes)
            if root.exists():
                if not valid_destination():
                    raise RuntimeError("content-addressed resource destination already conflicts")
            else:
                os.replace(staging, root)
                staging = None  # type: ignore[assignment]
        finally:
            if staging is not None and staging.exists():
                for item in sorted(staging.rglob("*"), reverse=True):
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                    elif item.is_dir():
                        item.rmdir()
                staging.rmdir()
        if not valid_destination():
            raise RuntimeError("published package resources failed manifest verification")
        return root
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def secrets_token() -> str:
    """Return a filesystem-safe staging suffix without exposing case data."""

    return os.urandom(12).hex()


def schema_root(root: Path | None = None) -> Path:
    local = project_root(root) / "schema"
    if local.exists():
        return local
    package_path = Path(__file__).resolve()
    package_roots = (package_path.parents[1], package_path.parents[2])
    candidates = tuple(
        root / "share" / "radar-bench" / "schema" for root in package_roots
    ) + (Path(sys.prefix) / "share" / "radar-bench" / "schema",)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return local
