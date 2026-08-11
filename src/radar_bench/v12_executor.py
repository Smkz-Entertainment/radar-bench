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
IMAGE_RE = r"^[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}$"


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

    def _docker_argv(self, runtime: Mapping[str, Any], side: str, command: Sequence[str], input_root: Path) -> list[str] | None:
        platform = runtime.get("platform")
        image = platform.get("container_image") if isinstance(platform, Mapping) else None
        if not isinstance(image, str) or not re.fullmatch(IMAGE_RE, image):
            return None
        workspace_info = self._workspace(runtime, side)
        if workspace_info is None:
            return None
        workspace, mount, side_value = workspace_info
        if not workspace.is_dir() or not input_root.is_dir():
            return None
        env = side_value.get("environment", {})
        if not isinstance(env, Mapping):
            return None
        argv = [
            "docker", "run", "--rm", "--name", "radar-v12-exp-" + uuid.uuid4().hex[:12],
            "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--user=65532:65532", "--memory=512m", "--memory-swap=512m", "--cpus=1", "--pids-limit=128",
            "--ulimit", "nofile=1024:1024", "--ulimit", "core=0:0",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",  # nosec B108 - container-local tmpfs, never a host path
            "--mount", f"type=bind,src={workspace},dst={mount},readonly",
            "--mount", f"type=bind,src={input_root},dst=/input",
        ]
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
            return ["python", "-c", "import json,platform,sys; print(json.dumps({'python':sys.version,'platform':platform.platform()},sort_keys=True))"]
        if capability == "inspect_dependency_graph":
            return ["python", "-c", "import importlib.metadata as m,json; print(json.dumps(sorted((d.metadata['Name'],d.version) for d in m.distributions()),sort_keys=True))"]
        declared = side_value.get("command")
        requested = request.get("parameters", {}).get("command") if isinstance(request.get("parameters"), Mapping) else None
        if requested is not None and requested != declared:
            return None
        if not isinstance(declared, list) or not declared or any(not isinstance(value, str) for value in declared):
            return None
        command = [str(value) for value in declared]
        if command[0] != "python":
            return None
        if len(command) > 1 and not command[1].startswith("/"):
            command[1] = "/workspace/" + command[1]
        return command

    def _installing_command(self, runtime: Mapping[str, Any], side: str, command: list[str], request: Mapping[str, Any]) -> list[str] | None:
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
        script = (
            "import os,subprocess,sys; "
            f"wheels={encoded}; target='/tmp/site'; "
            "subprocess.check_call([sys.executable,'-m','pip','install','--no-index','--no-cache-dir','--no-deps','--target',target] + ['/artifact/'+name for name in wheels]); "
            "os.environ['PYTHONPATH']=target; "
            "os.execvpe(sys.executable,[sys.executable] + " + repr(command) + ",os.environ)"
        )
        return ["python", "-c", script]

    def _run_side(self, runtime: Mapping[str, Any], side: str, command: list[str], input_root: Path, request: Mapping[str, Any]) -> Any:
        installing_command = self._installing_command(runtime, side, command, request)
        if installing_command is None:
            return None
        argv = self._docker_argv(runtime, side, installing_command, input_root)
        if argv is None:
            return None
        return run_bounded(argv, cwd=self.root, timeout=MAX_RUN_SECONDS, max_output_bytes=MAX_OBSERVATION_BYTES)

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
            return {"status": "INVALID_REQUEST", "observation": {"status": "COMMAND_NOT_DECLARED_BY_RECIPE"}}
        control_command = self._command_for(runtime, "control", request)
        if control_command is None:
            return {"status": "INVALID_REQUEST", "observation": {"status": "CONTROL_COMMAND_NOT_DECLARED_BY_RECIPE"}}
        with tempfile.TemporaryDirectory(prefix="radar-v12-input-") as input_dir:
            input_root = Path(input_dir)
            preparation = runtime.get("preparation", [])
            if isinstance(preparation, list):
                for step in preparation:
                    if not isinstance(step, Mapping) or not isinstance(step.get("command"), list):
                        return self._unavailable("RUNTIME_RECIPE_INVALID")
                    prep = [str(value) for value in step["command"] if isinstance(value, str)]
                    prepared = self._run_side(runtime, "control", prep, input_root, {"capability": "rerun", "parameters": {"command": prep}})
                    if prepared is None or prepared.returncode != 0:
                        return self._unavailable("PREPARATION_FAILED")
            control_capture = self._run_side(runtime, "control", control_command, input_root, request)
            capture = self._run_side(runtime, "candidate", command, input_root, request)
            if control_capture is None or capture is None:
                return self._unavailable("RUNTIME_RECIPE_INVALID")
        def summarize(value: Any) -> dict[str, Any]:
            return {
                "returncode": value.returncode,
                "output_digest": value.output_digest,
                "output_bytes": value.output_bytes,
                "output_limit_exceeded": value.output_limit_exceeded,
                "timed_out": value.timed_out,
                "excerpt": value.excerpt,
            }
        return {
            "status": "COMPLETED" if capture.returncode == 0 else "OBSERVED_FAILURE",
            "observation": {
                "control": summarize(control_capture),
                "candidate": summarize(capture),
                "useful": all(
                    value.returncode is not None and not value.timed_out and not value.output_limit_exceeded
                    for value in (control_capture, capture)
                ),
            },
        }
