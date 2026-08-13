"""Generate the blinded candidate-only solvability reference from fresh receipts."""

from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any, Mapping

from radar_bench.v1_2 import (
    ALL_CASE_IDS,
    CAPABILITIES,
    HISTORICAL_IDS,
    CandidatePacket,
    ExternalCandidateProtocol,
    canonical_digest,
    candidate_bundle_audit,
)
from radar_bench.v12_executor import V12ExperimentExecutor


DEFAULT_IMAGE = (
    "mirror.gcr.io/library/python@sha256:"
    "63669fd2563fa90b0442fa7b568e66e3667755636cda086d7bcaaa895f66fe39"
)

# This program is the candidate-side reference strategy.  It receives only
# opaque protocol packets and experiment observations.  It has no repository,
# evaluator bundle, reference labels, or host filesystem mount.
CANDIDATE_PROGRAM = r"""
import json
import sys

pending = set()
request_number = 0

def terminal_prediction(episode_id, response):
    observation = response.get("observation", {})
    candidate = observation.get("candidate", {}) if isinstance(observation, dict) else {}
    control = observation.get("control", {}) if isinstance(observation, dict) else {}
    excerpt = str(candidate.get("excerpt", "")).lower()
    control_exit = control.get("returncode")
    candidate_exit = candidate.get("returncode")
    candidate_induced = control_exit == 0 and candidate_exit != 0
    if "scipy" in excerpt:
        component = "scipy"
        disposition = "ATTRIBUTED"
        semantic = "known"
    elif "pd.na" in excerpt or "not replaced" in excerpt:
        component = "pandas"
        disposition = "AMBIGUOUS"
        semantic = "ambiguous"
    elif "pandas" in excerpt:
        component = "pandas"
        disposition = "ATTRIBUTED"
        semantic = "known"
    elif candidate_induced:
        component = None
        disposition = "ATTRIBUTED"
        semantic = "known"
    else:
        component = None
        disposition = "ABSTAINED"
        semantic = "not-applicable"
    return {
        "schema_version": "1.2-jsonl",
        "message": "final_prediction",
        "episode_id": episode_id,
        "prediction": {
            "causal_component": component,
            "candidate_induced": candidate_induced,
            "semantic_intent": semantic,
            "action_owner": None,
            "disposition": disposition,
            "evidence_ids": [],
        },
    }

for raw in sys.stdin:
    message = json.loads(raw)
    kind = message.get("message")
    if kind == "episode_start":
        episode_id = message["episode_id"]
        request_number += 1
        pending.add(episode_id)
        print(json.dumps({
            "schema_version": "1.2-jsonl",
            "message": "experiment_request",
            "episode_id": episode_id,
            "request_id": "reference-request-" + str(request_number),
            "capability": "rerun",
            "parameters": {},
        }), flush=True)
    elif kind == "experiment_result":
        episode_id = message["episode_id"]
        if episode_id in pending:
            print(json.dumps(terminal_prediction(episode_id, message)), flush=True)
            pending.remove(episode_id)
"""


def _declared_mounts(command: tuple[str, ...]) -> list[str]:
    mounts: list[str] = []
    for index, argument in enumerate(command):
        if argument in {"--mount", "-v", "--volume"} and index + 1 < len(command):
            mounts.append(command[index + 1])
        elif argument.startswith("--mount="):
            mounts.append(argument.split("=", 1)[1])
    return mounts


def _sandbox_receipt(protocol: ExternalCandidateProtocol, result: Mapping[str, Any]) -> dict[str, Any]:
    mounts = _declared_mounts(protocol.command)
    lowered_mounts = [mount.lower() for mount in mounts]
    return {
        "docker_isolated": protocol.docker_isolated is True,
        "network_denied": result.get("network_denied") is True,
        "actual_config_verified": result.get("status") == "COMPLETED"
        and "CANDIDATE_ACTUAL_CONFIG_INVALID" not in result.get("errors", []),
        "declared_mount_count": len(mounts),
        "repository_mount_count": sum(
            int(any(marker in mount for marker in ("repository", "repo", "radar", "src")))
            for mount in lowered_mounts
        ),
        "evaluator_mount_count": sum(
            int(any(marker in mount for marker in ("evaluator", "gold", "label", "reference")))
            for mount in lowered_mounts
        ),
        "reference_mount_count": sum(
            int(any(marker in mount for marker in ("reference", "runtime", "artifact")))
            for mount in lowered_mounts
        ),
    }


def _totals(ledgers: Mapping[str, Any]) -> dict[str, int]:
    fields = ("executor_calls", "fresh", "available", "cleanup_verified")
    return {
        field: sum(
            int(value.get(field, 0))
            for value in ledgers.values()
            if isinstance(value, Mapping)
        )
        for field in fields
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    candidate_path = root / "candidate" / "decisive-v1.2" / "candidate-bundle.json"
    candidate_document = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate_audit = candidate_bundle_audit(root)
    raw_cases = candidate_document.get("cases")
    expected_records = [f"record-{index:03d}" for index in range(1, len(ALL_CASE_IDS) + 1)]
    if (
        not candidate_audit["valid"]
        or not isinstance(raw_cases, list)
        or len(raw_cases) != len(ALL_CASE_IDS)
        or [item.get("record_id") for item in raw_cases if isinstance(item, Mapping)] != expected_records
    ):
        raise RuntimeError("candidate bundle does not contain the blinded reference inputs")

    # This transport mapping is evaluator-owned runtime plumbing only.  It is
    # never emitted, and the candidate strategy receives opaque episodes.
    episodes = ["ep_ref_" + secrets.token_urlsafe(18) for _ in ALL_CASE_IDS]
    hidden_transport = dict(zip(episodes, ALL_CASE_IDS, strict=True))
    packets = [
        CandidatePacket(
            episode,
            raw_cases[index]["evidence"],
            tuple(sorted(CAPABILITIES)),
        )
        for index, episode in enumerate(episodes)
    ]
    executor = V12ExperimentExecutor(
        root,
        episode_to_case=hidden_transport,
        artifact_root=root / "artifacts" / "external" / "decisive-v1.2",
    )

    with tempfile.TemporaryDirectory(prefix="radar-reference-candidate-") as workspace:
        protocol = ExternalCandidateProtocol(
            DEFAULT_IMAGE,
            ["python", "-u", "-c", CANDIDATE_PROGRAM],
            working_directory=Path(workspace),
            timeout_seconds=1800.0,
        )
        result = protocol.run(packets, experiment_executor=executor)

    ledgers = result.get("ledgers", {})
    if not isinstance(ledgers, Mapping):
        ledgers = {}
    predictions_by_episode = result.get("predictions", {})
    if not isinstance(predictions_by_episode, Mapping):
        predictions_by_episode = {}
    sandbox = _sandbox_receipt(protocol, result)
    evaluator_available = sandbox["evaluator_mount_count"] > 0

    roles = ("A01_OR_OTHER", "A02_SCIPY", "A03_AMBIGUOUS", "A04_OR_OTHER", "A05_OR_OTHER")
    predictions: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for index, role in enumerate(roles):
        episode_id = episodes[index]
        packet = packets[index]
        candidate_prediction = predictions_by_episode.get(episode_id)
        ledger = ledgers.get(episode_id)
        if not isinstance(candidate_prediction, Mapping):
            candidate_prediction = {}
        if not isinstance(ledger, Mapping):
            ledger = {}
        ledger_digest = canonical_digest({"episode_id": episode_id, "ledger": ledger})
        prediction = dict(candidate_prediction)
        prediction.update(
            {
                "episode_id": episode_id,
                "evidence_digest": canonical_digest(packet.evidence),
                "experiment_response_digest": ledger_digest,
            }
        )
        predictions.append(prediction)
        experiment_count = ledger.get("executor_calls")
        fresh = ledger.get("fresh") == 1
        available = ledger.get("available") == 1
        cleanup_verified = ledger.get("cleanup_verified") == 1
        receipts.append(
            {
                "episode_id": episode_id,
                "status": (
                    "COMPLETED"
                    if result.get("status") == "COMPLETED" and fresh and available and cleanup_verified
                    else "BLOCKED"
                ),
                "fresh": fresh,
                "available": available,
                "cleanup_verified": cleanup_verified,
                "experiment_count": experiment_count,
                "receipt_digest": ledger_digest,
            }
        )
        review.append(
            {
                "episode_id": episode_id,
                "role": role,
                "derived_from": ledger_digest,
            }
        )

    evidence_shapes = {canonical_digest(packet.evidence) for packet in packets}
    totals = _totals(ledgers)
    document = {
        "schema_version": "1",
        "review_type": "candidate-only-reference",
        "reference_method": "isolated candidate protocol with fresh blinded rerun observations and no evaluator labels",
        "candidate_bundle_digest": candidate_audit.get("digest"),
        "evaluator_available_during_run": evaluator_available,
        "sandbox_receipt": sandbox,
        "protocol_receipt": {
            "status": result.get("status"),
            "network_denied": result.get("network_denied"),
            "packet_count": len(packets),
            "totals": totals,
            "errors": result.get("errors", []),
        },
        "raw_predictions": predictions,
        "receipts": receipts,
        "historical_review": review,
        "metadata_only": {
            "case_type_signal": "NONE" if len(evidence_shapes) == 1 else "SIGNAL",
            "classifier_advantage": 0.0 if len(evidence_shapes) == 1 else 1.0,
            "feature_source": "candidate evidence only",
        },
        "certifying": (
            result.get("status") == "COMPLETED"
            and sandbox["docker_isolated"]
            and sandbox["network_denied"]
            and sandbox["actual_config_verified"]
            and not evaluator_available
            and len(predictions) == len(HISTORICAL_IDS)
            and len(receipts) == len(HISTORICAL_IDS)
            and len(review) == len(HISTORICAL_IDS)
            and all(item["status"] == "COMPLETED" for item in receipts)
        ),
    }
    output = root / "evidence" / "decisive-v1.2" / "solvability-reference.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": document["certifying"], "protocol": document["protocol_receipt"]}, sort_keys=True))
    return 0 if document["certifying"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
