from __future__ import annotations

import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

from radar_bench.execution.docker_runtime import DockerRuntime
from radar_bench.historical_runtime import (
    _catalog_files,
    _build_side,
    _dockerfile,
    _ensure_base_image,
    _exact_python,
    _remove_image,
    _run_case_side,
    _run_docker,
    _read_json,
    _safe_repo_path,
    _valid_command,
    load_runtime_recipes,
    reconstruct_historical_cases,
    validate_runtime_recipes,
)

ROOT = Path(__file__).resolve().parents[1]


class HistoricalRuntimeContractTests(unittest.TestCase):
    def test_public_runtime_recipes_are_valid(self) -> None:
        result = validate_runtime_recipes(ROOT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["recipe_count"], 5)

    def test_missing_recipe_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = validate_runtime_recipes(Path(temporary))
        self.assertFalse(result["valid"])
        self.assertEqual(result["recipe_count"], 0)

    def test_recipe_rejects_shell_syntax(self) -> None:
        document = load_runtime_recipes(ROOT)
        modified = copy.deepcopy(document)
        modified["recipes"][0]["control"]["command"] = ["python", "-c", "bad;command"]
        with patch("radar_bench.historical_runtime.load_runtime_recipes", return_value=modified):
            result = validate_runtime_recipes(ROOT)
        self.assertFalse(result["valid"])
        self.assertTrue(any("shell syntax" in error for error in result["errors"]))

    def test_recipe_rejects_multiple_artifact_bundles(self) -> None:
        document = copy.deepcopy(load_runtime_recipes(ROOT))
        document["recipes"][0]["artifacts"].append("pandas-45601-wheelhouse")
        with patch("radar_bench.historical_runtime.load_runtime_recipes", return_value=document):
            result = validate_runtime_recipes(ROOT)
        self.assertFalse(result["valid"])

    def test_recipe_digest_is_stable_for_current_file(self) -> None:
        result = validate_runtime_recipes(ROOT)
        self.assertRegex(result["recipe_digest"], r"^sha256:[0-9a-f]{64}$")

    def test_malformed_recipe_document_reports_contract_errors(self) -> None:
        malformed = {
            "schema_version": "0.0",
            "suite_id": "wrong",
            "network_policy": {},
            "build": {},
            "recipes": [
                {
                    "case_id": "BAD",
                    "recipe_id": "bad/id",
                    "platform": {"os": "windows", "architecture": "arm64", "python": "bad", "container_image": "python:latest"},
                    "artifacts": ["not-a-bundle"],
                    "reproducer": str(ROOT / "outside.py"),
                    "filesystem": {"input_mount": "/bad", "reproducer_mount": "/bad", "input_files": ["../bad"]},
                    "preparation": [{"side": "candidate", "command": ["bash"], "writes": ["bad"]}],
                    "control": {"packages": [None, {"name": "", "version": "", "wheel": "bad"}], "environment": {"BAD-KEY": "x\n"}, "command": ["bash", "x" * 513], "expected_exit": 999},
                    "candidate": "invalid",
                    "expected": {"control_exit": 4, "candidate_exit": 4, "root_cause_repository": "bad"},
                }
            ],
        }
        with patch("radar_bench.historical_runtime.load_runtime_recipes", return_value=malformed):
            result = validate_runtime_recipes(ROOT)
        self.assertFalse(result["valid"])
        self.assertGreaterEqual(len(result["errors"]), 9)

    def test_path_and_catalog_validation_fail_closed(self) -> None:
        self.assertIsNotNone(_safe_repo_path(ROOT, "../escape")[1])
        self.assertEqual(_safe_repo_path(ROOT, "subdir/../file.py")[1], "path may not contain parent traversal")
        self.assertIsNotNone(_safe_repo_path(ROOT, str(ROOT / "absolute.py"))[1])
        with patch("radar_bench.historical_runtime._read_json", return_value={"bundles": "bad"}):
            self.assertTrue(_catalog_files(ROOT)[1])
        with patch("radar_bench.historical_runtime._read_json", return_value={"bundles": [{}]}):
            self.assertTrue(_catalog_files(ROOT)[1])
        with tempfile.TemporaryDirectory() as temporary:
            invalid_json = Path(temporary) / "runtime-recipes.json"
            invalid_json.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                _read_json(invalid_json)
        errors: list[str] = []
        self.assertFalse(_valid_command(None, "command", errors))
        self.assertTrue(errors)


class HistoricalRuntimeDockerTests(unittest.TestCase):
    def test_run_docker_success_timeout_and_os_error(self) -> None:
        completed = subprocess.CompletedProcess(["docker"], 0, b"ok", b"")
        with patch("radar_bench.historical_runtime.subprocess.run", return_value=completed):
            result = _run_docker(["docker", "info"], timeout=1)
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["output_bytes"], 2)
        with patch(
            "radar_bench.historical_runtime.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["docker"], 1),
        ):
            self.assertTrue(_run_docker(["docker", "info"], timeout=1)["timed_out"])
        with patch(
            "radar_bench.historical_runtime.subprocess.run",
            side_effect=OSError("missing"),
        ):
            self.assertEqual(_run_docker(["docker", "info"], timeout=1)["error_type"], "OSError")
        oversized = subprocess.CompletedProcess(["docker"], 0, b"x" * (256 * 1024 + 1), b"")
        with patch("radar_bench.historical_runtime.subprocess.run", return_value=oversized):
            self.assertEqual(_run_docker(["docker", "build"], timeout=1)["error_type"], "OUTPUT_LIMIT_EXCEEDED")

    def test_ensure_base_image_uses_pull_only_when_missing(self) -> None:
        with patch(
            "radar_bench.historical_runtime._run_docker",
            side_effect=[{"returncode": 0}],
        ):
            self.assertEqual(_ensure_base_image("docker", "python@sha256:" + "a" * 64), (True, False, None))
        with patch(
            "radar_bench.historical_runtime._run_docker",
            side_effect=[{"returncode": 1}, {"returncode": 0}, {"returncode": 0}],
        ):
            self.assertEqual(_ensure_base_image("docker", "python@sha256:" + "a" * 64), (True, True, None))
        with patch(
            "radar_bench.historical_runtime._run_docker",
            side_effect=[{"returncode": 1}, {"returncode": 1}],
        ):
            self.assertEqual(_ensure_base_image("docker", "python@sha256:" + "a" * 64), (False, True, "BASE_IMAGE_UNAVAILABLE"))
        with patch(
            "radar_bench.historical_runtime._run_docker",
            side_effect=[{"returncode": 1}, {"returncode": 0}, {"returncode": 1}],
        ):
            self.assertEqual(_ensure_base_image("docker", "python@sha256:" + "a" * 64), (False, True, "BASE_IMAGE_UNAVAILABLE"))

    def test_exact_python_checks_the_reported_version(self) -> None:
        success = {"returncode": 0, "_output": b"Python 3.10.12\n"}
        with patch("radar_bench.historical_runtime._run_docker", return_value=success):
            self.assertEqual(_exact_python("docker", "image", "3.10.12"), (True, None))
            self.assertEqual(_exact_python("docker", "image", "3.10.1"), (False, "BASE_IMAGE_RUNTIME_MISMATCH"))
        with patch("radar_bench.historical_runtime._run_docker", return_value={"returncode": 1}):
            self.assertEqual(_exact_python("docker", "image", "3.10.12"), (False, "BASE_IMAGE_RUNTIME_UNAVAILABLE"))

    def test_dockerfile_and_runtime_command_are_network_denied(self) -> None:
        document = load_runtime_recipes(ROOT)
        recipe = dict(document["recipes"][0])
        recipe["_document_build"] = document["build"]
        dockerfile = _dockerfile(recipe, "control", [recipe["control"]["packages"][0]["wheel"]])
        self.assertIn("FROM mirror.gcr.io/library/python@sha256:", dockerfile)
        self.assertIn('"--no-index"', dockerfile)
        with tempfile.TemporaryDirectory() as temporary:
            with patch("radar_bench.historical_runtime._run_docker", return_value={"returncode": 0}) as runner:
                result = _run_case_side(
                    "docker",
                    "image",
                    "control",
                    ["python", "/reproducer/a01_pickle.py", "--read", "/input/old_pandas.pkl"],
                    {"LANG": "C.UTF-8"},
                    Path(temporary),
                )
        self.assertEqual(result["network"], "none")
        command = runner.call_args.args[0]
        self.assertIn("--network=none", command)
        self.assertIn("--read-only", command)

    def test_build_side_copies_only_selected_inputs(self) -> None:
        document = load_runtime_recipes(ROOT)
        recipe = dict(document["recipes"][0])
        recipe["_document_build"] = document["build"]
        recipe["_reproducer_path"] = str((ROOT / recipe["reproducer"]).resolve())
        with tempfile.TemporaryDirectory() as temporary:
            artifact_root = Path(temporary) / "artifacts"
            bundle = artifact_root / recipe["artifacts"][0]
            bundle.mkdir(parents=True)
            for package in recipe["control"]["packages"]:
                (bundle / package["wheel"]).write_bytes(b"wheel")
            context = Path(temporary) / "context"
            context.mkdir()
            with patch("radar_bench.historical_runtime._run_docker", return_value={"returncode": 0}):
                image, error = _build_side("docker", recipe, "control", artifact_root, context)
            self.assertIsNotNone(image)
            self.assertIsNone(error)
            self.assertTrue((context / "Dockerfile").is_file())

    def test_build_side_rejects_missing_wheel_and_build_failure(self) -> None:
        document = load_runtime_recipes(ROOT)
        recipe = dict(document["recipes"][0])
        recipe["_document_build"] = document["build"]
        recipe["_reproducer_path"] = str((ROOT / recipe["reproducer"]).resolve())
        with tempfile.TemporaryDirectory() as temporary:
            artifact_root = Path(temporary) / "artifacts"
            (artifact_root / recipe["artifacts"][0]).mkdir(parents=True)
            context = Path(temporary) / "context"
            context.mkdir()
            image, error = _build_side("docker", recipe, "control", artifact_root, context)
            self.assertIsNone(image)
            self.assertEqual(error, "ARTIFACT_UNAVAILABLE")
            bundle = artifact_root / recipe["artifacts"][0]
            for package in recipe["control"]["packages"]:
                (bundle / package["wheel"]).write_bytes(b"wheel")
            failed_context = Path(temporary) / "failed-context"
            failed_context.mkdir()
            with patch("radar_bench.historical_runtime._run_docker", return_value={"returncode": 1}):
                image, error = _build_side("docker", recipe, "control", artifact_root, failed_context)
            self.assertIsNotNone(image)
            self.assertEqual(error, "IMAGE_BUILD_FAILED")

    def test_remove_image_uses_exact_tag(self) -> None:
        with patch("radar_bench.historical_runtime._run_docker", return_value={"returncode": 0}) as runner:
            _remove_image("docker", "radar-bench-runtime-test")
        self.assertEqual(runner.call_args.args[0][-1], "radar-bench-runtime-test")


class HistoricalRuntimeOrchestrationTests(unittest.TestCase):
    def test_reconstruction_reports_all_five_when_docker_steps_match(self) -> None:
        def fake_build(_docker: str, recipe: dict[str, object], side: str, _artifact: Path, _context: Path) -> tuple[str, None]:
            return f"image-{recipe['case_id']}-{side}", None

        def fake_run(_docker: str, _image: str, side: str, command: list[str], _environment: Mapping[str, str], _input: Path, *, preparation: bool = False) -> dict[str, object]:
            if preparation:
                code = 0
            elif side == "control":
                code = 0
            elif "a05" in command[-1]:
                code = 139
            else:
                code = 1
            return {"returncode": code, "output_bytes": 0, "output_digest": "sha256:" + "0" * 64}

        with patch("radar_bench.historical_runtime.validate_runtime_recipes", return_value={"valid": True, "recipe_digest": "sha256:" + "0" * 64}), patch(
            "radar_bench.historical_runtime.verify_artifacts", return_value={"status": "READY"}
        ), patch("radar_bench.historical_runtime.shutil.which", return_value="docker"), patch(
            "radar_bench.historical_runtime.inspect_docker_runtime",
            return_value=DockerRuntime(True, True, "linux", "x86_64", None),
        ), patch("radar_bench.historical_runtime._ensure_base_image", return_value=(True, False, None)), patch(
            "radar_bench.historical_runtime._exact_python", return_value=(True, None)
        ), patch("radar_bench.historical_runtime._build_side", side_effect=fake_build), patch(
            "radar_bench.historical_runtime._run_case_side", side_effect=fake_run
        ), patch("radar_bench.historical_runtime._remove_image"):
            result = reconstruct_historical_cases(ROOT, Path("C:/external-artifacts"))
        self.assertEqual(result["status"], "READY")
        self.assertEqual(len(result["cases"]), 5)
        self.assertEqual(result["execution_network"], "none")

    def test_reconstruction_stops_before_docker_for_missing_artifacts(self) -> None:
        with patch("radar_bench.historical_runtime.verify_artifacts", return_value={"status": "BLOCKED", "errors": ["missing"]}):
            result = reconstruct_historical_cases(ROOT, Path("C:/external-artifacts"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blockers"], ["ARTIFACT_UNAVAILABLE"])


if __name__ == "__main__":
    unittest.main()
