from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any

from radar_bench.cli import main
from radar_bench.evaluation.v05 import (
    ablation_summary,
    lane_metrics,
    resolution_at_k,
    safety_results,
    v05_gates,
)
from radar_bench.investigation.v01 import (
    HeuristicInvestigator,
    ReplayOracle,
    build_candidate_view,
    build_episode,
    canonical_digest,
    validate_episode,
    validate_experiment_request,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "v0.4" / "pilot"


class V05Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((PILOT / "records").glob("*.json"))
            if "admitted" == json.loads(path.read_text(encoding="utf-8"))["admission_state"]
        ]
        cls.episodes = [build_episode(record, root=ROOT) for record in cls.records]
        cls.views = [build_candidate_view(episode) for episode in cls.episodes]

    def _runs(self) -> list[dict[str, Any]]:
        oracle = ReplayOracle(self.episodes, root=ROOT)
        investigator = HeuristicInvestigator(root=ROOT)
        return [investigator.run(view, oracle.execute) for view in self.views]

    def test_episode_is_temporally_valid_and_candidate_view_is_blind(self) -> None:
        for episode, view in zip(self.episodes, self.views):
            self.assertEqual(validate_episode(episode, root=ROOT), [])
            self.assertNotIn("gold", json.dumps(view))
            self.assertNotIn("historical_evidence", json.dumps(view))
            self.assertTrue(
                set(episode["candidate_snapshot"]["visible_evidence_ids"]).isdisjoint(
                    episode["hidden_gold_packet"]["evidence_ids"]
                )
            )
        self.assertEqual(canonical_digest({"b": 1, "a": 2}), canonical_digest({"a": 2, "b": 1}))

    def test_episode_validation_rejects_temporal_and_visibility_errors(self) -> None:
        invalid = copy.deepcopy(self.episodes[0])
        invalid["tcut"] = "2024-01-01T00:00:00Z"
        invalid["candidate_snapshot"]["visible_evidence_ids"] = invalid["hidden_gold_packet"]["evidence_ids"][:1]
        errors = validate_episode(invalid, root=ROOT)
        self.assertTrue(any("tcut must not precede" in error for error in errors))
        self.assertIn("candidate and hidden evidence ids must be disjoint", errors)
        invalid["action_space"] = ["rerun"]
        self.assertTrue(validate_episode(invalid, root=ROOT))

    def test_experiment_request_semantics_are_fail_closed(self) -> None:
        valid = {
            "schema_version": "0.1", "request_id": "REQ-TEST", "episode_id": self.episodes[0]["episode_id"],
            "experiment_id": "EXP-TEST", "type": "version_swap", "hypothesis": "control differs",
            "target_component": "upstream", "changed_variable": "revision", "control": "a", "candidate": "b",
            "limits": {"network_policy": "denied", "timeout_seconds": 10, "memory_mb": 64, "output_mb": 1},
        }
        self.assertEqual(validate_experiment_request(valid, root=ROOT), [])
        invalid = copy.deepcopy(valid)
        invalid["control"] = invalid["candidate"]
        invalid["changed_variable"] = None
        self.assertEqual(len(validate_experiment_request(invalid, root=ROOT)), 2)
        self.assertTrue(validate_experiment_request({"type": "unknown"}, root=ROOT))

    def test_oracle_replays_causal_external_safety_and_budget_paths(self) -> None:
        oracle = ReplayOracle(self.episodes, root=ROOT)
        baseline = {
            "schema_version": "0.1", "request_id": "REQ-B", "episode_id": self.episodes[0]["episode_id"],
            "experiment_id": "EXP-B", "type": "baseline_check", "hypothesis": "baseline is stable",
            "limits": {"network_policy": "denied", "timeout_seconds": 10, "memory_mb": 64, "output_mb": 1},
        }
        self.assertEqual(oracle.execute(baseline)["status"], "AVAILABLE")
        exp = next(item for item in self.episodes if item["gold"]["attributability_class"] == "EXPERIMENTALLY_ATTRIBUTABLE")
        causal = copy.deepcopy(baseline)
        causal.update({"request_id": "REQ-C", "episode_id": exp["episode_id"], "experiment_id": "EXP-C", "type": "version_swap", "hypothesis": "revision causes failure", "target_component": "upstream", "changed_variable": "revision", "control": "old", "candidate": "new"})
        response = oracle.execute(causal)
        self.assertEqual(response["result"]["outcome"], "CANDIDATE_SPECIFIC")
        external = next(item for item in self.episodes if item["gold"]["attributability_class"] == "EXTERNALLY_DEPENDENT")
        external_request = copy.deepcopy(causal)
        external_request.update({"request_id": "REQ-X", "episode_id": external["episode_id"], "experiment_id": "EXP-X"})
        self.assertEqual(oracle.execute(external_request)["result"]["outcome"], "CONFOUNDING_DEPENDENCY")
        safety = next(item for item in self.episodes if item["corpus_kind"] == "safety")
        safety_request = copy.deepcopy(baseline)
        safety_request.update({"request_id": "REQ-S", "episode_id": safety["episode_id"], "experiment_id": "EXP-S"})
        self.assertEqual(oracle.execute(safety_request)["result"]["outcome"], "BASELINE_NOT_STABLE")
        self.assertEqual(oracle.execute({**baseline, "episode_id": "RADAR-V05-E-UNKNOWN", "request_id": "REQ-U"})["status"], "UNAVAILABLE")
        for index in range(2, 7):
            repeated = {**baseline, "request_id": f"REQ-R{index}", "experiment_id": f"EXP-R{index}"}
            response = oracle.execute(repeated)
        self.assertEqual(response["status"], "INVALID")

    def test_investigator_runs_terminal_paths_and_records_ledger(self) -> None:
        runs = self._runs()
        self.assertEqual(len(runs), 60)
        self.assertEqual(sum(run["terminal"]["state"] == "CAUSALLY_ATTRIBUTED" for run in runs), 12)
        self.assertTrue(all(run["candidate_visible_only"] for run in runs))
        self.assertTrue(all(run["phase_trace"][0] == "OBSERVE" for run in runs))
        invalid_run = HeuristicInvestigator(root=ROOT).run(self.views[0], lambda request: {"status": "INVALID", "request_id": request["request_id"]})
        self.assertEqual(invalid_run["terminal"]["state"], "INVALID_INVESTIGATION")

    def test_metrics_resolution_safety_gates_and_ablation(self) -> None:
        runs = self._runs()
        metrics = lane_metrics(self.episodes, runs)
        safety = safety_results(self.episodes, runs)
        self.assertEqual(metrics["candidate_induced"]["precision"]["value"], 1.0)
        self.assertEqual(metrics["action_owner"]["precision"]["value"], 1.0)
        self.assertEqual(metrics["experimentally_attributable_action_owner"]["precision"]["value"], 1.0)
        self.assertEqual(safety["abstention_recall"]["value"], 1.0)
        self.assertEqual(resolution_at_k(self.episodes, runs)["ks"]["3"]["value"], 1.0)
        gates = v05_gates(metrics, safety)
        self.assertTrue(gates["continue_pilot"])
        killed = copy.deepcopy(metrics)
        killed["experimentally_attributable_action_owner"]["precision"]["value"] = 0.0
        self.assertTrue(v05_gates(killed, safety)["kill_criteria_triggered"])
        worsened = copy.deepcopy(safety)
        worsened["abstention_recall"]["value"] = 0.5
        self.assertTrue(v05_gates(metrics, worsened)["kill_criteria_triggered"])
        self.assertIn("lanes", ablation_summary({"B": metrics}))

    def test_cli_validates_generated_episode_artifact(self) -> None:
        self.assertEqual(main(["validate-v05-episodes"]), 0)
