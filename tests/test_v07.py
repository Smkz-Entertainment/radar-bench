from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from radar_bench.cli import main
from radar_bench.execution.v07 import (
    COMMON_CAPABILITIES,
    FROZEN_V05_COMMIT,
    HermeticExecutor,
    MAX_OUTPUT_BYTES,
    adapt_frozen_request,
    evaluate_pilot,
    freeze_audit,
    preparation_audit,
    validate_manifest,
    validate_request,
    v07_gates,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "corpus" / "v0.7" / "executable-subset.json"


class V07ExecutableContracts(unittest.TestCase):
    def _manifest(self, root: Path) -> dict[str, Any]:
        view = root / "candidate-view.json"
        view.write_text('{"episode_id":"V07-CASE-1"}\n', encoding="utf-8")
        artifact = root / "artifact.whl"
        artifact.write_bytes(b"sealed artifact")
        for side in ("control", "candidate"):
            (root / side).mkdir()
        def digest(path: Path) -> str:
            return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        recipe = {
            capability: {
                "control_command": ["python", "-c", "print('control')"],
                "candidate_command": ["python", "-c", "print('candidate')"],
            }
            for capability in COMMON_CAPABILITIES
        }
        return {
            "schema_version": "0.7",
            "manifest_status": "SEALED",
            "evaluation_policy": {
                "network": "denied",
                "gold_mounted": False,
                "historical_evidence_mounted": False,
                "artifact_policy": "local_only",
                "shell": False,
            },
            "capabilities": list(COMMON_CAPABILITIES),
            "cases": [
                {
                    "case_id": "V07-CASE-1",
                    "corpus_kind": "attribution",
                    "platform": {"os": "linux", "architecture": "x86_64", "container_image": "python@sha256:" + "0" * 64},
                    "candidate_view": "candidate-view.json",
                    "candidate_view_digest": digest(view),
                    "control": {"workspace": "control", "revision": "abcdef1", "source_digest": "sha256:" + hashlib.sha256(b"").hexdigest(), "command": ["python", "-c", "pass"], "environment": {"LANG": "C"}},
                    "candidate": {"workspace": "candidate", "revision": "1234567", "source_digest": "sha256:" + hashlib.sha256(b"").hexdigest(), "command": ["python", "-c", "pass"], "environment": {"LANG": "C"}},
                    "capability_recipes": recipe,
                    "prepared_artifacts": [{"path": "artifact.whl", "digest": digest(artifact)}],
                }
            ],
        }

    def test_common_manifest_and_request_contracts_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._manifest(root)
            self.assertEqual(validate_manifest(manifest, root=root), [])
            invalid = copy.deepcopy(manifest)
            invalid["evaluation_policy"]["gold_mounted"] = True
            self.assertTrue(validate_manifest(invalid, root=root))
            unsealed = copy.deepcopy(manifest)
            unsealed["manifest_status"] = "UNSEALED"
            self.assertTrue(validate_manifest(unsealed, root=root))
            self.assertEqual(
                validate_request({"schema_version": "0.7", "request_id": "R1", "episode_id": "V07-CASE-1", "capability": "rerun", "parameters": {}}),
                [],
            )
            self.assertTrue(validate_request({"schema_version": "0.7", "request_id": "R1", "episode_id": "V07-CASE-1", "capability": "unknown"}))

    def test_frozen_request_adapter_and_executor_return_observations(self) -> None:
        adapted = adapt_frozen_request({"request_id": "REQ-1", "episode_id": "V07-CASE-1", "type": "baseline_check"})
        self.assertEqual(adapted["capability"], "rerun")
        with self.assertRaises(ValueError):
            adapt_frozen_request({"type": "dependency_graph_probe"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = self._manifest(root)
            executor = HermeticExecutor(manifest, root=root)
            request = {"schema_version": "0.7", "request_id": "R1", "episode_id": "V07-CASE-1", "capability": "rerun", "parameters": {}}
            completed = subprocess.CompletedProcess([], 0, b"ok", b"")
            with patch("radar_bench.execution.v07.shutil.which", return_value="docker"), patch("radar_bench.execution.v07.subprocess.run", return_value=completed) as run:
                response = executor.execute(request)
            self.assertEqual(response["status"], "COMPLETED")
            self.assertEqual(response["result"]["outcome"], "NO_DISTINGUISHING_EFFECT")
            self.assertNotIn("AVAILABLE", json.dumps(response))
            self.assertEqual(run.call_count, 2)
            self.assertIn("--network=none", run.call_args_list[0].args[0])
            command = run.call_args_list[0].args[0]
            self.assertIn("--user=65532:65532", command)
            self.assertIn("--cap-drop=ALL", command)

            with patch(
                "radar_bench.execution.v07.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 0, b"x" * (MAX_OUTPUT_BYTES + 1), b""
                ),
            ):
                oversized = executor.execute({**request, "request_id": "R-LIMIT"})
            self.assertEqual(oversized["status"], "EXECUTION_ERROR")

            with patch("radar_bench.execution.v07.shutil.which", return_value="docker"), patch(
                "radar_bench.execution.v07.subprocess.run",
                side_effect=[subprocess.CompletedProcess([], 0, b"ok", b""), subprocess.CompletedProcess([], 1, b"fail", b"")],
            ):
                changed = executor.execute({**request, "request_id": "R2", "capability": "change_dependency_version"})
            self.assertEqual(changed["result"]["outcome"], "CANDIDATE_SPECIFIC")

            with patch("radar_bench.execution.v07.shutil.which", return_value="docker"), patch(
                "radar_bench.execution.v07.subprocess.run",
                side_effect=[subprocess.CompletedProcess([], 1, b"fail", b""), subprocess.CompletedProcess([], 0, b"ok", b"")],
            ):
                unstable = executor.execute({**request, "request_id": "R3"})
            self.assertEqual(unstable["result"]["outcome"], "BASELINE_NOT_STABLE")

    def test_preparation_and_freeze_boundaries_are_honest(self) -> None:
        self.assertEqual(preparation_audit(ROOT, ROOT / "missing-v07-manifest.json")["status"], "BLOCKED_BY_EXECUTABILITY")
        preparation = preparation_audit(ROOT, MANIFEST)
        self.assertEqual(preparation["status"], "BLOCKED_BY_EXECUTABILITY")
        self.assertEqual(preparation["case_count"], 0)
        result = json.loads((ROOT / "artifacts" / "v05-result.json").read_text(encoding="utf-8"))
        freeze = freeze_audit(ROOT, result["hashes"]["implementation"], FROZEN_V05_COMMIT)
        self.assertTrue(freeze["digest_match"])
        self.assertTrue(freeze["commit_match"])
        self.assertFalse(freeze["tuning_performed"])

    def test_pilot_metrics_score_abstention_and_experiment_advantage(self) -> None:
        cases = [
            {"case_id": "A", "corpus_kind": "attribution", "gold": {"should_abstain": False, "candidate_induced": True, "root_cause_component": "root-a", "action_owner_repository": "owner-a"}},
            {"case_id": "S", "corpus_kind": "safety", "gold": {"should_abstain": True, "candidate_induced": None, "root_cause_component": None, "action_owner_repository": None}},
        ]
        runs = [
            {"episode_id": "A", "terminal": {"state": "CAUSALLY_ATTRIBUTED", "root_cause_component": "root-a", "action_owner_repository": "owner-a", "candidate_induced": True}, "attempts": [{"useful": True}]},
            {"episode_id": "S", "terminal": {"state": "BOUNDED_INCONCLUSIVE", "root_cause_component": None, "action_owner_repository": None}, "attempts": [{"useful": False}]},
        ]
        metrics = evaluate_pilot(cases, runs, [{"episode_id": "A", "terminal": {"root_cause_component": "wrong"}}], [{"episode_id": "A", "terminal": {"root_cause_component": "wrong"}}])
        self.assertEqual(metrics["action_owner_precision"]["value"], 1.0)
        self.assertEqual(metrics["correct_resolution_or_abstention"]["value"], 1.0)
        self.assertEqual(metrics["safety_abstention_recall"]["value"], 1.0)
        self.assertEqual(metrics["useful_experiment_rate"]["value"], 0.5)
        self.assertEqual(metrics["advantage_over_naive"]["value"], 1.0)
        self.assertIsNone(metrics["random_resolution"]["value"])

    def test_gates_block_without_cases_and_validate_ready_metrics(self) -> None:
        blocked = v07_gates({}, {"status": "BLOCKED_BY_EXECUTABILITY"}, {"digest_match": True})
        self.assertEqual(blocked["decision"], "BLOCKED_BY_EXECUTABILITY")
        metrics = {
            "action_owner_precision": {"value": 0.9},
            "candidate_induced_precision": {"value": 0.9},
            "correct_resolution_or_abstention": {"value": 0.9},
            "safety_abstention_recall": {"value": 1.0},
            "premature_owner_accusations": {"value": 0},
            "useful_experiment_rate": {"value": 0.7},
            "median_experiments_to_resolution": {"value": 2.0},
            "naive_resolution": {"value": 0.5},
            "advantage_over_naive": {"value": 0.4},
            "advantage_over_no_experiment": {"value": 0.2},
        }
        passing = v07_gates(metrics, {"status": "READY"}, {"digest_match": True})
        self.assertTrue(passing["integrity_validated"])
        metrics["action_owner_precision"]["value"] = 0.7
        failing = v07_gates(metrics, {"status": "READY"}, {"digest_match": True})
        self.assertEqual(failing["decision"], "KILL_RADAR_PRODUCT_THESIS")

    def test_cli_validates_v07_blocked_artifact(self) -> None:
        self.assertEqual(main(["validate-v07-executable"]), 0)
