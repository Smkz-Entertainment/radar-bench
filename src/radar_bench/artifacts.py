"""Fetch and verify external historical benchmark artifacts.

The repository publishes manifests and reconstruction metadata, not historical
wheel bytes.  This module keeps acquisition separate from evaluation: fetch
may use the network, while verify is local-only and evaluation remains
network-denied inside the executor.
"""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, cast
from urllib.error import URLError
from urllib.parse import quote, unquote, urlparse
from urllib.request import Request, urlopen  # nosec B310 - hosts are allowlisted

SUITE_RELATIVE = Path("corpus/v1.0.1/decisive-v1.1/suite.json")
CATALOG_RELATIVE = Path("corpus/v1.0.1/decisive-v1.1/artifact-catalog.json")
DEFAULT_ARTIFACT_DIR = Path("artifacts/external")
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_BUNDLE_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 60
PYPI_API_HOST = "pypi.org"
PYPI_FILE_HOST = "files.pythonhosted.org"


class ArtifactContractError(ValueError):
    """Raised when public artifact metadata is incomplete or inconsistent."""


@dataclass(frozen=True)
class ArtifactFile:
    name: str
    digest: str
    size: int


@dataclass(frozen=True)
class ArtifactBundle:
    artifact_id: str
    case_ids: tuple[str, ...]
    incidents: tuple[str, ...]
    format: str
    architecture: str
    python: str
    total_bytes: int
    bundle_digest: str
    redistribution_status: str
    provenance: tuple[str, ...]
    files: tuple[ArtifactFile, ...]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise ArtifactContractError(f"JSON exceeds size limit: {path.name}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except ArtifactContractError:
        raise
    except (OSError, ValueError) as exc:
        raise ArtifactContractError(f"cannot read JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ArtifactContractError(f"JSON object required: {path.name}")
    return cast(dict[str, Any], value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _catalog_digest(root: Path) -> str:
    return _sha256(root / CATALOG_RELATIVE)


def _safe_relative(root: Path, value: str, base: Path | None = None) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        raise ArtifactContractError("artifact metadata path escapes the repository")
    resolved = ((base or root) / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ArtifactContractError("artifact metadata path escapes the repository") from exc
    return resolved


def _safe_name(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and path.name == value and ".." not in path.parts


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _bundle_digest(files: Mapping[str, tuple[str, int]]) -> str:
    payload = "\n".join(
        f"{name}\0{digest}\0{size}" for name, (digest, size) in sorted(files.items())
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_archive(path: Path) -> list[str]:
    errors: list[str] = []
    if path.suffix.lower() != ".whl":
        return ["artifact is not a wheel archive"]
    try:
        with zipfile.ZipFile(path) as archive:
            total_uncompressed = 0
            for member in archive.infolist():
                name = member.filename
                parts = PurePosixPath(name).parts
                if not name or name.startswith(("/", "\\")) or ".." in parts or "\\" in name:
                    errors.append(f"unsafe archive member: {name!r}")
                total_uncompressed += member.file_size
                if member.file_size > MAX_FILE_BYTES:
                    errors.append(f"archive member exceeds size limit: {name!r}")
            if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                errors.append("archive uncompressed size exceeds limit")
            if archive.testzip() is not None:
                errors.append("archive CRC check failed")
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"invalid wheel archive: {type(exc).__name__}")
    return errors


def _load_bundles(root: Path, suite_id: str) -> tuple[dict[str, Any], tuple[ArtifactBundle, ...]]:
    if suite_id != "decisive-v1.1":
        raise ArtifactContractError(f"unsupported artifact suite: {suite_id}")
    catalog = _read_json(root / CATALOG_RELATIVE)
    if catalog.get("schema_version") != "1.0" or catalog.get("suite_id") != suite_id:
        raise ArtifactContractError("artifact catalog has the wrong suite identity")
    raw_bundles = catalog.get("bundles")
    if not isinstance(raw_bundles, list) or len(raw_bundles) != 5:
        raise ArtifactContractError("artifact catalog must contain five bundles")
    catalog_by_id: dict[str, Mapping[str, Any]] = {}
    for raw in raw_bundles:
        if not isinstance(raw, Mapping) or not isinstance(raw.get("artifact_id"), str):
            raise ArtifactContractError("artifact catalog contains an invalid bundle")
        artifact_id = str(raw["artifact_id"])
        if not _safe_name(artifact_id):
            raise ArtifactContractError(f"invalid artifact ID: {artifact_id}")
        if artifact_id in catalog_by_id:
            raise ArtifactContractError(f"duplicate artifact ID: {artifact_id}")
        catalog_by_id[artifact_id] = raw

    suite = _read_json(root / SUITE_RELATIVE)
    entries = suite.get("historical_cases")
    if not isinstance(entries, list) or len(entries) != 5:
        raise ArtifactContractError("decisive-v1.1 does not contain five historical cases")
    bundles: list[ArtifactBundle] = []
    suite_base = (root / SUITE_RELATIVE).parent.resolve()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ArtifactContractError("historical suite entry is invalid")
        manifest_path = _safe_relative(root, str(entry.get("manifest", "")), suite_base)
        manifest = _read_json(manifest_path)
        artifact_bundle = manifest.get("artifact_bundle")
        if not isinstance(artifact_bundle, Mapping):
            raise ArtifactContractError(f"missing artifact bundle: {entry.get('case_id')}")
        raw_artifact_id = artifact_bundle.get("bundle_id")
        if not isinstance(raw_artifact_id, str):
            raise ArtifactContractError(f"missing artifact bundle ID: {entry.get('case_id')}")
        artifact_id = raw_artifact_id
        raw_catalog = catalog_by_id.get(artifact_id)
        if raw_catalog is None:
            raise ArtifactContractError(f"catalog missing bundle: {artifact_id}")
        expected = artifact_bundle.get("files")
        catalog_files = raw_catalog.get("files")
        if not isinstance(expected, Mapping) or not isinstance(catalog_files, list):
            raise ArtifactContractError(f"invalid file inventory: {artifact_id}")
        catalog_by_name: dict[str, ArtifactFile] = {}
        for item in catalog_files:
            if not isinstance(item, Mapping):
                raise ArtifactContractError(f"invalid catalog file: {artifact_id}")
            name = item.get("name")
            digest = item.get("sha256")
            size = item.get("size")
            if (
                not isinstance(name, str)
                or not _safe_name(name)
                or not isinstance(digest, str)
                or not _valid_digest(digest)
                or type(size) is not int
                or size < 0
            ):
                raise ArtifactContractError(f"invalid file metadata: {artifact_id}")
            if name in catalog_by_name:
                raise ArtifactContractError(f"duplicate catalog file: {artifact_id}/{name}")
            catalog_by_name[name] = ArtifactFile(name, digest, size)
        if set(str(name) for name in expected) != set(catalog_by_name):
            raise ArtifactContractError(f"manifest/catalog file sets differ: {artifact_id}")
        for name, digest in expected.items():
            if not isinstance(name, str) or not isinstance(digest, str) or not _valid_digest(digest):
                raise ArtifactContractError(f"invalid manifest file metadata: {artifact_id}")
            item = catalog_by_name[name]
            if digest != item.digest:
                raise ArtifactContractError(f"manifest/catalog digest differs: {artifact_id}/{name}")
        files = tuple(catalog_by_name[name] for name in sorted(catalog_by_name))
        total_bytes = raw_catalog.get("total_bytes")
        bundle_digest = raw_catalog.get("bundle_digest")
        if type(total_bytes) is not int or total_bytes < 0 or not _valid_digest(bundle_digest):
            raise ArtifactContractError(f"invalid bundle metadata: {artifact_id}")
        if sum(item.size for item in files) != total_bytes:
            raise ArtifactContractError(f"catalog total size differs: {artifact_id}")
        bundle_records = {item.name: (item.digest, item.size) for item in files}
        if _bundle_digest(bundle_records) != bundle_digest:
            raise ArtifactContractError(f"catalog bundle digest differs: {artifact_id}")
        if raw_catalog.get("redistribution_status") not in {"RECONSTRUCT_ONLY", "REDISTRIBUTABLE", "UNCLEAR_DO_NOT_PUBLISH"}:
            raise ArtifactContractError(f"invalid redistribution status: {artifact_id}")
        case_id = str(entry.get("case_id"))
        case_ids = tuple(str(value) for value in raw_catalog.get("case_ids", []))
        if case_id not in case_ids:
            raise ArtifactContractError(f"catalog does not map case to bundle: {case_id}")
        bundles.append(
            ArtifactBundle(
                artifact_id=str(artifact_id),
                case_ids=case_ids,
                incidents=tuple(str(value) for value in raw_catalog.get("incidents", [])),
                format=str(raw_catalog.get("format")),
                architecture=str(raw_catalog.get("supported_architecture")),
                python=str(raw_catalog.get("python")),
                total_bytes=total_bytes,
                bundle_digest=bundle_digest,
                redistribution_status=str(raw_catalog["redistribution_status"]),
                provenance=tuple(str(value) for value in raw_catalog.get("upstream_provenance", [])),
                files=files,
            )
        )
    if len({bundle.artifact_id for bundle in bundles}) != 5:
        raise ArtifactContractError("historical cases do not map to five distinct bundles")
    return catalog, tuple(bundles)


def default_artifact_root(root: Path, suite_id: str = "decisive-v1.1") -> Path:
    """Return the ignored local default for externally acquired bundles."""

    return root / DEFAULT_ARTIFACT_DIR / suite_id


def _redacted_root() -> str:
    return "external-artifact-root"


def _verify_bundle(bundle: ArtifactBundle, artifact_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    bundle_root = artifact_root / bundle.artifact_id
    if not bundle_root.is_dir() or bundle_root.is_symlink():
        return {"artifact_id": bundle.artifact_id, "status": "BLOCKED", "errors": ["bundle directory is absent"]}
    expected = {item.name: item for item in bundle.files}
    actual_files: dict[str, Path] = {}
    actual_records: dict[str, tuple[str, int]] = {}
    for path in bundle_root.rglob("*"):
        relative = path.relative_to(bundle_root).as_posix()
        if path.is_symlink() or not path.is_file() or not _safe_name(relative):
            errors.append(f"unexpected or unsafe bundle entry: {relative}")
        else:
            actual_files[relative] = path
    for name, item in expected.items():
        candidate = actual_files.get(name)
        if candidate is None:
            errors.append(f"missing file: {name}")
            continue
        if candidate.stat().st_size != item.size:
            errors.append(f"size mismatch: {name}")
            continue
        digest = _sha256(candidate)
        if digest != item.digest:
            errors.append(f"digest mismatch: {name}")
            continue
        actual_records[name] = (digest, item.size)
        errors.extend(f"{name}: {error}" for error in _validate_archive(candidate))
    extras = sorted(set(actual_files) - set(expected))
    errors.extend(f"unexpected file: {name}" for name in extras)
    total_bytes = sum(path.stat().st_size for path in actual_files.values())
    if total_bytes > MAX_BUNDLE_BYTES:
        errors.append("bundle exceeds total size limit")
    if not errors and _bundle_digest(actual_records) != bundle.bundle_digest:
        errors.append("bundle digest mismatch")
    return {
        "artifact_id": bundle.artifact_id,
        "case_ids": list(bundle.case_ids),
        "status": "READY" if not errors else "BLOCKED",
        "bytes": total_bytes,
        "bundle_digest": bundle.bundle_digest if not errors else None,
        "errors": errors,
    }


def verify_artifacts(root: Path, suite_id: str, artifact_root: Path | None = None) -> dict[str, Any]:
    """Verify external bundles locally without network access or extraction."""

    try:
        catalog, bundles = _load_bundles(root, suite_id)
    except ArtifactContractError as exc:
        return {"status": "INVALID", "suite_id": suite_id, "errors": [str(exc)], "network_used": False}
    external_root = (artifact_root or default_artifact_root(root, suite_id)).resolve()
    results = [_verify_bundle(bundle, external_root) for bundle in bundles]
    errors = [f"{item['artifact_id']}: {error}" for item in results for error in item["errors"]]
    return {
        "status": "READY" if not errors else "BLOCKED",
        "suite_id": suite_id,
        "artifact_root": _redacted_root(),
        "catalog_digest": _catalog_digest(root),
        "catalog_policy": catalog.get("catalog_policy"),
        "network_used": False,
        "bundles": results,
        "errors": errors,
    }


def _pypi_project_version(filename: str) -> tuple[str, str]:
    if not filename.endswith(".whl"):
        raise ArtifactContractError(f"unsupported artifact format: {filename}")
    parts = filename[:-4].split("-")
    if len(parts) < 5:
        raise ArtifactContractError(f"cannot derive PyPI project/version: {filename}")
    distribution = "-".join(parts[:-4]).replace("_", "-")
    return distribution, parts[-4]


def _approved_https_url(value: str, host: str) -> bool:
    if not isinstance(value, str) or "\\" in value or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in value
    ):
        return False
    try:
        parsed = urlparse(value)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == host
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None
        and not parsed.query
        and not parsed.fragment
    )


def _approved_file_url(value: str, filename: str) -> bool:
    if not _approved_https_url(value, PYPI_FILE_HOST):
        return False
    try:
        decoded_name = PurePosixPath(unquote(urlparse(value).path)).name
    except (UnicodeError, ValueError):
        return False
    return decoded_name == filename


def _read_remote_json(url: str) -> dict[str, Any]:
    if not _approved_https_url(url, PYPI_API_HOST):
        raise ArtifactContractError("unapproved metadata host")
    request = Request(url, headers={"User-Agent": "radar-bench/1.0.1"})
    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:  # nosec B310
            final_url = str(response.geturl())
            if not _approved_https_url(final_url, PYPI_API_HOST):
                raise ArtifactContractError("metadata redirect left the approved host")
            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_JSON_BYTES:
                raise ArtifactContractError("remote metadata exceeds size limit")
            payload = response.read(MAX_JSON_BYTES + 1)
    except (OSError, URLError, ValueError) as exc:
        raise ArtifactContractError("unable to acquire PyPI metadata") from exc
    if len(payload) > MAX_JSON_BYTES:
        raise ArtifactContractError("remote metadata exceeds size limit")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ArtifactContractError("remote metadata is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ArtifactContractError("remote metadata is not an object")
    return cast(dict[str, Any], value)


def _source_url(filename: str, cache: dict[str, str]) -> str:
    project, version = _pypi_project_version(filename)
    if filename not in cache:
        metadata_url = f"https://{PYPI_API_HOST}/pypi/{quote(project)}/{quote(version)}/json"
        metadata = _read_remote_json(metadata_url)
        releases = metadata.get("urls")
        if not isinstance(releases, list):
            raise ArtifactContractError(f"PyPI metadata has no files: {filename}")
        match = next(
            (item for item in releases if isinstance(item, Mapping) and item.get("filename") == filename),
            None,
        )
        if not isinstance(match, Mapping) or not isinstance(match.get("url"), str):
            raise ArtifactContractError(f"exact PyPI file is unavailable: {filename}")
        cache[filename] = str(match["url"])
    url = cache[filename]
    if not _approved_file_url(url, filename):
        raise ArtifactContractError(f"unapproved artifact host: {filename}")
    return url


def _download(url: str, destination: Path, expected: ArtifactFile) -> None:
    if not _approved_file_url(url, expected.name):
        raise ArtifactContractError("download URL is not an approved PyPI file URL")
    if destination.exists() and destination.is_symlink():
        raise ArtifactContractError(f"refusing symlink destination: {destination.name}")
    partial = destination.with_name(destination.name + ".part.whl")
    if partial.exists() and partial.is_symlink():
        raise ArtifactContractError(f"refusing symlink temporary file: {partial.name}")
    partial.unlink(missing_ok=True)
    request = Request(url, headers={"User-Agent": "radar-bench/1.0.1"})
    digest = hashlib.sha256()
    size = 0
    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:  # nosec B310
            final_url = str(response.geturl())
            if not _approved_file_url(final_url, expected.name):
                raise ArtifactContractError("artifact redirect left the approved host")
            length = response.headers.get("Content-Length")
            if length and int(length) > min(MAX_FILE_BYTES, expected.size):
                raise ArtifactContractError(f"download exceeds recorded size: {expected.name}")
            with partial.open("wb") as output:
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(block)
                    if size > expected.size or size > MAX_FILE_BYTES:
                        raise ArtifactContractError(f"download exceeds recorded size: {expected.name}")
                    digest.update(block)
                    output.write(block)
    except ArtifactContractError:
        partial.unlink(missing_ok=True)
        raise
    except (OSError, URLError, ValueError) as exc:
        partial.unlink(missing_ok=True)
        raise ArtifactContractError(f"unable to download: {expected.name}") from exc
    if size != expected.size or "sha256:" + digest.hexdigest() != expected.digest:
        partial.unlink(missing_ok=True)
        raise ArtifactContractError(f"download verification failed: {expected.name}")
    archive_errors = _validate_archive(partial)
    if archive_errors:
        partial.unlink(missing_ok=True)
        raise ArtifactContractError(
            f"download archive validation failed: {expected.name}: {archive_errors[0]}"
        )
    os.replace(partial, destination)


def fetch_artifacts(root: Path, suite_id: str, artifact_root: Path | None = None) -> dict[str, Any]:
    """Reconstruct exact wheel files from PyPI, then verify the complete root."""

    try:
        _catalog, bundles = _load_bundles(root, suite_id)
    except ArtifactContractError as exc:
        return {"status": "INVALID", "suite_id": suite_id, "errors": [str(exc)], "network_used": False}
    external_root = (artifact_root or default_artifact_root(root, suite_id)).resolve()
    external_root.mkdir(parents=True, exist_ok=True)
    cache: dict[str, str] = {}
    errors: list[str] = []
    fetched: list[str] = []
    network_used = False
    for bundle in bundles:
        if bundle.redistribution_status == "UNCLEAR_DO_NOT_PUBLISH":
            errors.append(f"{bundle.artifact_id}: redistribution status is unresolved")
            continue
        bundle_root = external_root / bundle.artifact_id
        bundle_root.mkdir(parents=True, exist_ok=True)
        existing = _verify_bundle(bundle, external_root)
        for expected in bundle.files:
            destination = bundle_root / expected.name
            if destination.is_file() and not destination.is_symlink() and not existing["errors"]:
                continue
            try:
                network_used = True
                _download(_source_url(expected.name, cache), destination, expected)
                fetched.append(f"{bundle.artifact_id}/{expected.name}")
            except ArtifactContractError as exc:
                errors.append(str(exc))
                break
    verification = verify_artifacts(root, suite_id, external_root)
    errors.extend(verification.get("errors", []))
    status = "READY" if not errors and verification["status"] == "READY" else "BLOCKED"
    if status == "READY":
        provenance = {
            "schema_version": "1.0",
            "suite_id": suite_id,
            "catalog_digest": verification["catalog_digest"],
            "network_used": True,
            "redistribution_status": "RECONSTRUCT_ONLY",
            "bundles": verification["bundles"],
        }
        (external_root / "provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return {
        "status": status,
        "suite_id": suite_id,
        "artifact_root": _redacted_root(),
        "catalog_digest": verification.get("catalog_digest"),
        "network_used": network_used,
        "fetched_files": fetched,
        "bundles": verification.get("bundles", []),
        "errors": errors,
    }
