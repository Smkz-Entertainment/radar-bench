"""Cross-platform project and cache paths."""

from __future__ import annotations

import os
import shutil
import sys
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
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return (base / "radar-bench").resolve()


def package_resource_root() -> Path:
    """Materialize packaged benchmark resources into a private cache directory.

    Installed wheels and sdists do not have a repository checkout or a stable
    current working directory.  ``importlib.resources`` is therefore the
    source of truth; materialization gives the existing path-oriented runtime
    code a stable, read-only-compatible directory to inspect.
    """

    source = resources.files("radar_bench").joinpath("resources")
    target = cache_root() / "package-resources" / "v1.0.1"
    marker = target / ".materialized"
    if marker.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    with resources.as_file(source) as source_path:
        shutil.copytree(source_path, staging)
    marker_staging = staging / ".materialized"
    marker_staging.write_text("radar-bench packaged resources\n", encoding="utf-8")
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    return target


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
