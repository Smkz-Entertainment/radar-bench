"""Cross-platform project and cache paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root(start: Path | None = None) -> Path:
    """Find the repository root without relying on a shell or cwd global."""
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "src").is_dir():
            return candidate
    return current


def cache_root(root: Path | None = None) -> Path:
    """Return a user-local cache path; callers create it explicitly."""
    if value := os.environ.get("RADAR_BENCH_CACHE"):
        return Path(value).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return (base / "radar-bench").resolve()


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
