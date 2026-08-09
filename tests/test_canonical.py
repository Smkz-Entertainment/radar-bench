from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from types import SimpleNamespace
from unittest.mock import patch

from radar_bench.execution.canonical import (
    CanonicalHarness,
    HistoricalObservationExecutor,
    OpaqueSafetyExecutor,
    _candidate_view,
    _read_list,
    _read_object,
    _response,
    _opaque_id,
    score_canonical_lanes,
    validate_candidate_view,
)

ROOT = Path(__file__).resolve().parents[1]


class CanonicalHarnessContracts(unittest.TestCase):
    def test_candidate_shape_is_identical_and_opaque(self) -> None:
        harness = CanonicalHarness(ROOT, None)
        cases = harness._cases(
            {"historical_cases": [{"case_id": f"RADAR-V07-A{index:02d}"} for index in range(1, 6)]},
            {"cases": [{"case_id": f"RADAR-V07-T{index:02d}"} for index in range(1, 21)]},
        )
        self.assertEqual(len(cases), 25)
        self.assertEqual(set(cases[0].candidate_view), set(cases[1].candidate_view))
        self.assertEqual(validate_candidate_view(cases[0].candidate_view), [])
        self.assertNotIn("corpus_kind", cases[0].candidate_view)
        self.assertNotIn("case_type", cases[0].candidate_view)
        self.assertNotEqual(cases[0].episode_id, cases[1].episode_id)

    def test_candidate_validation_and_bounded_file_readers_fail_closed(self) -> None:
        view = _candidate_view(_opaque_id("case"))
        view["gold"] = {"owner": "hidden"}
        view["schema_version"] = "wrong"
        errors = validate_candidate_view(view)
        self.assertEqual(len(errors), 3)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.json"
            with self.assertRaisesRegex(ValueError, "absent or too large"):
                _read_object(missing, 100)
            object_path = root / "object.json"
            object_path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expected an object"):
                _read_object(object_path, 100)
            list_path = root / "list.json"
            list_path.write_text(json.dumps([{"valid": True}, "ignored"]), encoding="utf-8")
            self.assertEqual(_read_list(list_path, 100), [{"valid": True}])
            (root / "object-value.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "expected a list"):
                _read_list(root / "object-value.json", 100)
            with self.assertRaisesRegex(ValueError, "absent or too large"):
                _read_list(list_path, 1)

    def test_observation_outcomes_cover_baseline_and_no_effect(self) -> None:
        request = {"request_id": "request"}
        invalid = _response(request, {"returncode": "bad"}, {"returncode": 0}, adapter="test")
        self.assertEqual(invalid["status"], "EXECUTION_ERROR")
        baseline = _response(request, {"returncode": 1}, {"returncode": 1}, adapter="test")
        self.assertEqual(baseline["result"]["outcome"], "BASELINE_NOT_STABLE")
        unchanged = _response(request, {"returncode": 0}, {"returncode": 0}, adapter="test")
        self.assertEqual(unchanged["result"]["outcome"], "NO_DISTINGUISHING_EFFECT")

    def test_runtime_executor_rejects_invalid_and_unsealed_shapes(self) -> None:
        executor = HistoricalObservationExecutor({"case": {"sides": {"control": {}, "candidate": {}}}})
        invalid = executor.execute({"schema_version": "0.7"})
        self.assertEqual(invalid["status"], "INVALID_REQUEST")
        valid = {
            "schema_version": "0.7",
            "request_id": "request",
            "episode_id": "unknown",
            "capability": "rerun",
            "parameters": {},
        }
        self.assertEqual(executor.execute(valid)["error_codes"], ["CASE_NOT_SEALED"])
        malformed = HistoricalObservationExecutor({"case": {"sides": []}})
        self.assertEqual(malformed.execute({**valid, "episode_id": "case"})["error_codes"], ["CONTAINER_EXECUTION_FAILED"])
        malformed_executor = HistoricalObservationExecutor({"case": {"sides": {"control": {}, "candidate": []}}})
        self.assertEqual(malformed_executor.execute({**valid, "episode_id": "case"})["error_codes"], ["CONTAINER_EXECUTION_FAILED"])

    def test_safety_executor_maps_opaque_ids_and_caches_observations(self) -> None:
        class FakeExecutor:
            def __init__(self) -> None:
                self.requests: list[dict[str, Any]] = []

            def execute(self, request: dict[str, Any]) -> dict[str, Any]:
                self.requests.append(request)
                return _response(request, {"returncode": 0}, {"returncode": 1}, adapter="fake")

        fake = FakeExecutor()
        executor = OpaqueSafetyExecutor(cast(Any, fake), {"opaque": "RADAR-V07-T01"})
        request = {
            "schema_version": "0.7",
            "request_id": "request-1",
            "episode_id": "opaque",
            "capability": "rerun",
            "parameters": {},
        }
        first = executor.execute(request)
        second = executor.execute({**request, "request_id": "request-2"})
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(first["status"], second["status"])
        self.assertEqual(second["request_id"], "request-2")
        self.assertEqual(executor.execute({**request, "episode_id": "missing"})["error_codes"], ["CASE_NOT_SEALED"])
        self.assertEqual(executor.execute({"schema_version": "0.7"})["status"], "INVALID_REQUEST")

    def test_safety_image_acquisition_is_digest_checked(self) -> None:
        harness = CanonicalHarness(ROOT, None)
        manifest = {"cases": [{"platform": {"container_image": "python@sha256:" + "a" * 64}}]}
        with patch("radar_bench.execution.canonical.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "RUNTIME_UNAVAILABLE"):
                harness._ensure_safety_image(manifest)
        with patch("radar_bench.execution.canonical.shutil.which", return_value="docker"), patch(
            "radar_bench.execution.canonical.subprocess.run", return_value=SimpleNamespace(returncode=0)
        ) as run:
            self.assertFalse(harness._ensure_safety_image(manifest))
            self.assertEqual(run.call_count, 1)
        with patch("radar_bench.execution.canonical.shutil.which", return_value="docker"), patch(
            "radar_bench.execution.canonical.subprocess.run",
            side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=0), SimpleNamespace(returncode=0)],
        ):
            self.assertTrue(harness._ensure_safety_image(manifest))
        with patch("radar_bench.execution.canonical.shutil.which", return_value="docker"), patch(
            "radar_bench.execution.canonical.subprocess.run",
            side_effect=[SimpleNamespace(returncode=1), SimpleNamespace(returncode=1)],
        ):
            with self.assertRaisesRegex(RuntimeError, "BASE_IMAGE_UNAVAILABLE"):
                harness._ensure_safety_image(manifest)

    def test_harness_runs_with_case_agnostic_fake_safety_transport(self) -> None:
        historical = [
            {
                "case_id": f"RADAR-V07-A{index:02d}",
                "sides": {"control": {"returncode": 0}, "candidate": {"returncode": 1}},
            }
            for index in range(1, 6)
        ]

        class FakeHermetic:
            def __init__(self, manifest: Any, *, root: Path) -> None:
                del manifest, root

            def execute(self, request: dict[str, Any]) -> dict[str, Any]:
                return _response(request, {"returncode": 0}, {"returncode": 0}, adapter="fake")

        with patch("radar_bench.execution.canonical.reconstruct_historical_cases", return_value={"status": "READY", "cases": historical, "network_used": False}), patch(
            "radar_bench.execution.canonical.HermeticExecutor", FakeHermetic
        ), patch.object(CanonicalHarness, "_ensure_safety_image", return_value=False):
            result = CanonicalHarness(ROOT, None).run()
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(len(result["cases"]), 25)
        self.assertTrue(result["metrics"]["labels_loaded_after_execution"])

    def test_runtime_executor_returns_observation_and_rejects_unsupported(self) -> None:
        executor = HistoricalObservationExecutor(
            {
                "episode-1": {
                    "sides": {
                        "control": {"returncode": 0, "output_digest": "sha256:control"},
                        "candidate": {"returncode": 1, "output_digest": "sha256:candidate"},
                    }
                }
            }
        )
        request = {
            "schema_version": "0.7",
            "request_id": "request-1",
            "episode_id": "episode-1",
            "capability": "change_dependency_version",
            "parameters": {},
        }
        response = executor.execute(request)
        self.assertEqual(response["status"], "COMPLETED")
        self.assertEqual(response["result"]["outcome"], "CANDIDATE_SPECIFIC")
        self.assertIsNone(response["result"]["supported_component"])
        self.assertNotIn("gold", response)
        unsupported = executor.execute({**request, "capability": "bisect_component"})
        self.assertEqual(unsupported["status"], "UNSUPPORTED_EXPERIMENT")
        self.assertIn("EXPERIMENT_NOT_SEALED", unsupported["error_codes"])

    def test_evaluator_labels_are_loaded_only_by_scorer(self) -> None:
        historical_ids = [
            "RADAR-V07-A01",
            "RADAR-V07-A02",
            "RADAR-V07-A03",
            "RADAR-V07-A04",
            "RADAR-V07-A05",
        ]
        safety_ids = [f"RADAR-V07-T{index:02d}" for index in range(1, 21)]
        cases = [
            {"case_id": case_id, "episode_id": _opaque_id(case_id)}
            for case_id in [*historical_ids, *safety_ids]
        ]
        predictions = [
            {
                "case_id": record,
                "verdict": "confirmed_regression",
                "candidate_induced": True,
                "root_cause_component": root,
                "action_owner_repository": None,
            }
            for record, root in (
                ("RADAR-V04-A05", "https://github.com/pandas-dev/pandas"),
                ("RADAR-V04-A03", "https://github.com/scipy/scipy"),
                ("RADAR-V04-A06", "https://github.com/pandas-dev/pandas"),
                ("RADAR-V04-A21", "https://github.com/pandas-dev/pandas"),
                ("RADAR-V04-A15", "https://github.com/pandas-dev/pandas"),
            )
        ]

        def bounded(case_id: str) -> dict[str, Any]:
            return {
                "case_id": case_id,
                "episode_id": _opaque_id(case_id),
                "run": {
                    "terminal": {
                        "state": "BOUNDED_INCONCLUSIVE",
                        "candidate_induced": True if case_id in historical_ids else None,
                        "root_cause_component": None,
                        "action_owner_repository": None,
                    },
                    "attempts": [],
                },
            }

        run_result = {
            "cases": cases,
            "lanes": {
                "static-v0.4": {"predictions": predictions},
                "naive-deterministic": {"runs": [bounded(case_id) for case_id in [*historical_ids, *safety_ids]]},
                "agentic-v0.5-frozen": {"runs": [bounded(case_id) for case_id in [*historical_ids, *safety_ids]]},
            },
        }
        scored = score_canonical_lanes(ROOT, run_result)
        frozen = scored["lanes"]["agentic-v0.5-frozen"]["metrics"]
        self.assertTrue(scored["labels_loaded_after_execution"])
        self.assertEqual(frozen["historical_positive_resolution"]["numerator"], 1)
        self.assertEqual(frozen["safety_abstention_recall"]["numerator"], 20)
        self.assertFalse(scored["mandatory_case_gates"]["scikit-learn-30512-resolves-to-scipy"])
        self.assertTrue(scored["mandatory_case_gates"]["pandas-45601-keeps-semantic-ambiguity-open"])


if __name__ == "__main__":
    unittest.main()
