from __future__ import annotations

import subprocess
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from radar_bench.execution.docker_runtime import DockerRuntime
from radar_bench.errors import SecurityError
from radar_bench.providers.subprocess_provider import (
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    SubprocessProvider,
)


class SubprocessHardeningTests(unittest.TestCase):
    def test_timeout_and_input_limits_are_rejected(self) -> None:
        with self.assertRaises(SecurityError):
            SubprocessProvider(["python"], timeout=0)
        oversized = {"payload": "x" * MAX_INPUT_BYTES}
        with self.assertRaises(SecurityError):
            SubprocessProvider(["python"]).predict(oversized)

    def test_output_limit_is_rejected_before_json_parsing(self) -> None:
        completed = subprocess.CompletedProcess(
            ["provider"], 0, "x" * (MAX_OUTPUT_BYTES + 1), ""
        )
        with patch(
            "radar_bench.providers.subprocess_provider.subprocess.run",
            return_value=completed,
        ):
            with self.assertRaises(SecurityError):
                SubprocessProvider(["provider"]).predict({"ok": True})


class ReleaseHelperTests(unittest.TestCase):
    def test_path_artifact_and_opacity_helpers_fail_closed(self) -> None:
        from radar_bench.release import (
            _artifact_status,
            _audit_opacity,
            _resolve_inside,
            canonical_digest,
            file_digest,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.whl"
            artifact.write_bytes(b"artifact")
            digest = file_digest(artifact)
            self.assertTrue(digest.startswith("sha256:"))
            self.assertTrue(canonical_digest({"a": 1}).startswith("sha256:"))
            self.assertEqual(_resolve_inside(root, root, "artifact.whl")[0], artifact)
            self.assertEqual(_resolve_inside(root, root, "../outside")[0], None)
            self.assertEqual(_resolve_inside(root, root, str(artifact))[1], "path must be relative to the repository")
            self.assertEqual(_artifact_status({})["reason"], "ARTIFACT_UNAVAILABLE")
            self.assertFalse(_artifact_status({"artifact_bundle": {"local_path": None}})["available"])
            missing = _artifact_status(
                {"artifact_bundle": {"bundle_id": "missing", "files": {"x": digest}}},
                artifact_root=root,
            )
            self.assertFalse(missing["available"])
            bundle = root / "bundle"
            bundle.mkdir()
            (bundle / "artifact.whl").write_bytes(b"artifact")
            missing_file = _artifact_status(
                {"artifact_bundle": {"bundle_id": "bundle", "files": {"missing.whl": digest}}},
                artifact_root=root,
            )
            self.assertFalse(missing_file["available"])
            valid = _artifact_status(
                {"artifact_bundle": {"bundle_id": "bundle", "files": {"artifact.whl": digest}}},
                artifact_root=root,
            )
            self.assertTrue(valid["available"])
            self.assertFalse(
                _artifact_status(
                    {"artifact_bundle": {"bundle_id": "bundle", "files": {}}},
                    artifact_root=root,
                )["available"]
            )
            self.assertFalse(
                _artifact_status(
                    {
                        "artifact_bundle": {
                            "bundle_id": "bundle",
                            "files": {"artifact.whl": "sha256:" + "0" * 64},
                        }
                    },
                    artifact_root=root,
                )["available"]
            )
            self.assertFalse(
                _artifact_status(
                    {"artifact_bundle": {"bundle_id": "../escape", "files": {}}},
                    artifact_root=root,
                )["available"]
            )
            self.assertFalse(
                _artifact_status(
                    {"artifact_bundle": {"bundle_id": str(root), "files": {}}},
                    artifact_root=root,
                )["available"]
            )
            (root / "visible").mkdir()
            (root / "visible" / "view.json").write_text('{"gold": false}', encoding="utf-8")
            opacity = _audit_opacity(root, [root / "visible"])
            self.assertFalse(opacity["valid"])
            (root / "visible" / "binary.bin").write_bytes(b"\xff\x00")
            self.assertFalse(_audit_opacity(root, [root / "visible"])["valid"])
            self.assertFalse(_audit_opacity(root, [root / "missing"])["valid"])

            from radar_bench.release import MAX_RUNTIME_FILE_BYTES

            (root / "visible" / "oversized.bin").write_bytes(
                b"x" * (MAX_RUNTIME_FILE_BYTES + 1)
            )
            oversized = _audit_opacity(root, [root / "visible"])
            self.assertFalse(oversized["valid"])
            self.assertTrue(
                any(
                    item["reason"].endswith("size limit")
                    for item in oversized["violations"]
                )
            )

    def test_historical_manifest_audit_records_each_blocker(self) -> None:
        from radar_bench.release import _audit_historical_case

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "suite"
            base.mkdir()
            self.assertFalse(_audit_historical_case(root, {"case_id": "A", "manifest": "missing.json"}, base)["valid"])
            self.assertFalse(_audit_historical_case(root, {"case_id": "A", "manifest": "../../outside.json"}, base)["valid"])
            manifest_path = base / "case.json"
            manifest_path.write_text(
                '{"case_id":"OTHER","status":"OPEN","container":{"network":"bridge","architecture":"arm64"},"execution":null}',
                encoding="utf-8",
            )
            result = _audit_historical_case(root, {"case_id": "A", "manifest": "case.json"}, base)
            self.assertFalse(result["valid"])
            self.assertGreaterEqual(len(result["errors"]), 5)

    def test_suite_audit_reports_missing_runtime_gold_and_baseline_paths(self) -> None:
        from radar_bench.release import validate_decisive_suite

        suite = {
            "suite_id": "decisive-v1",
            "historical_cases": [],
            "safety_cases": {"runtime_manifest": "C:/outside.json", "evaluator_labels": "C:/labels.json"},
            "baselines": [
                {"id": "bad-git", "source": "git:other"},
                {"id": "escape", "source": "../outside", "source_digest": "sha256:" + "0" * 64},
                {"id": "missing", "source": "missing.json", "source_digest": "sha256:" + "0" * 64},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("radar_bench.release.load_suite", return_value=suite):
                result = validate_decisive_suite(root)
        self.assertFalse(result["valid"])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime.json"
            labels = root / "labels.json"
            runtime.write_text(json.dumps({"cases": [{"corpus_kind": "safety"}] * 20}), encoding="utf-8")
            label_values = {f"T{i:02d}": {"should_abstain": i != 1} for i in range(1, 21)}
            labels.write_text(json.dumps({"cases": label_values}), encoding="utf-8")
            suite["safety_cases"] = {"runtime_manifest": "../runtime.json", "evaluator_labels": "../labels.json"}
            with patch("radar_bench.release.load_suite", return_value=suite):
                result = validate_decisive_suite(root)
        self.assertFalse(result["valid"])

        with patch("radar_bench.release.load_suite", return_value=suite), patch(
            "radar_bench.release._resolve_inside", return_value=(None, "path rejected")
        ):
            result = validate_decisive_suite(Path(directory))
        self.assertFalse(result["valid"])
        self.assertTrue(any("evaluator labels" in error for error in result["errors"]))

        suite["safety_cases"] = {"runtime_manifest": "runtime.json", "evaluator_labels": "labels.json"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "artifacts" / "v1.0"
            reference.mkdir(parents=True)
            (reference / "canonical-results.json").write_text("not-json", encoding="utf-8")
            with patch("radar_bench.release.load_suite", return_value=suite):
                result = validate_decisive_suite(root)
        self.assertFalse(result["valid"])

    def test_reference_and_inspection_paths_are_checked(self) -> None:
        from radar_bench.release import inspect_case, write_evaluation

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            result = write_evaluation(Path.cwd(), output)
            self.assertTrue(output.is_file())
            self.assertIn(result["status"], {"BLOCKED", "COMPLETED", "INVALID"})
        self.assertFalse(inspect_case(Path.cwd(), "RADAR-V07-A01")["runtime_visible"])
        self.assertTrue(inspect_case(Path.cwd(), "RADAR-V07-T01")["runtime_visible"])
        with self.assertRaises(ValueError):
            inspect_case(Path.cwd(), "UNKNOWN")

    def test_suite_audit_rejects_non_abstaining_safety_label(self) -> None:
        from radar_bench.release import validate_decisive_suite

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "corpus" / "v0.7" / "decisive-v1"
            base.mkdir(parents=True)
            (base / "runtime.json").write_text(
                json.dumps({"cases": [{"corpus_kind": "safety"}] * 20}),
                encoding="utf-8",
            )
            (base / "labels.json").write_text(
                json.dumps(
                    {
                        "cases": {
                            f"T{i:02d}": {"should_abstain": i != 1}
                            for i in range(1, 21)
                        }
                    }
                ),
                encoding="utf-8",
            )
            suite = {
                "suite_id": "decisive-v1",
                "historical_cases": [],
                "safety_cases": {
                    "runtime_manifest": "runtime.json",
                    "evaluator_labels": "labels.json",
                },
                "baselines": [],
            }
            with patch("radar_bench.release.load_suite", return_value=suite):
                result = validate_decisive_suite(root)
        self.assertFalse(result["valid"])
        self.assertIn(
            "every safety twin must have an evaluator abstention label",
            result["errors"],
        )

    def test_invalid_root_and_live_harness_branch_are_explicit(self) -> None:
        from radar_bench.release import evaluate_decisive_suite, validate_decisive_suite

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audit = validate_decisive_suite(root)
            self.assertFalse(audit["valid"])
            result = evaluate_decisive_suite(root)
            self.assertEqual(result["status"], "INVALID")

        valid_audit = {"valid": True, "historical": [], "safety": {"count": 0}}
        with patch("radar_bench.release.validate_decisive_suite", return_value=valid_audit), patch(
            "radar_bench.release.inspect_docker_runtime",
            return_value=DockerRuntime(available=True, supported=True, engine_os="linux", engine_architecture="x86_64", reason=None),
        ), patch(
            "radar_bench.release.reconstruct_historical_cases",
            return_value={"status": "READY", "blockers": [], "cases": []},
        ):
            result = evaluate_decisive_suite(Path("."))
        self.assertEqual(result["blockers"], ["EXECUTOR_HARNESS_UNAVAILABLE"])
        with patch("radar_bench.release.validate_decisive_suite", return_value=valid_audit), patch(
            "radar_bench.release.inspect_docker_runtime",
            return_value=DockerRuntime(available=False, supported=False, engine_os=None, engine_architecture=None, reason="RUNTIME_UNAVAILABLE"),
        ):
            result = evaluate_decisive_suite(Path("."))
        self.assertEqual(result["blockers"], ["RUNTIME_UNAVAILABLE"])

    def test_subprocess_provider_rejects_bad_shapes(self) -> None:
        from radar_bench.providers.subprocess_provider import SubprocessProvider

        with patch(
            "radar_bench.providers.subprocess_provider.subprocess.run",
            return_value=subprocess.CompletedProcess(["provider"], 1, "", ""),
        ):
            with self.assertRaises(RuntimeError):
                SubprocessProvider(["provider"]).predict({})
        with patch(
            "radar_bench.providers.subprocess_provider.subprocess.run",
            return_value=subprocess.CompletedProcess(["provider"], 0, "[]", ""),
        ):
            with self.assertRaises(TypeError):
                SubprocessProvider(["provider"]).predict({})


if __name__ == "__main__":
    unittest.main()
