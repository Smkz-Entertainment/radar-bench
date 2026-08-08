"""Portable temporal-blind boundary for candidate providers and later scoring."""

from __future__ import annotations

import hashlib
import json
import os
import platform
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from radar_bench.errors import ExternalBlocked
from radar_bench.providers.base import inference_packet


def digest_path(path: Path) -> str:
    """Hash a file or directory with names included, deterministically."""

    hasher = hashlib.sha256()
    if path.is_file():
        hasher.update(path.name.encode("utf-8"))
        hasher.update(path.read_bytes())
    elif path.is_dir():
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            hasher.update(str(child.relative_to(path)).replace("\\", "/").encode("utf-8"))
            hasher.update(child.read_bytes())
    else:
        raise FileNotFoundError(path)
    return "sha256:" + hasher.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class CandidateFilesystem:
    """Capability object exposing only the candidate snapshot tree."""

    allowed_root: Path

    def resolve(self, path: str | Path) -> Path:
        candidate = Path(path).resolve()
        if not _inside(candidate, self.allowed_root.resolve()):
            raise PermissionError("blind candidate filesystem denied path outside input root")
        if "gold" in candidate.parts:
            raise PermissionError("blind candidate filesystem denied gold path")
        return candidate

    def read_text(self, path: str | Path) -> str:
        return self.resolve(path).read_text(encoding="utf-8")

    def list_files(self) -> list[str]:
        return [
            str(path.relative_to(self.allowed_root.resolve())).replace("\\", "/")
            for path in sorted(self.allowed_root.resolve().rglob("*"))
            if path.is_file() and "gold" not in path.parts
        ]


@contextmanager
def network_denied() -> Iterator[None]:
    """Mark the process as network-disabled for the repository's collectors."""

    previous = os.environ.get("RADAR_BENCH_NETWORK")
    os.environ["RADAR_BENCH_NETWORK"] = "denied"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("RADAR_BENCH_NETWORK", None)
        else:
            os.environ["RADAR_BENCH_NETWORK"] = previous


@dataclass(frozen=True)
class BlindRun:
    run_id: str
    candidate_snapshot_digest: str
    gold_packet_digest: str
    candidate_allowed_root: str
    candidate_output_digest: str
    implementation_commit: str
    environment_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "0.3",
            "run_id": self.run_id,
            "candidate_snapshot_digest": self.candidate_snapshot_digest,
            "gold_packet_digest": self.gold_packet_digest,
            "network_policy": "denied",
            "candidate_allowed_root": self.candidate_allowed_root,
            "gold_readable_by_candidate": False,
            "candidate_output_digest": self.candidate_output_digest,
            "scorer_process": "separate_post_cutoff_process",
            "implementation_commit": self.implementation_commit,
            "environment_digest": self.environment_digest,
        }


def run_blind_provider(
    provider: Any,
    candidate_snapshot: Path,
    gold_packet: Path,
    output_path: Path,
    *,
    run_id: str = "BLIND-V03-LOCAL",
    implementation_commit: str = "uncommitted",
) -> tuple[dict[str, Any], BlindRun]:
    """Run a provider on input only; the gold path is used only for later digesting."""

    candidate_snapshot = candidate_snapshot.resolve()
    gold_packet = gold_packet.resolve()
    output_path = output_path.resolve()
    if candidate_snapshot == gold_packet or _inside(gold_packet, candidate_snapshot):
        raise ValueError("candidate and gold packet must be physically separate")
    packet = inference_packet(candidate_snapshot, allowed_root=candidate_snapshot)
    filesystem = CandidateFilesystem(candidate_snapshot)
    packet = dict(packet)
    packet["blind_filesystem"] = filesystem.list_files()
    with network_denied():
        prediction = provider.predict(packet)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(prediction, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    environment = f"{platform.python_implementation()} {platform.python_version()} {platform.platform()}"
    record = BlindRun(
        run_id=run_id,
        candidate_snapshot_digest=digest_path(candidate_snapshot),
        gold_packet_digest=digest_path(gold_packet),
        candidate_allowed_root=str(candidate_snapshot),
        candidate_output_digest=digest_path(output_path),
        implementation_commit=implementation_commit,
        environment_digest="sha256:" + hashlib.sha256(environment.encode("utf-8")).hexdigest(),
    )
    return prediction, record


def assert_network_denied() -> None:
    if os.environ.get("RADAR_BENCH_NETWORK") == "denied":
        raise ExternalBlocked("network is disabled during v0.3 blind inference")
