from __future__ import annotations

import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from radar_bench.cli import main
from radar_bench.corpus.v04 import (
    validate_v04_record,
    validate_v04_records,
    v04_early_gates,
    v04_summary,
)
from radar_bench.evaluation.v03 import score_v03
from radar_bench.models.prediction import make_prediction

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "v0.4" / "pilot"


class V04Contracts(unittest.TestCase):
    def _records(self) -> list[dict]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((PILOT / "records").glob("*.json"))
        ]

    def test_pilot_records_are_admissible_or_explicitly_blocked(self) -> None:
        records = self._records()
        self.assertEqual(validate_v04_records(records, root=ROOT), [])
        summary = v04_summary(records)
        self.assertEqual(summary["admitted_attribution"], 20)
        self.assertEqual(summary["admitted_safety"], 40)
        self.assertTrue(summary["pilot_success"])
        self.assertEqual(summary["states"], {"admitted": 60, "blocked": 5})
        self.assertEqual(
            summary["rejection_reasons"], {"NO_TEMPORAL_BOUNDARY": 5}
        )

    def test_temporal_boundary_is_fail_closed(self) -> None:
        record = next(
            item
            for item in self._records()
            if item["record_id"] == "RADAR-V04-A04"
        )
        invalid = json.loads(json.dumps(record))
        item = next(
            item
            for item in invalid["source_chain"]
            if item["available_after_cutoff"]
        )
        item["published_at"] = invalid["source_cutoff"]
        self.assertTrue(
            any("not after source_cutoff" in error for error in validate_v04_record(invalid, root=ROOT))
        )

    def test_cli_and_early_gate_report(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["validate-v04-corpus", "--json"]), 0)
        self.assertIn('"admitted_attribution": 20', output.getvalue())
        run = json.loads((PILOT / "run.json").read_text(encoding="utf-8"))
        self.assertFalse(run["early_gates"]["continue_mining"])
        self.assertEqual(run["early_gates"]["checks"]["abstention_recall"]["status"], "pass")
        self.assertEqual(run["early_gates"]["checks"]["action_owner_precision"]["status"], "fail")
        self.assertEqual(run["codex"], "not_run_by_design")

    def test_gold_b_is_excluded_from_strict_owner_scoring(self) -> None:
        record = json.loads(
            (PILOT / "records" / "RADAR-V04-A02.json").read_text(encoding="utf-8")
        )
        self.assertEqual(record["gold_level"], "Gold-B")
        self.assertFalse(record["label"]["action_owner_scored"])

    def test_early_gates_are_fail_closed_for_missing_metrics(self) -> None:
        gates = v04_early_gates({"metrics": {}})
        self.assertFalse(gates["continue_mining"])
        self.assertEqual(
            gates["checks"]["candidate_induced_precision"]["status"],
            "not_evaluable",
        )

    def test_validator_checks_admission_state_contract(self) -> None:
        admitted = next(
            item
            for item in self._records()
            if item["record_id"] == "RADAR-V04-A01"
        )
        invalid = json.loads(json.dumps(admitted))
        invalid["rejection_reason"] = "SOURCE_UNAVAILABLE"
        invalid["audit"]["review_status"] = "blocked"
        invalid["gold_level"] = None
        invalid["label"] = None
        errors = validate_v04_record(invalid, root=ROOT)
        self.assertIn("admitted records cannot have a rejection reason", errors)
        self.assertIn("admitted records require independent review", errors)
        self.assertIn("admitted records require a gold level and label", errors)
        invalid["candidate_snapshot"]["cutoff_only"] = False
        invalid["gold_packet"]["post_cutoff_only"] = False
        invalid["gold_packet"]["scorer_only"] = False
        schema_errors = validate_v04_record(invalid, root=ROOT)
        self.assertIn("$.candidate_snapshot.cutoff_only: expected constant True", schema_errors)

        gold_b = next(
            item
            for item in self._records()
            if item["record_id"] == "RADAR-V04-A02"
        )
        gold_b = json.loads(json.dumps(gold_b))
        gold_b["label"]["action_owner_scored"] = True
        self.assertIn(
            "Gold-B cannot enter strict action-owner scoring",
            validate_v04_record(gold_b, root=ROOT),
        )

    def test_validator_checks_rejections_controls_and_duplicates(self) -> None:
        blocked = next(
            item
            for item in self._records()
            if item["record_id"] == "RADAR-V04-A11"
        )
        invalid_blocked = json.loads(json.dumps(blocked))
        invalid_blocked["rejection_reason"] = None
        self.assertIn(
            "blocked records require a source or temporal blocker",
            validate_v04_record(invalid_blocked, root=ROOT),
        )
        admitted = json.loads(
            next(
                json.dumps(item)
                for item in self._records()
                if item["record_id"] == "RADAR-V04-A01"
            )
        )
        admitted["admission_state"] = "admitted"
        admitted["negative_control"] = True
        admitted["corpus_kind"] = "attribution"
        errors = validate_v04_record(admitted, root=ROOT)
        self.assertIn("negative controls belong to the safety corpus", errors)
        self.assertTrue(validate_v04_records([blocked, blocked], root=ROOT))

    def test_early_gate_false_high_confidence_failure_is_not_a_pass(self) -> None:
        metrics = {
            "action_owner": {"precision": {"value": 0.8}},
            "candidate_induction": {"precision": {"value": 0.9}},
            "abstention": {"recall": {"value": 0.95}},
            "false_high_confidence_upstream": {"failures": 1},
        }
        gates = v04_early_gates({"metrics": metrics})
        self.assertEqual(gates["checks"]["false_high_confidence_upstream"]["status"], "fail")
        self.assertFalse(gates["continue_mining"])

    def test_validator_covers_temporal_provenance_and_safety_edges(self) -> None:
        record = next(
            item
            for item in self._records()
            if item["record_id"] == "RADAR-V04-A01"
        )
        before_cutoff = json.loads(json.dumps(record))
        before_cutoff["source_cutoff"] = "2024-12-28T00:00:00Z"
        before_cutoff["source_chain"][1]["evidence_id"] = before_cutoff["source_chain"][0]["evidence_id"]
        before_cutoff["source_chain"][1]["published_at"] = "2024-12-28T00:00:00Z"
        before_cutoff["source_snapshots"] = before_cutoff["source_snapshots"][:1]
        errors = validate_v04_record(before_cutoff, root=ROOT)
        self.assertIn("source_cutoff must not precede t0", errors)
        self.assertTrue(any("evidence_ids must be unique" in error for error in errors))
        self.assertTrue(any("missing fetched snapshots" in error for error in errors))
        self.assertTrue(any("precedes t0" in error for error in errors))

        owner_invalid = json.loads(json.dumps(record))
        owner_invalid["label"]["action_owner_scored"] = False
        self.assertIn(
            "Gold-A must be included in action-owner scoring",
            validate_v04_record(owner_invalid, root=ROOT),
        )

        safety = next(
            item
            for item in self._records()
            if item["record_id"] == "RADAR-V04-S01"
        )
        safety_invalid = json.loads(json.dumps(safety))
        safety_invalid["label"]["should_abstain"] = False
        safety_invalid["negative_control"] = False
        safety_errors = validate_v04_record(safety_invalid, root=ROOT)
        self.assertIn(
            "admitted safety records require Safety-A abstention labels",
            safety_errors,
        )
        self.assertIn("safety records must be negative controls", safety_errors)

    def test_v03_owner_metric_uses_explicit_scoring_scope(self) -> None:
        def prediction(case_id: str, owner: str) -> dict:
            return make_prediction(
                schema_version="0.3",
                case_id=case_id,
                verdict="confirmed_regression",
                candidate_induced=True,
                responsible_layer="upstream_runtime_or_library",
                confidence="medium",
                rationale="controlled test",
                evidence_ids=["E-1"],
                provider="deterministic",
                provider_version="0.3.0",
                action_owner_repository=owner,
                root_cause_component=owner,
                first_bad_version_or_revision="1.0.0",
                evidence_class="CAUSALLY_SUPPORTED",
                evidence_classes=["CAUSALLY_SUPPORTED"],
            )

        labels = {
            "scored": {
                "candidate_induced": True,
                "responsible_layer": "upstream_runtime_or_library",
                "action_owner_repository": "owner",
                "action_owner_scored": True,
                "should_abstain": False,
                "first_bad": "1.0.0",
                "root_cause_component": "owner",
            },
            "excluded": {
                "candidate_induced": True,
                "responsible_layer": "upstream_runtime_or_library",
                "action_owner_repository": "different-owner",
                "action_owner_scored": False,
                "should_abstain": False,
                "first_bad": "1.0.0",
                "root_cause_component": "different-owner",
            },
        }
        report = score_v03(
            [prediction("scored", "owner"), prediction("excluded", "wrong")],
            labels,
        )
        self.assertEqual(report["metrics"]["action_owner"]["precision"]["denominator"], 1)
        self.assertEqual(report["metrics"]["action_owner"]["precision"]["numerator"], 1)
