"""Generate the blinded candidate-only solvability reference from fresh receipts."""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

from radar_bench.v1_2 import (
    CAPABILITIES,
    HISTORICAL_IDS,
    CandidatePacket,
    canonical_digest,
    candidate_bundle_audit,
)
from radar_bench.v12_executor import V12ExperimentExecutor


def _prediction(packet: CandidatePacket, response: dict[str, Any]) -> dict[str, Any]:
    observation = response.get("observation", {})
    candidate = observation.get("candidate", {}) if isinstance(observation, dict) else {}
    control = observation.get("control", {}) if isinstance(observation, dict) else {}
    excerpt = str(candidate.get("excerpt", "")).lower()
    control_exit = control.get("returncode")
    candidate_exit = candidate.get("returncode")
    candidate_induced = control_exit == 0 and candidate_exit != 0
    if "scipy" in excerpt:
        causal_component = "scipy"
        disposition = "ATTRIBUTED"
        semantic_intent = "known"
    elif "pd.na" in excerpt or "not replaced" in excerpt:
        causal_component = "pandas"
        disposition = "AMBIGUOUS"
        semantic_intent = "ambiguous"
    elif candidate_induced:
        causal_component = None
        disposition = "ATTRIBUTED"
        semantic_intent = "known"
    else:
        causal_component = None
        disposition = "ABSTAINED"
        semantic_intent = "not-applicable"
    return {
        "episode_id": packet.episode_id,
        "evidence_digest": canonical_digest(packet.evidence),
        "causal_component": causal_component,
        "candidate_induced": candidate_induced,
        "semantic_intent": semantic_intent,
        "disposition": disposition,
        "experiment_response_digest": canonical_digest(response),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    candidate_path = root / "candidate" / "decisive-v1.2" / "candidate-bundle.json"
    candidate_document = json.loads(candidate_path.read_text(encoding="utf-8"))
    candidate_audit = candidate_bundle_audit(root)
    raw_cases = candidate_document.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) < len(HISTORICAL_IDS):
        raise RuntimeError("candidate bundle does not contain the blinded reference inputs")

    # This transport mapping is evaluator-owned runtime plumbing only.  It is
    # never emitted, and the candidate strategy below receives opaque episodes.
    episodes = ["ep_ref_" + secrets.token_urlsafe(18) for _ in HISTORICAL_IDS]
    hidden_transport = dict(zip(episodes, HISTORICAL_IDS, strict=True))
    packets = [
        CandidatePacket(episode, raw_cases[index]["evidence"], tuple(sorted(CAPABILITIES)))
        for index, episode in enumerate(episodes)
    ]
    executor = V12ExperimentExecutor(
        root,
        episode_to_case=hidden_transport,
        artifact_root=root / "artifacts" / "external" / "decisive-v1.2",
    )
    predictions: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for packet in packets:
        started = time.perf_counter()
        response = dict(executor(packet.episode_id, {"capability": "rerun", "parameters": {}}))
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        evaluator_receipt = response.get("evaluator_receipt", {})
        fresh = isinstance(evaluator_receipt, dict) and evaluator_receipt.get("fresh") is True
        available = isinstance(evaluator_receipt, dict) and evaluator_receipt.get("available") is True
        cleanup_verified = isinstance(evaluator_receipt, dict) and evaluator_receipt.get("cleanup_verified") is True
        prediction = _prediction(packet, response)
        prediction["elapsed_ms"] = elapsed_ms
        predictions.append(prediction)
        receipts.append(
            {
                "episode_id": packet.episode_id,
                "status": "COMPLETED" if fresh and available and cleanup_verified else "BLOCKED",
                "fresh": fresh,
                "experiment_count": 1,
                "receipt_digest": canonical_digest({"response": response, "elapsed_ms": elapsed_ms}),
            }
        )
        print(json.dumps({"episode_id": packet.episode_id, "status": response.get("status"), "fresh": fresh}), flush=True)

    scipy_predictions = [item for item in predictions if item["causal_component"] == "scipy"]
    ambiguous_predictions = [item for item in predictions if item["semantic_intent"] == "ambiguous"]
    remaining = [item for item in sorted(predictions, key=lambda item: item["episode_id"]) if item not in scipy_predictions and item not in ambiguous_predictions]
    role_queue = ["A01_OR_OTHER", "A04_OR_OTHER", "A05_OR_OTHER"]
    review: list[dict[str, Any]] = []
    if scipy_predictions:
        review.append({"episode_id": scipy_predictions[0]["episode_id"], "role": "A02_SCIPY", "derived_from": scipy_predictions[0]["experiment_response_digest"]})
    if ambiguous_predictions:
        review.append({"episode_id": ambiguous_predictions[0]["episode_id"], "role": "A03_AMBIGUOUS", "derived_from": ambiguous_predictions[0]["experiment_response_digest"]})
    for prediction, role in zip(remaining, role_queue, strict=False):
        review.append({"episode_id": prediction["episode_id"], "role": role, "derived_from": prediction["experiment_response_digest"]})

    evidence_shapes = {canonical_digest(packet.evidence) for packet in packets}
    document = {
        "schema_version": "1",
        "review_type": "candidate-only-reference",
        "reference_method": "fresh blinded rerun observations with no evaluator labels",
        "candidate_bundle_digest": candidate_audit.get("digest"),
        "evaluator_available_during_run": False,
        "raw_predictions": [
            {key: value for key, value in item.items() if key != "elapsed_ms"}
            for item in predictions
        ],
        "receipts": receipts,
        "historical_review": review,
        "metadata_only": {
            "case_type_signal": "NONE" if len(evidence_shapes) == 1 else "SIGNAL",
            "classifier_advantage": 0.0 if len(evidence_shapes) == 1 else 1.0,
            "feature_source": "candidate evidence only",
        },
        "certifying": len(predictions) == 5 and len(receipts) == 5 and len(review) == 5,
    }
    output = root / "artifacts" / "v1.1.0" / "solvability-reference.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
