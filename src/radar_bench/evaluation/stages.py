"""Reproducible v0.3 freeze metadata and stage boundaries."""

from __future__ import annotations

import hashlib
import platform
import sys
from pathlib import Path
from typing import Any


def digest_tree(root: Path, patterns: tuple[str, ...]) -> str:
    hasher = hashlib.sha256()
    paths = [path for pattern in patterns for path in root.glob(pattern) if path.is_file()]
    for path in sorted(set(paths)):
        hasher.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
        hasher.update(path.read_bytes())
    return "sha256:" + hasher.hexdigest()


def build_freeze_manifest(
    root: Path, *, invocation: list[str], implementation_commit: str
) -> dict[str, Any]:
    corpus_digest = digest_tree(root, ("corpus/v0.3/**/*.json", "corpus/v0.3/**/*.csv"))
    implementation_digest = digest_tree(
        root,
        (
            "src/radar_bench/**/*.py",
            "schema/*v0.3*.json",
            "scripts/seed_v03_plan.py",
        ),
    )
    environment = f"{sys.implementation.name} {platform.python_version()} {platform.platform()}"
    environment_digest = "sha256:" + hashlib.sha256(environment.encode("utf-8")).hexdigest()
    return {
        "schema_version": "0.3",
        "stage": "C_freeze_before_hidden_evaluation",
        "implementation_commit": implementation_commit,
        "corpus_digest": corpus_digest,
        "implementation_digest": implementation_digest,
        "environment_digest": environment_digest,
        "cli_invocation": invocation,
        "network_policy": "denied_for_candidate",
        "gold_labels_available_to_candidate": False,
        "tuning_after_labels": False,
        "stages": {
            "A": {"status": "completed", "scope": "deterministic development baseline and error taxonomy"},
            "B": {"status": "not_run", "scope": "development-only deterministic improvements"},
            "C": {"status": "blocked", "scope": "hidden freeze and independent post-cutoff scoring"},
        },
    }
