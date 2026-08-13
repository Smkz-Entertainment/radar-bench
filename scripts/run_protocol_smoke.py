"""Run a real Docker candidate-protocol smoke with one experiment round trip."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping

from radar_bench.v1_2 import (
    ALL_CASE_IDS,
    CAPABILITIES,
    CandidatePacket,
    ExternalCandidateProtocol,
    generate_episode_ids,
)
from radar_bench.v12_executor import V12ExperimentExecutor


DEFAULT_IMAGE = (
    "mirror.gcr.io/library/python@sha256:"
    "63669fd2563fa90b0442fa7b568e66e3667755636cda086d7bcaaa895f66fe39"
)
CANDIDATE_PROGRAM = """
import json
import sys

requested = False
pending_episode = None

def final_prediction(episode_id):
    return {
        "schema_version": "1.2-jsonl",
        "message": "final_prediction",
        "episode_id": episode_id,
        "prediction": {
            "causal_component": None,
            "candidate_induced": False,
            "semantic_intent": "not-applicable",
            "action_owner": None,
            "disposition": "ABSTAINED",
            "evidence_ids": [],
        },
    }

for raw in sys.stdin:
    message = json.loads(raw)
    if message.get("message") == "episode_start":
        episode_id = message["episode_id"]
        if not requested:
            requested = True
            pending_episode = episode_id
            print(json.dumps({
                "schema_version": "1.2-jsonl",
                "message": "experiment_request",
                "episode_id": episode_id,
                "request_id": "smoke-request-1",
                "capability": "inspect_dependency_graph",
                "parameters": {},
            }), flush=True)
        else:
            print(json.dumps(final_prediction(episode_id)), flush=True)
    elif message.get("message") == "experiment_result" and pending_episode is not None:
        print(json.dumps(final_prediction(pending_episode)), flush=True)
        pending_episode = None
"""


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    artifact_root = args.artifact_root.resolve() if args.artifact_root is not None else None
    candidate = json.loads(
        (root / "candidate/decisive-v1.2/candidate-bundle.json").read_text(
            encoding="utf-8"
        )
    )
    raw_cases = candidate.get("cases")
    if not isinstance(raw_cases, list) or len(raw_cases) != len(ALL_CASE_IDS):
        raise SystemExit("candidate bundle does not contain 25 cases")
    mapping = generate_episode_ids()
    packets = [
        CandidatePacket(
            mapping[case_id],
            raw_cases[index]["evidence"],
            tuple(sorted(CAPABILITIES)),
        )
        for index, case_id in enumerate(ALL_CASE_IDS)
    ]
    executor = V12ExperimentExecutor(
        root,
        episode_to_case={packet.episode_id: "RADAR-V07-T01" for packet in packets},
        artifact_root=artifact_root,
    )
    with tempfile.TemporaryDirectory(prefix="radar-protocol-smoke-") as workspace:
        protocol = ExternalCandidateProtocol(
            args.image,
            ["python", "-u", "-c", CANDIDATE_PROGRAM],
            working_directory=Path(workspace),
        )
        result = protocol.run(packets, experiment_executor=executor)
    ledgers = result.get("ledgers", {})
    totals = _totals(ledgers if isinstance(ledgers, Mapping) else {})
    round_trip = {
        "status": (
            "PASS"
            if totals["executor_calls"] >= 1
            and totals["fresh"] >= 1
            and totals["available"] >= 1
            and totals["cleanup_verified"] >= 1
            else "BLOCKED"
        ),
        "required": "at least one fresh available experiment with verified cleanup",
        "totals": totals,
    }
    document = {
        "status": (
            "PASS"
            if result.get("status") == "COMPLETED"
            and result.get("network_denied") is True
            and round_trip["status"] == "PASS"
            else "BLOCKED"
        ),
        "image": args.image,
        "packet_count": len(packets),
        "protocol": {
            "status": result.get("status"),
            "network_denied": result.get("network_denied"),
            "exit_code": result.get("exit_code"),
            "errors": result.get("errors", []),
            "experiment_round_trip": round_trip,
            "ledgers": ledgers,
        },
        "candidate": {
            "gold_visible": False,
            "repository_visible": False,
            "candidate_argv": ["python", "-u", "-c", "<smoke-program>"],
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": document["status"], "protocol": document["protocol"]}, sort_keys=True))
    return 0 if document["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
