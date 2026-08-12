"""Case-agnostic evaluator-owned executor for the v1.2 protocol.

This module deliberately contains no diagnosis or gold lookup.  It resolves an
opaque episode to a sealed runtime recipe supplied by the evaluator, performs
only recipe-declared Docker work, and returns bounded observations.  Missing
artifacts, Docker, or a platform are explicit unavailable observations.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

from radar_bench.artifacts import verify_artifacts
from radar_bench.execution.process import run_bounded

V12_SUITE_RELATIVE = Path("corpus/v1.1.0/decisive-v1.2/suite.json")
V12_RECIPE_RELATIVE = V12_SUITE_RELATIVE.parent / "runtime-recipes.json"
SAFETY_MANIFEST_RELATIVE = Path("corpus/v1.0.1/safety-twins/runtime-manifest.json")
MAX_OBSERVATION_BYTES = 64 * 1024
MAX_RUN_SECONDS = 180
MAX_PREPARATION_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_PREPARATION_OUTPUT_FILES = 16
IMAGE_RE = r"^[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}$"
APPROVED_PYTHON_EXECUTABLES = frozenset({"python", "python3", "python3.11", "python3.12", "python3.13"})


def normalize_python_command(command: Sequence[Any], *, interpreter: str | None = None) -> list[str]:
    """Normalize a recipe's portable Python argv exactly once."""

    values = list(command)
    if not values or any(not isinstance(value, str) for value in values):
        raise ValueError("Python command must be a non-empty string array")
    if values[0] not in APPROVED_PYTHON_EXECUTABLES:
        raise ValueError("Python command must start with an approved Python executable")
    if len(values) == 1:
        raise ValueError("Python command must include a script or -c argument")
    return [interpreter or sys.executable, *values[1:]]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return cast(dict[str, Any], value)


class V12ExperimentExecutor:
    """Execute declared runtime capabilities without exposing evaluator gold."""

    def __init__(self, root: Path, *, episode_to_case: Mapping[str, str], artifact_root: Path | None = None) -> None:
        self.root = root.resolve()
        self.episode_to_case = dict(episode_to_case)
        self.artifact_root = artifact_root.resolve() if artifact_root is not None else None
        self.recipes = self._load_recipes()
        self.safety = self._load_safety()
        self.artifact_status = (
            verify_artifacts(self.root, "decisive-v1.2", self.artifact_root)
            if self.artifact_root is not None
            else {"status": "BLOCKED", "reason": "artifact root was not supplied"}
        )

    def _load_recipes(self) -> dict[str, Mapping[str, Any]]:
        path = self.root / V12_RECIPE_RELATIVE
        if not path.is_file():
            return {}
        try:
            records = _read_json(path).get("recipes")
        except (OSError, ValueError):
            return {}
        return {
            str(item["case_id"]): cast(Mapping[str, Any], item)
            for item in records
            if isinstance(item, Mapping) and isinstance(item.get("case_id"), str)
        } if isinstance(records, list) else {}

    def _load_safety(self) -> dict[str, Mapping[str, Any]]:
        path = self.root / SAFETY_MANIFEST_RELATIVE
        if not path.is_file():
            return {}
        try:
            records = _read_json(path).get("cases")
        except (OSError, ValueError):
            return {}
        return {
            str(item["case_id"]): cast(Mapping[str, Any], item)
            for item in records
            if isinstance(item, Mapping) and isinstance(item.get("case_id"), str)
        } if isinstance(records, list) else {}

    def _unavailable(self, code: str, **detail: Any) -> Mapping[str, Any]:
        return {"status": "UNAVAILABLE", "observation": {"status": code, **detail}}

    def _runtime(self, case_id: str) -> Mapping[str, Any] | None:
        return self.recipes.get(case_id) or self.safety.get(case_id)

    def _workspace(self, runtime: Mapping[str, Any], side: str) -> tuple[Path, str, Mapping[str, Any]] | None:
        value = runtime.get(side)
        if not isinstance(value, Mapping):
            return None
        workspace = value.get("workspace")
        mount = "/workspace"
        if not isinstance(workspace, str):
            reproducer = runtime.get("reproducer")
            if not isinstance(reproducer, str):
                return None
            workspace = str(Path(reproducer).parent)
            mount = "/reproducer"
        if Path(workspace).is_absolute() or ".." in Path(workspace).parts:
            return None
        path = (self.root / workspace).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            return None
        return path, mount, value

    def _docker_argv(
        self,
        runtime: Mapping[str, Any],
        side: str,
        command: Sequence[str],
        input_source: Path | str,
        *,
        input_volume: bool = False,
        preparation: bool = False,
        site_volume: str | None = None,
    ) -> list[str] | None:
        platform = runtime.get("platform")
        image = platform.get("container_image") if isinstance(platform, Mapping) else None
        if not isinstance(image, str) or not re.fullmatch(IMAGE_RE, image):
            return None
        workspace_info = self._workspace(runtime, side)
        if workspace_info is None:
            return None
        workspace, mount, side_value = workspace_info
        if not workspace.is_dir() or (not input_volume and (not isinstance(input_source, Path) or not input_source.is_dir())):
            return None
        env = side_value.get("environment", {})
        if not isinstance(env, Mapping):
            return None
        argv = [
            "docker", "run", "--name", "radar-v12-exp-" + uuid.uuid4().hex[:12],
            "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--user=0:0" if preparation else "--user=65532:65532", "--memory=512m", "--memory-swap=512m", "--cpus=1", "--pids-limit=128",
            "--ulimit", "nofile=1024:1024", "--ulimit", "core=0:0",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=512m,mode=1777",  # nosec B108 - container-local tmpfs, never a host path
            "--workdir", mount,
            "--mount", f"type=bind,src={workspace},dst={mount},readonly",
        ]
        if input_volume:
            suffix = "" if preparation else ",readonly"
            argv.extend(["--mount", f"type=volume,source={input_source},dst=/input{suffix}"])
        else:
            argv.extend(["--mount", f"type=bind,src={input_source},dst=/input,readonly"])
        if site_volume is not None:
            if not re.fullmatch(r"radar-v12-site-[0-9a-f]{16}", site_volume):
                return None
            argv.extend(["--mount", f"type=volume,source={site_volume},dst=/opt/radar/site,volume-nocopy"])
        artifacts = runtime.get("artifacts")
        if isinstance(artifacts, list) and len(artifacts) == 1 and isinstance(artifacts[0], str):
            if self.artifact_root is None:
                return None
            bundle = (self.artifact_root / artifacts[0]).resolve()
            try:
                bundle.relative_to(self.artifact_root)
            except ValueError:
                return None
            if not bundle.is_dir():
                return None
            argv.extend(["--mount", f"type=bind,src={bundle},dst=/artifact,readonly"])
        for key, value in sorted(env.items()):
            if not isinstance(key, str) or not key or not isinstance(value, str) or "\n" in value or "\r" in value:
                return None
            argv.extend(["--env", f"{key}={value}"])
        argv.extend(["--env", "PYTHONUNBUFFERED=1", image])
        argv.extend(command)
        return argv

    def _command_for(self, runtime: Mapping[str, Any], side: str, request: Mapping[str, Any]) -> list[str] | None:
        side_value = runtime.get(side)
        if not isinstance(side_value, Mapping):
            return None
        capability = request.get("capability")
        if capability == "inspect_environment":
            return ["python", "-c", "import importlib.metadata as m,json,os,platform,sys; allow={'LANG','LC_ALL','RADAR_PLATFORM','RADAR_PROFILE','RADAR_SIDE'}; value={'python':sys.version,'platform':platform.platform(),'packages':sorted((d.metadata.get('Name'),d.version) for d in m.distributions())[:256],'environment':{k:os.environ[k] for k in sorted(allow) if k in os.environ}}; print(json.dumps(value,sort_keys=True))"]
        if capability == "inspect_dependency_graph":
            return ["python", "-c", "import importlib.metadata as m,json; print(json.dumps({'packages':sorted((d.metadata.get('Name'),d.version) for d in m.distributions())[:256]},sort_keys=True))"]
        parameters = request.get("parameters")
        if capability == "run_minimal_test" and (not isinstance(parameters, Mapping) or parameters.get("test_id") != "sealed-reproducer"):
            return None
        if capability == "change_dependency_version" and not isinstance(runtime.get("artifacts"), list):
            return None
        declared = side_value.get("command")
        if not isinstance(declared, list) or not declared or any(not isinstance(value, str) for value in declared):
            return None
        try:
            command = normalize_python_command(declared, interpreter="python")
        except ValueError:
            return None
        return command

    def _installing_command(
        self,
        runtime: Mapping[str, Any],
        side: str,
        command: list[str],
        request: Mapping[str, Any],
        *,
        site_path: str = "/opt/radar/site",
    ) -> list[str] | None:
        side_value = runtime.get(side)
        packages = side_value.get("packages", []) if isinstance(side_value, Mapping) else []
        wheels = [item.get("wheel") for item in packages if isinstance(item, Mapping) and isinstance(item.get("wheel"), str)]
        artifacts = runtime.get("artifacts")
        if not wheels or not isinstance(artifacts, list):
            return command
        if request.get("capability") == "change_dependency_version" and side == "candidate":
            parameters = request.get("parameters")
            target = parameters.get("target_component") if isinstance(parameters, Mapping) else None
            version = parameters.get("version") if isinstance(parameters, Mapping) else None
            if not isinstance(target, str) or not isinstance(version, str):
                return None
            replacement: str | None = None
            for candidate_side in ("control", "candidate"):
                candidate_packages = runtime.get(candidate_side, {}).get("packages", []) if isinstance(runtime.get(candidate_side), Mapping) else []
                for package in candidate_packages:
                    if isinstance(package, Mapping) and str(package.get("name", "")).lower().replace("-", "_") == target.lower().replace("-", "_") and package.get("version") == version and isinstance(package.get("wheel"), str):
                        replacement = str(package["wheel"])
                        break
                if replacement is not None:
                    break
            if replacement is None:
                return None
            target_name = target.lower().replace("-", "_")
            replaced = False
            wheels = [
                replacement if isinstance(package, Mapping) and str(package.get("name", "")).lower().replace("-", "_") == target_name else wheel
                for package, wheel in zip(packages, wheels)
            ]
            replaced = replacement in wheels
            if not replaced:
                wheels.append(replacement)
        encoded = repr(wheels)
        normalized = normalize_python_command(command, interpreter="python")
        script = (
            "import os,subprocess,sys; "
            f"wheels={encoded}; target={site_path!r}; "
            "subprocess.check_call([sys.executable,'-m','pip','install','--no-index','--no-cache-dir','--no-deps','--target',target] + ['/artifact/'+name for name in wheels]); "
            "os.environ['PYTHONPATH']=target; "
            "os.execvpe(sys.executable," + repr(normalized) + ",os.environ)"
        )
        return ["python", "-c", script]

    @staticmethod
    def _requires_site_volume(runtime: Mapping[str, Any], side: str) -> bool:
        side_value = runtime.get(side)
        packages = side_value.get("packages", []) if isinstance(side_value, Mapping) else []
        artifacts = runtime.get("artifacts")
        return isinstance(artifacts, list) and any(
            isinstance(item, Mapping) and isinstance(item.get("wheel"), str)
            for item in packages
        )

    def _run_side(
        self,
        runtime: Mapping[str, Any],
        side: str,
        command: list[str],
        input_source: Path | str,
        request: Mapping[str, Any],
        *,
        input_volume: bool = False,
        preparation: bool = False,
    ) -> Any:
        site_volume: str | None = None
        container_name: str | None = None
        container_cleanup: dict[str, Any] | None = None
        result: Any = None
        try:
            needs_site_volume = self._requires_site_volume(runtime, side)
            site_path = "/opt/radar/site"
            if needs_site_volume:
                site_volume = "radar-v12-site-" + uuid.uuid4().hex[:16]
                docker = shutil.which("docker") or "docker"
                site_owner = "0" if preparation else "65532"
                created = run_bounded(
                    [
                        docker, "volume", "create", "--driver", "local", "--opt", "type=tmpfs",
                        "--opt", "device=tmpfs", "--opt", f"o=uid={site_owner},gid={site_owner},mode=0755,nosuid,nodev,size=1024m",
                        site_volume,
                    ],
                    timeout=30,
                    max_output_bytes=MAX_OBSERVATION_BYTES,
                )
                if created.returncode != 0:
                    return None
            installing_command = self._installing_command(runtime, side, command, request, site_path=site_path)
            if installing_command is not None:
                argv = self._docker_argv(
                    runtime,
                    side,
                    installing_command,
                    input_source,
                    input_volume=input_volume,
                    preparation=preparation,
                    site_volume=site_volume,
                )
                if argv is not None:
                    container_name = argv[argv.index("--name") + 1]
                    capture = run_bounded(argv, cwd=self.root, timeout=MAX_RUN_SECONDS, max_output_bytes=MAX_OBSERVATION_BYTES)
                    container_cleanup = self._cleanup_container(container_name)
                    result = capture
                    if not container_cleanup["cleanup_verified"]:
                        result = capture.__class__(**{**capture.__dict__, "cleanup_error": "CONTAINER_CLEANUP_UNVERIFIED"})
        finally:
            if container_name is not None and container_cleanup is None:
                container_cleanup = self._cleanup_container(container_name)
                if result is not None and not container_cleanup["cleanup_verified"]:
                    result = result.__class__(**{**result.__dict__, "cleanup_error": "CONTAINER_CLEANUP_UNVERIFIED"})
            if site_volume is not None:
                site_cleanup = self._cleanup_volume(site_volume)
                if result is not None and not site_cleanup["cleanup_verified"]:
                    result = result.__class__(**{**result.__dict__, "cleanup_error": "SITE_VOLUME_CLEANUP_UNVERIFIED"})
        return result

    def _cleanup_container(self, name: str) -> dict[str, Any]:
        docker = shutil.which("docker") or "docker"
        first = run_bounded([docker, "inspect", name], timeout=30, max_output_bytes=MAX_OBSERVATION_BYTES)
        if first.returncode != 0:
            absent = "no such object" in first.excerpt.lower() or "no such container" in first.excerpt.lower()
            return {"cleanup_verified": absent, "present_after_cleanup": False}
        removed = run_bounded([docker, "rm", "-f", name], timeout=30, max_output_bytes=MAX_OBSERVATION_BYTES)
        final = run_bounded([docker, "inspect", name], timeout=30, max_output_bytes=MAX_OBSERVATION_BYTES)
        absent = final.returncode != 0 and ("no such object" in final.excerpt.lower() or "no such container" in final.excerpt.lower())
        return {"cleanup_verified": removed.returncode == 0 and absent, "present_after_cleanup": not absent}

    def _cleanup_volume(self, name: str) -> dict[str, Any]:
        docker = shutil.which("docker") or "docker"
        removed = run_bounded([docker, "volume", "rm", "--force", name], timeout=30, max_output_bytes=MAX_OBSERVATION_BYTES)
        inspected = run_bounded([docker, "volume", "ls", "--filter", f"name=^{name}$", "--format", "{{.Name}}"], timeout=30, max_output_bytes=MAX_OBSERVATION_BYTES)
        present = any(line.strip() == name for line in inspected.excerpt.splitlines())
        return {"cleanup_verified": removed.returncode == 0 and inspected.returncode == 0 and not present, "present_after_cleanup": present}

    def _copy_volume_to_staging(self, runtime: Mapping[str, Any], volume_name: str, staging: Path) -> Any:
        platform = runtime.get("platform")
        image = platform.get("container_image") if isinstance(platform, Mapping) else None
        if not isinstance(image, str) or not re.fullmatch(IMAGE_RE, image):
            return None
        docker = shutil.which("docker") or "docker"
        name = "radar-v12-inventory-" + uuid.uuid4().hex[:12]
        argv = [
            docker, "run", "--name", name, "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--user=0:0", "--memory=512m", "--memory-swap=512m",
            "--cpus=1", "--pids-limit=128", "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777",  # nosec B108 - container-local tmpfs, never a host path
            "--mount", f"type=volume,source={volume_name},dst=/input,readonly",
            "--mount", f"type=bind,src={staging},dst=/output",
            image, "python", "-c", "import shutil; shutil.copytree('/input','/output',dirs_exist_ok=True)",
        ]
        capture = run_bounded(argv, cwd=self.root, timeout=MAX_RUN_SECONDS, max_output_bytes=MAX_OBSERVATION_BYTES)
        cleanup = self._cleanup_container(name)
        if not cleanup["cleanup_verified"]:
            return capture.__class__(**{**capture.__dict__, "cleanup_error": "CONTAINER_CLEANUP_UNVERIFIED"})
        return capture

    @staticmethod
    def _audit_preparation_output(staging: Path, declared: Sequence[str]) -> tuple[bool, str | None, dict[str, Any]]:
        observed: list[str] = []
        total = 0
        for path in staging.rglob("*"):
            relative = path.relative_to(staging).as_posix()
            observed.append(relative)
            if path.is_symlink() or not path.is_file():
                return False, "PREPARATION_OUTPUT_INVALID", {"observed": sorted(observed)}
            if path.stat().st_nlink != 1:
                return False, "PREPARATION_OUTPUT_HARDLINK", {"observed": sorted(observed)}
            total += path.stat().st_size
            if len(observed) > MAX_PREPARATION_OUTPUT_FILES:
                return False, "PREPARATION_OUTPUT_TOO_MANY_FILES", {"observed": sorted(observed)}
            if total > MAX_PREPARATION_OUTPUT_BYTES:
                return False, "PREPARATION_OUTPUT_TOO_LARGE", {"observed": sorted(observed)}
        expected = sorted(str(item) for item in declared)
        if sorted(observed) != expected:
            return False, "PREPARATION_OUTPUT_INVENTORY_MISMATCH", {"expected": expected, "observed": sorted(observed)}
        return True, None, {"expected": expected, "observed": sorted(observed), "bytes": total}

    @staticmethod
    def _capture_is_complete(value: Any) -> bool:
        return value.returncode is not None and not value.timed_out and not value.output_limit_exceeded and value.cleanup_error is None

    def _evaluator_receipt(self, request: Mapping[str, Any], control: Any, candidate: Any) -> dict[str, Any]:
        complete = self._capture_is_complete(control) and self._capture_is_complete(candidate)
        changed = control.returncode != candidate.returncode or control.output_digest != candidate.output_digest
        useful = complete and (changed or request.get("capability") in {"inspect_environment", "inspect_dependency_graph"})
        return {"schema_version": "1", "executor_calls": 2, "fresh": complete, "available": complete, "useful": useful, "cache_hit": False, "reused": False, "cleanup_verified": complete}

    def __call__(self, episode_id: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        case_id = self.episode_to_case.get(episode_id)
        if case_id is None:
            return self._unavailable("EPISODE_NOT_BOUND")
        runtime = self._runtime(case_id)
        if runtime is None:
            return self._unavailable("RUNTIME_RECIPE_UNAVAILABLE")
        if self.artifact_root is None and case_id in self.recipes:
            return self._unavailable("ARTIFACT_UNAVAILABLE")
        if self.artifact_root is not None and case_id in self.recipes:
            if self.artifact_status.get("status") != "READY":
                return self._unavailable("ARTIFACT_UNAVAILABLE", detail=self.artifact_status)
        if shutil.which("docker") is None:
            return self._unavailable("DOCKER_UNAVAILABLE")
        command = self._command_for(runtime, "candidate", request)
        if command is None:
            if request.get("capability") == "change_dependency_version":
                return {"status": "UNSUPPORTED_EXPERIMENT", "observation": {"status": "APPROVED_VERSION_NOT_AVAILABLE"}}
            return {"status": "INVALID_REQUEST", "observation": {"status": "COMMAND_NOT_DECLARED_BY_RECIPE"}}
        control_command = self._command_for(runtime, "control", request)
        if control_command is None:
            return {"status": "INVALID_REQUEST", "observation": {"status": "CONTROL_COMMAND_NOT_DECLARED_BY_RECIPE"}}
        with tempfile.TemporaryDirectory(prefix="radar-v12-input-") as input_dir:
            input_root = Path(input_dir)
            preparation = runtime.get("preparation", [])
            if not isinstance(preparation, list):
                return self._unavailable("RUNTIME_RECIPE_INVALID")
            input_source: Path | str = input_root
            volume_name: str | None = None
            volume_created = False
            result: Mapping[str, Any] | None = None
            try:
                if preparation:
                    docker = shutil.which("docker") or "docker"
                    volume_name = "radar-v12-input-" + uuid.uuid4().hex[:16]
                    created = run_bounded([docker, "volume", "create", volume_name], timeout=30, max_output_bytes=MAX_OBSERVATION_BYTES)
                    if created.returncode != 0:
                        result = self._unavailable("PREPARATION_VOLUME_UNAVAILABLE")
                    else:
                        volume_created = True
                        input_source = volume_name
                        for step in preparation:
                            if not isinstance(step, Mapping) or not isinstance(step.get("command"), list) or not isinstance(step.get("writes"), list):
                                result = self._unavailable("RUNTIME_RECIPE_INVALID")
                                break
                            prep = [str(value) for value in step["command"] if isinstance(value, str)]
                            prepared = self._run_side(runtime, "control", prep, input_source, {"capability": "rerun", "parameters": {}}, input_volume=True, preparation=True)
                            if prepared is None or prepared.returncode != 0 or prepared.cleanup_error:
                                result = self._unavailable("PREPARATION_FAILED")
                                break
                        if result is None:
                            staging = Path(input_dir) / "prepared-output"
                            staging.mkdir()
                            copied = self._copy_volume_to_staging(runtime, volume_name, staging)
                            if copied is None or copied.returncode != 0 or copied.cleanup_error:
                                result = self._unavailable("PREPARATION_OUTPUT_UNAVAILABLE")
                        if result is None:
                            for step in preparation:
                                ok, error, inventory = self._audit_preparation_output(staging, cast(Sequence[str], step["writes"]))
                                if not ok:
                                    result = self._unavailable(error or "PREPARATION_OUTPUT_INVALID", inventory=inventory)
                                    break
                if result is None:
                    control_capture = self._run_side(runtime, "control", control_command, input_source, request, input_volume=volume_name is not None)
                    capture = self._run_side(runtime, "candidate", command, input_source, request, input_volume=volume_name is not None)
                    if control_capture is None or capture is None:
                        result = self._unavailable("RUNTIME_RECIPE_INVALID")
                    else:
                        def summarize(value: Any) -> dict[str, Any]:
                            return {
                                "returncode": value.returncode,
                                "output_digest": value.output_digest,
                                "output_bytes": value.output_bytes,
                                "output_limit_exceeded": value.output_limit_exceeded,
                                "timed_out": value.timed_out,
                                "cleanup_error": value.cleanup_error,
                                "excerpt": value.excerpt,
                            }
                        result = {
                            "status": "COMPLETED" if capture.returncode == 0 else "OBSERVED_FAILURE",
                            "observation": {
                                "control": summarize(control_capture),
                                "candidate": summarize(capture),
                                "useful": all(
                                    self._capture_is_complete(value)
                                    for value in (control_capture, capture)
                                ),
                            },
                            "evaluator_receipt": self._evaluator_receipt(request, control_capture, capture),
                        }
            finally:
                if volume_created and volume_name is not None:
                    cleanup = self._cleanup_volume(volume_name)
                    if not cleanup["cleanup_verified"]:
                        result = self._unavailable("PREPARATION_VOLUME_CLEANUP_FAILED", cleanup=cleanup)
            if result is None:
                result = self._unavailable("RUNTIME_RECIPE_INVALID")
            return result
