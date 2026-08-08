from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from radar_bench.baseline.v03 import predict_v03
from radar_bench.blindness import (
    CandidateFilesystem,
    assert_network_denied,
    digest_path,
    network_denied,
    run_blind_provider,
)
from radar_bench.cli import main
from radar_bench.corpus.v03 import (
    validate_gold_admission,
    validate_v03_records,
    v03_corpus_summary,
)
from radar_bench.errors import ExternalBlocked
from radar_bench.evaluation.ablation import v03_lane_plan
from radar_bench.evaluation.gates import evaluate_gates
from radar_bench.evaluation.statistics import one_sided_upper_95, safety_confidence
from radar_bench.evaluation.stages import build_freeze_manifest, digest_tree
from radar_bench.evaluation.v03 import score_v03
from radar_bench.github.client import GitHubClient
from radar_bench.models.prediction import make_prediction, validate_prediction
from radar_bench.schema.loader import validate_json

ROOT = Path(__file__).resolve().parents[1]


def _admission() -> dict:
    roles = [
        "maintainer_confirmation",
        "first_bad",
        "causal",
        "reproducer",
        "resolution",
        "post_fix",
    ]
    return {
        "schema_version": "0.3",
        "admission_id": "ADMIT-V03-TEST-0001",
        "case_id": "RADAR-V03-TEST-0001",
        "corpus_kind": "attribution_gold",
        "candidate_category": "true_upstream_regression",
        "difficulty": "D3",
        "negative_control": False,
        "negative_control_type": "none",
        "counterfactual": False,
        "derived_from_positive_case_id": None,
        "admission_state": "admitted",
        "target_split": "hidden_test",
        "source_cutoff": "2026-08-09T00:00:00Z",
        "source_urls": ["https://github.com/example/project/issues/1"],
        "independent_evidence": [
            {
                "evidence_id": f"G03-TEST-{index}",
                "kind": "other",
                "uri": f"https://github.com/example/project/issues/{index + 2}",
                "published_at": "2026-08-10T00:00:00Z",
                "available_after_cutoff": True,
                "role": role,
                "snapshot_digest": "sha256:" + "a" * 64,
                "notes": None,
            }
            for index, role in enumerate(roles)
        ],
        "candidate_snapshot": {
            "path": "candidate/input",
            "digest": "sha256:" + "b" * 64,
            "cutoff_only": True,
        },
        "gold_packet": {
            "path": "gold/packet",
            "digest": "sha256:" + "c" * 64,
            "post_cutoff_only": True,
            "scorer_only": True,
        },
        "gold_derivation": "independent_public_evidence",
        "gold_label": {
            "should_abstain": False,
            "candidate_induced": True,
            "trigger_component": "https://github.com/example/project",
            "trigger_change": "1.2.0",
            "manifestation_project": "consumer",
            "manifestation_layer": "runtime",
            "root_cause_component": "project",
            "root_cause_mechanism": "removed API",
            "action_owner_repository": "https://github.com/example/project",
            "first_bad_version_or_revision": "1.2.0",
            "confounders": [],
            "evidence_class": "CONFIRMED",
        },
        "audit": {
            "created_at": "2026-08-10T00:00:00Z",
            "last_reviewed_at": "2026-08-10T00:00:00Z",
            "derived_by": "osint_protocol",
            "review_status": "independently_reviewed",
            "reviewer": "reviewer-1",
            "record_digest": None,
        },
    }


class V03Contracts(unittest.TestCase):
    def test_plan_shape_and_fail_closed_admission(self) -> None:
        plan = json.loads((ROOT / "corpus" / "v0.3" / "plan.json").read_text())
        self.assertEqual(plan["corpus_counts"]["attribution_gold_planned"], 120)
        self.assertEqual(plan["corpus_counts"]["safety_abstention_planned"], 300)
        self.assertEqual(plan["corpus_counts"]["counterfactual_variants_planned"], 50)
        record = json.loads(
            next((ROOT / "corpus" / "v0.3" / "attribution-gold").glob("**/*.json")).read_text()
        )
        self.assertEqual(validate_gold_admission(record, root=ROOT), [])
        summary = v03_corpus_summary([record])
        self.assertFalse(summary["planned_is_gold"])
        admitted = _admission()
        self.assertEqual(validate_gold_admission(admitted, root=ROOT), [])
        invalid = json.loads(json.dumps(admitted))
        invalid["gold_packet"]["digest"] = None
        self.assertTrue(validate_gold_admission(invalid, root=ROOT))

    def test_admission_rejects_ambiguous_and_incomplete_records(self) -> None:
        planned = json.loads(
            next((ROOT / "corpus" / "v0.3" / "safety-abstention").glob("**/*.json")).read_text()
        )
        planned["source_urls"] = ["https://example.invalid/a", "https://example.invalid/a"]
        planned["independent_evidence"] = [
            {
                "evidence_id": "G03-TEST-DUP",
                "kind": "other",
                "uri": "https://example.invalid/evidence",
                "published_at": "2026-08-08T00:00:00Z",
                "available_after_cutoff": True,
                "role": "context",
                "snapshot_digest": None,
                "notes": None,
            },
            {
                "evidence_id": "G03-TEST-DUP",
                "kind": "other",
                "uri": "https://example.invalid/evidence-2",
                "published_at": "2026-08-10T00:00:00Z",
                "available_after_cutoff": False,
                "role": "context",
                "snapshot_digest": None,
                "notes": None,
            },
        ]
        errors = validate_gold_admission(planned, root=ROOT)
        self.assertTrue(any("unique" in error for error in errors))
        planned["corpus_kind"] = "attribution_gold"
        planned["negative_control"] = True
        planned["negative_control_type"] = "none"
        planned["counterfactual"] = True
        planned["derived_from_positive_case_id"] = None
        self.assertTrue(validate_gold_admission(planned, root=ROOT))
        self.assertTrue(validate_v03_records([planned, planned], root=ROOT))

    def test_cli_and_freeze_commands(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["validate-v03-corpus", "--json"]), 0)
        self.assertIn('"records": 420', output.getvalue())
        snapshot = next((ROOT / "corpus" / "snapshots").glob("*/input/snapshot.json"))
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["baseline", str(snapshot), "--v03"]), 0)
        self.assertIn('"schema_version": "0.3"', output.getvalue())
        freeze = build_freeze_manifest(
            ROOT, invocation=["test"], implementation_commit="abc1234"
        )
        self.assertFalse(freeze["gold_labels_available_to_candidate"])
        self.assertTrue(freeze["corpus_digest"].startswith("sha256:"))
        self.assertTrue(digest_tree(ROOT, ("corpus/v0.3/**/*.json",)).startswith("sha256:"))

    def test_v03_prediction_ontology_and_baseline(self) -> None:
        packet = json.loads(
            next((ROOT / "corpus" / "snapshots").glob("*/input/snapshot.json")).read_text()
        )
        prediction = predict_v03(packet)
        self.assertEqual(prediction["schema_version"], "0.3")
        self.assertEqual(validate_prediction(prediction), [])
        bad = dict(prediction)
        bad["verdict"] = "confounded_change"
        bad["candidate_induced"] = True
        bad["evidence_class"] = "CONFOUNDED"
        bad["confounders"] = ["resolver"]
        self.assertTrue(validate_prediction(bad))

    def test_v03_scoring_statistics_and_gates(self) -> None:
        answer = make_prediction(
            schema_version="0.3",
            case_id="RADAR-V03-SCORE-1",
            verdict="confirmed_regression",
            candidate_induced=True,
            responsible_layer="upstream_runtime_or_library",
            confidence="medium",
            rationale="controlled test",
            evidence_ids=["E-1"],
            provider="deterministic",
            provider_version="0.3.0",
            root_cause_component="project",
            action_owner_repository="https://github.com/example/project",
            first_bad_version_or_revision="1.2.0",
            evidence_class="CAUSALLY_SUPPORTED",
            evidence_classes=["CAUSALLY_SUPPORTED"],
        )
        abstain = make_prediction(
            schema_version="0.3",
            case_id="RADAR-V03-SCORE-2",
            verdict="confounded_change",
            candidate_induced=None,
            responsible_layer="multiple_layers",
            confidence="inconclusive",
            rationale="resolver changed",
            evidence_ids=[],
            provider="deterministic",
            provider_version="0.3.0",
            evidence_class="CONFOUNDED",
            evidence_classes=["CONFOUNDED"],
            confounders=["resolver"],
        )
        predictions = [answer, abstain]
        for value in predictions:
            self.assertEqual(validate_prediction(value), [])
            value["_valid"] = True
        labels = {
            "RADAR-V03-SCORE-1": {
                "candidate_induced": True,
                "responsible_layer": "upstream_runtime_or_library",
                "root_cause_component": "project",
                "action_owner_repository": "https://github.com/example/project",
                "first_bad_version_or_revision": "1.2.0",
                "should_abstain": False,
                "difficulty": "D1",
            },
            "RADAR-V03-SCORE-2": {
                "candidate_induced": None,
                "responsible_layer": "multiple_layers",
                "should_abstain": True,
                "corpus_kind": "safety_abstention",
                "difficulty": "D5",
            },
        }
        report = score_v03(predictions, labels)
        self.assertEqual(report["metrics"]["action_owner"]["precision"]["value"], 1.0)
        self.assertEqual(report["metrics"]["false_high_confidence_upstream"]["trials"], 1)
        self.assertIsNone(one_sided_upper_95(0, 0))
        self.assertLess(one_sided_upper_95(0, 300) or 1.0, 0.01)
        self.assertFalse(safety_confidence(0, 0)["eligible_for_safety_claim"])
        with self.assertRaises(ValueError):
            one_sided_upper_95(2, 1)
        gates = evaluate_gates(report)
        self.assertIn("action_owner.precision", gates["gates"])

    def test_ablation_lanes_are_explicitly_blocked_or_not_run(self) -> None:
        digest = "sha256:" + "a" * 64
        plan = v03_lane_plan(digest)
        self.assertEqual(plan["lanes"]["deterministic"]["status"], "not_run")
        self.assertEqual(plan["lanes"]["local_model"]["status"], "blocked_external")
        for lane in plan["lanes"].values():
            validate_json(lane, "ablation_v03", ROOT)
        completed = v03_lane_plan(digest, deterministic_scored_cases=2, local_model_available=True)
        self.assertEqual(completed["lanes"]["deterministic"]["status"], "completed")


class BlindBoundary(unittest.TestCase):
    def test_candidate_can_only_see_neutral_input_and_network_is_denied(self) -> None:
        class Provider:
            def predict(self, packet: dict) -> dict:
                self.packet = packet
                return {"status": "neutral"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "candidate"
            gold = root / "gold"
            (candidate / "input").mkdir(parents=True)
            gold.mkdir()
            (candidate / "input" / "snapshot.json").write_text(
                json.dumps({"case_id": "RADAR-V03-BLIND-1"}), encoding="utf-8"
            )
            (gold / "label.json").write_text("secret", encoding="utf-8")
            filesystem = CandidateFilesystem(candidate)
            self.assertEqual(filesystem.list_files(), ["input/snapshot.json"])
            self.assertEqual(filesystem.read_text(candidate / "input" / "snapshot.json")[0], "{")
            with self.assertRaises(PermissionError):
                filesystem.read_text(gold / "label.json")
            (candidate / "gold").mkdir()
            (candidate / "gold" / "secret.txt").write_text("secret", encoding="utf-8")
            with self.assertRaises(PermissionError):
                filesystem.read_text(candidate / "gold" / "secret.txt")
            self.assertTrue(digest_path(candidate).startswith("sha256:"))
            self.assertTrue(digest_path(gold / "label.json").startswith("sha256:"))
            with self.assertRaises(FileNotFoundError):
                digest_path(root / "missing")
            with patch.dict("os.environ", {}, clear=False):
                with network_denied():
                    with self.assertRaises(ExternalBlocked):
                        assert_network_denied()
                    with self.assertRaises(ExternalBlocked):
                        GitHubClient().get_json("https://api.github.com/repos/a/b")
            output = root / "candidate-output.json"
            prediction, record = run_blind_provider(
                Provider(), candidate, gold, output, implementation_commit="abc1234"
            )
            self.assertEqual(prediction["status"], "neutral")
            self.assertFalse(record.as_dict()["gold_readable_by_candidate"])
            validate_json(record.as_dict(), "blind_run_v03", ROOT)
            with self.assertRaises(ValueError):
                run_blind_provider(Provider(), candidate, candidate, output)
            with network_denied():
                pass
