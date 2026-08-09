from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from radar_bench.cli import main
from radar_bench.evaluation.v05 import safety_results
from radar_bench.integrity.v06 import (
    action_space_audit,
    anti_oracle_baselines,
    counterfactual_audit,
    decoy_audit,
    grouped_holdout_audit,
    investigator_freeze_audit,
    metadata_channel_audit,
    real_execution_audit,
    replay_concordance_audit,
    v06_gates,
)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts" / "release-evidence"


class V06IntegrityChallenge(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        episode_artifact = cast(
            dict[str, Any],
            json.loads((EVIDENCE / "investigation-episodes.json").read_text(encoding="utf-8")),
        )
        cls.episodes = cast(list[dict[str, Any]], episode_artifact["episodes"])
        cls.views = cast(list[dict[str, Any]], episode_artifact["candidate_views"])
        metrics = cast(
            dict[str, Any],
            json.loads((EVIDENCE / "experiment-metrics.json").read_text(encoding="utf-8")),
        )
        cls.runs = cast(list[dict[str, Any]], metrics["runs"])
        cls.v05_result = cast(
            dict[str, Any],
            json.loads((ROOT / "artifacts" / "v05-result.json").read_text(encoding="utf-8")),
        )

    def test_action_space_metadata_and_freeze_contracts(self) -> None:
        action_space = action_space_audit(self.views)
        self.assertTrue(action_space["blind"])
        bad_view = copy.deepcopy(self.views[0])
        bad_view["action_space"] = ["RADAR-V04-visible-owner"]
        self.assertFalse(action_space_audit([bad_view])["blind"])

        metadata = metadata_channel_audit(self.episodes, self.views, ROOT)
        self.assertEqual(metadata["metadata_gate_value"], 0.5)
        self.assertEqual(metadata["chance_baseline"], 0.5)
        self.assertEqual(metadata["unavailable_outcome_reported_available"], 40)

        freeze = investigator_freeze_audit(
            ROOT, self.v05_result["hashes"]["implementation"], "60ccc18"
        )
        self.assertTrue(freeze["digest_match"])
        self.assertTrue(freeze["commit_match"])
        self.assertFalse(freeze["tuning_performed"])

    def test_grouped_and_cross_family_holdouts_do_not_cross(self) -> None:
        incident = grouped_holdout_audit(self.episodes, self.runs, group_field="incident")
        family = grouped_holdout_audit(self.episodes, self.runs, group_field="family")
        component = grouped_holdout_audit(self.episodes, self.runs, group_field="component")
        time_period = grouped_holdout_audit(self.episodes, self.runs, group_field="time_period")
        for report in (incident, family, component, time_period):
            self.assertTrue(report["no_group_crosses_split"])
            self.assertEqual(report["group_overlap"], [])
            self.assertFalse(report["tuning_performed"])
            self.assertGreater(report["evaluation"]["cases"], 0)

    def test_decoys_and_anti_oracle_baselines_are_measured(self) -> None:
        decoys = decoy_audit(self.episodes, self.views, ROOT)
        self.assertEqual(decoys["decoy_false_useful_rate"]["value"], 0.2)
        self.assertEqual(decoys["attribution_decoy_false_useful_rate"]["value"], 0.6)

        baselines = anti_oracle_baselines(self.episodes, self.views, ROOT)
        self.assertEqual(
            baselines["random_valid_experiment_selection"]["attribution_resolution"]["value"],
            0.2,
        )
        self.assertEqual(
            baselines["naive_first_component_heuristic"]["attribution_resolution"]["value"],
            0.6,
        )
        self.assertEqual(
            baselines["oracle_availability_only_planner"]["attribution_resolution"]["value"],
            0.0,
        )
        self.assertTrue(baselines["oracle_availability_only_planner"]["uses_only_response_status"])
        self.assertTrue(baselines["random_valid_experiment_selection"]["selected_types"])

    def test_counterfactual_execution_and_concordance_boundaries(self) -> None:
        counterfactual = counterfactual_audit(self.episodes, self.views, ROOT)
        self.assertEqual(counterfactual["irrelevant_invariance"]["value"], 1.0)
        self.assertEqual(counterfactual["causal_sensitivity"]["value"], 1.0)

        real_execution = real_execution_audit(ROOT, self.episodes)
        self.assertEqual(real_execution["status"], "BLOCKED_EXTERNAL")
        self.assertIsNone(real_execution["correctness"]["value"])
        self.assertEqual(replay_concordance_audit(real_execution)["status"], "NOT_EVALUABLE")
        self.assertEqual(
            replay_concordance_audit({"status": "COMPLETED"})["status"], "NOT_EVALUABLE"
        )

        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            manifest = temporary_root / "corpus" / "v0.6" / "execution-subset.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}\n", encoding="utf-8")
            self.assertIn(
                "unreviewed external manifest",
                real_execution_audit(temporary_root, self.episodes)["reason"],
            )

    def test_gate_report_preserves_failed_and_not_evaluable_states(self) -> None:
        v05_metrics = self.v05_result["lanes"]["B_deterministic_heuristic"]["metrics"]
        safety = safety_results(self.episodes, self.runs)
        action_space = action_space_audit(self.views)
        metadata = metadata_channel_audit(self.episodes, self.views, ROOT)
        decoys = decoy_audit(self.episodes, self.views, ROOT)
        baselines = anti_oracle_baselines(self.episodes, self.views, ROOT)
        counterfactual = counterfactual_audit(self.episodes, self.views, ROOT)
        real_execution = real_execution_audit(ROOT, self.episodes)
        concordance = replay_concordance_audit(real_execution)
        freeze = investigator_freeze_audit(
            ROOT, self.v05_result["hashes"]["implementation"], "60ccc18"
        )
        gates = v06_gates(
            action_space,
            metadata,
            decoys,
            baselines,
            counterfactual,
            real_execution,
            concordance,
            v05_metrics,
            safety,
            freeze,
        )
        self.assertFalse(gates["integrity_validated"])
        self.assertEqual(gates["decision"], "STOP_BENCHMARK_AND_FIX_ORACLE")
        self.assertEqual(gates["checks"]["real_execution_correctness"]["status"], "not_evaluable")

        failed_action_space = copy.deepcopy(action_space)
        failed_action_space["blind"] = False
        failed = v06_gates(
            failed_action_space,
            metadata,
            decoys,
            baselines,
            counterfactual,
            real_execution,
            concordance,
            v05_metrics,
            safety,
            freeze,
        )
        self.assertEqual(failed["checks"]["action_space_blindness"]["status"], "fail")

    def test_cli_validates_v06_artifact_set(self) -> None:
        self.assertEqual(main(["validate-v06-integrity"]), 0)
