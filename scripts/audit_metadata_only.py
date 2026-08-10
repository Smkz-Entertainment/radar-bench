"""Audit whether candidate-visible metadata carries safety-family signal."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

FEATURE_KEYS = ("schema_version", "corpus_kind", "plausible_components")
SUITE_ROOT = Path("corpus/v1.0.1/safety-twins")


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _metadata(view: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields available to a candidate and remove case identity."""

    return {key: view.get(key) for key in FEATURE_KEYS}


def audit(root: Path) -> dict[str, Any]:
    suite_root = root / SUITE_ROOT
    labels_path = suite_root / "evaluator-labels.json"
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    cases = labels["cases"]
    projected: list[dict[str, Any]] = []
    for case_id in sorted(cases):
        view_path = suite_root / "views" / f"{case_id.rsplit('-', 1)[-1].replace('T', 'T')}.json"
        if not view_path.is_file():
            raise FileNotFoundError(f"missing candidate view for {case_id}")
        view = json.loads(view_path.read_text(encoding="utf-8"))
        projected.append(_metadata(view))

    feature_digests = [_digest(item) for item in projected]
    family_counts = Counter(item["fault_family"] for item in cases.values())
    case_count = len(projected)
    family_count = len(family_counts)
    majority_accuracy = max(family_counts.values()) / case_count if case_count else 0.0
    uniform_chance = 1.0 / family_count if family_count else 0.0
    identical_features = len(set(feature_digests)) == 1
    return {
        "status": "PASS" if identical_features and case_count == 20 else "FAIL",
        "method": "Evaluator-side projection of candidate-visible metadata with case identity, digests, paths, and labels excluded from features.",
        "case_count": case_count,
        "feature_keys": list(FEATURE_KEYS),
        "feature_digest_classes": len(set(feature_digests)),
        "feature_digest": feature_digests[0] if feature_digests else None,
        "metadata_predictive_signal": "NONE" if identical_features else "PRESENT",
        "fault_family_count": family_count,
        "fault_family_counts": dict(sorted(family_counts.items())),
        "uniform_random_chance": uniform_chance,
        "majority_prior_accuracy": majority_accuracy,
        "prior_only_accuracy_excess_over_uniform": majority_accuracy - uniform_chance,
        "held_out_fault_families": labels.get("held_out_fault_families", []),
        "source_digests": {
            "evaluator_labels": _file_digest(labels_path),
            "candidate_views": _digest(feature_digests),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.root.resolve())
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    else:
        print(encoded, end="")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
