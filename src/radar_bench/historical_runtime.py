"""Reconstruct and execute the five sealed historical runtimes.

Historical wheel bytes remain external to the repository.  This module is the
small bridge between the public recipe contract and Docker: it verifies the
external wheelhouses, builds each side from a digest-pinned base image without
network access, and executes only fixed argument arrays in a denied-network,
read-only container.

The result is deliberately an execution report, not an investigator result.
It can prove that a historical control/candidate pair replays, but it cannot
turn that evidence into attribution or a release certification by itself.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess  # nosec B404 - fixed Docker argv, shell disabled
import tempfile
import uuid
from pathlib import Path
from typing import Any, Mapping, cast

from radar_bench.artifacts import verify_artifacts
from radar_bench.execution.docker_runtime import inspect_docker_runtime

SUITE_ID = "decisive-v1"
RUNTIME_RECIPES_RELATIVE = Path("corpus/v0.7/decisive-v1/runtime-recipes.json")
HISTORICAL_CASE_IDS = {
    "RADAR-V07-A01",
    "RADAR-V07-A02",
    "RADAR-V07-A03",
    "RADAR-V07-A04",
    "RADAR-V07-A05",
}
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_COMMAND_OUTPUT_BYTES = 256 * 1024
DOCKER_PULL_TIMEOUT_SECONDS = 600
DOCKER_BUILD_TIMEOUT_SECONDS = 900
DOCKER_RUN_TIMEOUT_SECONDS = 180
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9./_-]*@sha256:[0-9a-f]{64}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REPOSITORY_RE = re.compile(r"^[a-z0-9_.-]+/[a-z0-9_.-]+$")
_SHELL_TOKENS = (";", "&&", "||", "|", "`", "$(", "\n", "\r")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError(f"runtime recipe file is absent or too large: {RUNTIME_RECIPES_RELATIVE}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("runtime recipe document must be an object")
    return cast(dict[str, Any], value)


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _safe_repo_path(root: Path, value: object) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None, "path must be a non-empty repository-relative string"
    candidate = (root / Path(value)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None, "path escapes the repository"
    if ".." in Path(value).parts:
        return None, "path may not contain parent traversal"
    return candidate, None


def _safe_name(value: object) -> bool:
    return isinstance(value, str) and bool(_NAME_RE.fullmatch(value))


def _safe_container_path(value: object, expected: str) -> bool:
    return isinstance(value, str) and value == expected


def _valid_command(value: object, label: str, errors: list[str]) -> bool:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        errors.append(f"{label} must be a non-empty command array")
        return False
    command = cast(list[str], value)
    if command[0] != "python":
        errors.append(f"{label} must start with python")
    for item in command:
        if any(token in item for token in _SHELL_TOKENS):
            errors.append(f"{label} contains shell syntax")
            break
        if len(item) > 512:
            errors.append(f"{label} contains an overlong argument")
            break
    return True


def _catalog_files(root: Path) -> tuple[dict[str, set[str]], list[str]]:
    path = root / "corpus" / "v0.7" / "decisive-v1" / "artifact-catalog.json"
    errors: list[str] = []
    try:
        catalog = _read_json(path)
    except (OSError, ValueError) as exc:
        return {}, [f"artifact catalog: {exc}"]
    raw_bundles = catalog.get("bundles")
    if not isinstance(raw_bundles, list):
        return {}, ["artifact catalog bundles must be a list"]
    result: dict[str, set[str]] = {}
    for raw in raw_bundles:
        if not isinstance(raw, Mapping) or not _safe_name(raw.get("artifact_id")):
            errors.append("artifact catalog contains an invalid bundle")
            continue
        artifact_id = str(raw["artifact_id"])
        files = raw.get("files")
        if not isinstance(files, list):
            errors.append(f"artifact catalog bundle has no file list: {artifact_id}")
            continue
        names: set[str] = set()
        for item in files:
            if not isinstance(item, Mapping) or not _safe_name(item.get("name")):
                errors.append(f"artifact catalog contains an invalid file: {artifact_id}")
                continue
            names.add(str(item["name"]))
        result[artifact_id] = names
    return result, errors


def _validate_side(
    recipe: Mapping[str, Any],
    side: str,
    catalog_files: Mapping[str, set[str]],
    errors: list[str],
) -> None:
    value = recipe.get(side)
    label = f"{recipe.get('case_id', '<case>')} {side}"
    if not isinstance(value, Mapping):
        errors.append(f"{label} section is absent")
        return
    packages = value.get("packages")
    if not isinstance(packages, list) or not packages:
        errors.append(f"{label} packages must be a non-empty list")
    else:
        seen: set[str] = set()
        artifact_ids = recipe.get("artifacts")
        available = set()
        if isinstance(artifact_ids, list):
            for artifact_id in artifact_ids:
                available.update(catalog_files.get(str(artifact_id), set()))
        for package in packages:
            if not isinstance(package, Mapping):
                errors.append(f"{label} contains an invalid package")
                continue
            name = package.get("name")
            version = package.get("version")
            wheel = package.get("wheel")
            if not _safe_name(name) or not isinstance(version, str) or not version:
                errors.append(f"{label} contains an invalid package identity")
            if not _safe_name(wheel) or not str(wheel).endswith(".whl"):
                errors.append(f"{label} contains an invalid wheel name")
            elif str(wheel) not in available:
                errors.append(f"{label} wheel is not in the declared artifact catalog: {wheel}")
            if isinstance(wheel, str) and wheel in seen:
                errors.append(f"{label} declares a wheel more than once: {wheel}")
            if isinstance(wheel, str):
                seen.add(wheel)
    environment = value.get("environment")
    if not isinstance(environment, Mapping):
        errors.append(f"{label} environment must be an object")
    else:
        for key, item in environment.items():
            if not _ENV_RE.fullmatch(str(key)) or not isinstance(item, str) or "\n" in item or "\r" in item:
                errors.append(f"{label} contains an invalid environment entry")
    _valid_command(value.get("command"), f"{label} command", errors)
    if type(value.get("expected_exit")) is not int or not 0 <= int(value["expected_exit"]) <= 255:
        errors.append(f"{label} expected_exit must be an integer from 0 through 255")


def load_runtime_recipes(root: Path) -> dict[str, Any]:
    """Load the public runtime recipe document without resolving external paths."""

    return _read_json(root / RUNTIME_RECIPES_RELATIVE)


def validate_runtime_recipes(root: Path) -> dict[str, Any]:
    """Validate recipe completeness, path safety, and catalog references."""

    errors: list[str] = []
    path = root / RUNTIME_RECIPES_RELATIVE
    try:
        document = load_runtime_recipes(root)
    except (OSError, ValueError) as exc:
        return {
            "valid": False,
            "suite_id": SUITE_ID,
            "recipe_count": 0,
            "errors": [str(exc)],
        }
    if document.get("schema_version") != "1.0":
        errors.append("runtime recipe schema_version must be 1.0")
    if document.get("suite_id") != SUITE_ID:
        errors.append("runtime recipe suite_id does not match decisive-v1")
    network_policy = document.get("network_policy")
    if not isinstance(network_policy, Mapping) or network_policy.get("execution") != "denied":
        errors.append("runtime recipe execution network policy must be denied")
    build = document.get("build")
    if not isinstance(build, Mapping):
        errors.append("runtime recipe build section is absent")
    else:
        if build.get("platform") != "linux/amd64":
            errors.append("runtime recipe build platform must be linux/amd64")
        if build.get("pythonpath") != "/opt/radar/site":
            errors.append("runtime recipe PYTHONPATH must be /opt/radar/site")
        expected_install = [
            "python",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-cache-dir",
            "--no-deps",
            "--target",
            "/opt/radar/site",
        ]
        if build.get("install_command") != expected_install:
            errors.append("runtime recipe install command is not the offline fixed command")
        if build.get("read_only_execution_root") is not True:
            errors.append("runtime recipe execution root must be read-only")
    catalog_files, catalog_errors = _catalog_files(root)
    errors.extend(catalog_errors)
    recipes = document.get("recipes")
    if not isinstance(recipes, list) or len(recipes) != len(HISTORICAL_CASE_IDS):
        errors.append("runtime recipe document must contain exactly five recipes")
        recipes = []
    seen_cases: set[str] = set()
    seen_recipe_ids: set[str] = set()
    for raw in recipes:
        if not isinstance(raw, Mapping):
            errors.append("runtime recipe entry must be an object")
            continue
        case_id = raw.get("case_id")
        recipe_id = raw.get("recipe_id")
        label = str(case_id or "<case>")
        if case_id not in HISTORICAL_CASE_IDS:
            errors.append(f"{label}: unknown historical case ID")
        elif case_id in seen_cases:
            errors.append(f"{label}: duplicate historical case ID")
        else:
            seen_cases.add(str(case_id))
        if not _safe_name(recipe_id) or recipe_id in seen_recipe_ids:
            errors.append(f"{label}: recipe_id is invalid or duplicated")
        elif isinstance(recipe_id, str):
            seen_recipe_ids.add(recipe_id)
        platform = raw.get("platform")
        if not isinstance(platform, Mapping):
            errors.append(f"{label}: platform section is absent")
        else:
            if platform.get("os") != "linux" or platform.get("architecture") != "x86_64":
                errors.append(f"{label}: platform must be Linux x86_64")
            if not isinstance(platform.get("python"), str) or not re.fullmatch(r"3\.\d+\.\d+", str(platform.get("python"))):
                errors.append(f"{label}: exact Python version is required")
            image = platform.get("container_image")
            if not isinstance(image, str) or not _IMAGE_RE.fullmatch(image):
                errors.append(f"{label}: container image must be digest-pinned")
        artifacts = raw.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) != 1 or any(not _safe_name(item) for item in artifacts):
            errors.append(f"{label}: exactly one safe artifact bundle ID is required")
        elif any(str(item) not in catalog_files for item in artifacts):
            errors.append(f"{label}: recipe references an unknown artifact bundle")
        reproducer, path_error = _safe_repo_path(root, raw.get("reproducer"))
        if path_error or reproducer is None or not reproducer.is_file():
            errors.append(f"{label}: reproducer is absent or unsafe")
        filesystem = raw.get("filesystem")
        if not isinstance(filesystem, Mapping):
            errors.append(f"{label}: filesystem section is absent")
        else:
            if not _safe_container_path(filesystem.get("input_mount"), "/input"):
                errors.append(f"{label}: input mount must be /input")
            if not _safe_container_path(filesystem.get("reproducer_mount"), "/reproducer"):
                errors.append(f"{label}: reproducer mount must be /reproducer")
            input_files = filesystem.get("input_files")
            if not isinstance(input_files, list) or any(not _safe_name(item) for item in input_files):
                errors.append(f"{label}: input_files must contain safe names")
        preparation = raw.get("preparation")
        if not isinstance(preparation, list):
            errors.append(f"{label}: preparation must be a list")
        else:
            for item in preparation:
                if not isinstance(item, Mapping) or item.get("side") != "control":
                    errors.append(f"{label}: preparation may only run on control")
                    continue
                _valid_command(item.get("command"), f"{label} preparation", errors)
                writes = item.get("writes")
                input_files = filesystem.get("input_files", []) if isinstance(filesystem, Mapping) else []
                if not isinstance(writes, list) or any(item not in input_files for item in writes):
                    errors.append(f"{label}: preparation writes undeclared input files")
        _validate_side(raw, "control", catalog_files, errors)
        _validate_side(raw, "candidate", catalog_files, errors)
        expected = raw.get("expected")
        if not isinstance(expected, Mapping):
            errors.append(f"{label}: expected behavior section is absent")
        else:
            control = raw.get("control")
            candidate = raw.get("candidate")
            control_expected = control.get("expected_exit") if isinstance(control, Mapping) else None
            candidate_expected = candidate.get("expected_exit") if isinstance(candidate, Mapping) else None
            for side in ("control_exit", "candidate_exit"):
                expected_side = control_expected if side == "control_exit" else candidate_expected
                if expected.get(side) != expected_side:
                    errors.append(f"{label}: expected behavior disagrees with {side}")
            if "root_cause_repository" in expected and (
                not isinstance(expected["root_cause_repository"], str)
                or not _REPOSITORY_RE.fullmatch(expected["root_cause_repository"])
            ):
                errors.append(f"{label}: root_cause_repository is invalid")
    if seen_cases != HISTORICAL_CASE_IDS:
        errors.append("runtime recipes do not cover exactly the five historical cases")
    return {
        "valid": not errors,
        "suite_id": document.get("suite_id"),
        "recipe_count": len(recipes),
        "recipe_digest": _digest(path) if path.is_file() else None,
        "errors": errors,
    }


def _bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    return value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")


def _docker_result(completed: subprocess.CompletedProcess[bytes]) -> dict[str, Any]:
    output = _bytes(completed.stdout) + _bytes(completed.stderr)
    return {
        "returncode": completed.returncode,
        "output_bytes": len(output),
        "output_digest": "sha256:" + hashlib.sha256(output).hexdigest(),
        "output_limit_exceeded": len(output) > MAX_COMMAND_OUTPUT_BYTES,
        "_output": output[:4096],
    }


def _run_docker(
    argv: list[str],
    *,
    timeout: int,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(  # nosec B603 - validated fixed Docker argv and shell=False
            argv,
            capture_output=True,
            check=False,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "returncode": None,
            "output_bytes": 0,
            "output_digest": None,
            "output_limit_exceeded": False,
            "timed_out": True,
        }
    except OSError as exc:
        return {
            "returncode": None,
            "output_bytes": 0,
            "output_digest": None,
            "output_limit_exceeded": False,
            "error_type": type(exc).__name__,
        }
    result = _docker_result(cast(subprocess.CompletedProcess[bytes], completed))
    if result["output_limit_exceeded"]:
        result["error_type"] = "OUTPUT_LIMIT_EXCEEDED"
    return result


def _ensure_base_image(docker: str, image: str) -> tuple[bool, bool, str | None]:
    inspected = _run_docker([docker, "image", "inspect", image], timeout=30)
    if inspected.get("returncode") == 0:
        return True, False, None
    pulled = _run_docker([docker, "pull", image], timeout=DOCKER_PULL_TIMEOUT_SECONDS)
    if pulled.get("returncode") != 0:
        return False, True, "BASE_IMAGE_UNAVAILABLE"
    checked = _run_docker([docker, "image", "inspect", image], timeout=30)
    if checked.get("returncode") != 0:
        return False, True, "BASE_IMAGE_UNAVAILABLE"
    return True, True, None


def _exact_python(docker: str, image: str, expected: str) -> tuple[bool, str | None]:
    result = _run_docker(
        [docker, "run", "--rm", "--network=none", "--platform", "linux/amd64", "--entrypoint", "python", image, "--version"],
        timeout=60,
    )
    if result.get("returncode") != 0:
        return False, "BASE_IMAGE_RUNTIME_UNAVAILABLE"
    version = _bytes(cast(bytes | str | None, result.get("_output"))).decode(
        "utf-8", errors="replace"
    ).strip().splitlines()[0:1]
    observed = version[0].removeprefix("Python ") if version else ""
    if observed != expected:
        return False, "BASE_IMAGE_RUNTIME_MISMATCH"
    return True, None


def _dockerfile(recipe: Mapping[str, Any], side: str, wheel_names: list[str]) -> str:
    platform = cast(Mapping[str, Any], recipe["platform"])
    build = cast(Mapping[str, Any], cast(Mapping[str, Any], recipe.get("_document_build", {})))
    install = cast(list[str], build["install_command"])
    install_argv = install + [f"/wheelhouse/{name}" for name in wheel_names]
    image = str(platform["container_image"])
    script_name = Path(str(recipe["reproducer"])).name
    lines = [
        f"FROM {image}",
        "ENV PYTHONPATH=/opt/radar/site",
        "COPY wheels /wheelhouse/",
        "RUN " + json.dumps(install_argv, separators=(",", ":")),
        f"COPY reproducer.py /reproducer/{script_name}",
    ]
    return "\n".join(lines) + "\n"


def _mount(source: Path, target: str, read_only: bool) -> str:
    mode = ",readonly" if read_only else ""
    return f"type=bind,source={source},target={target}{mode}"


def _run_case_side(
    docker: str,
    image: str,
    side: str,
    command: list[str],
    environment: Mapping[str, str],
    input_dir: Path,
    *,
    preparation: bool = False,
) -> dict[str, Any]:
    argv = [
        docker,
        "run",
        "--rm",
        "--network=none",
        "--platform",
        "linux/amd64",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pids-limit=256",
        "--cpus=2",
        "--memory=512m",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,nodev,mode=1777",
        "--user=0:0" if preparation else "--user=65532:65532",
        "--mount",
        _mount(input_dir, "/input", not preparation),
    ]
    for key, value in sorted(environment.items()):
        argv.extend(["--env", f"{key}={value}"])
    argv.extend([image, *command])
    result = _run_docker(argv, timeout=DOCKER_RUN_TIMEOUT_SECONDS)
    result.pop("_output", None)
    result["side"] = side
    result["network"] = "none"
    result["preparation"] = preparation
    return result


def _build_side(
    docker: str,
    recipe: Mapping[str, Any],
    side: str,
    artifact_root: Path,
    context: Path,
) -> tuple[str | None, str | None]:
    side_data = cast(Mapping[str, Any], recipe[side])
    artifact_id = str(cast(list[Any], recipe["artifacts"])[0])
    bundle_root = (artifact_root / artifact_id).resolve()
    wheels_dir = context / "wheels"
    wheels_dir.mkdir()
    wheel_names = [str(cast(Mapping[str, Any], item)["wheel"]) for item in cast(list[Any], side_data["packages"])]
    for name in wheel_names:
        source = bundle_root / name
        if not source.is_file() or source.is_symlink():
            return None, "ARTIFACT_UNAVAILABLE"
        shutil.copyfile(source, wheels_dir / name)
    shutil.copyfile(Path(str(recipe["_reproducer_path"])), context / "reproducer.py")
    (context / "Dockerfile").write_text(_dockerfile(recipe, side, wheel_names), encoding="utf-8", newline="\n")
    image_tag = f"radar-bench-runtime-{uuid.uuid4().hex[:16]}"
    result = _run_docker(
        [
            docker,
            "build",
            "--pull=false",
            "--network=none",
            "--platform",
            "linux/amd64",
            "--tag",
            image_tag,
            str(context),
        ],
        timeout=DOCKER_BUILD_TIMEOUT_SECONDS,
    )
    if result.get("returncode") != 0:
        return image_tag, "IMAGE_BUILD_FAILED"
    return image_tag, None


def _remove_image(docker: str, image: str) -> None:
    _run_docker([docker, "image", "rm", "--force", image], timeout=60)


def reconstruct_historical_cases(root: Path, artifact_root: Path | None = None) -> dict[str, Any]:
    """Reconstruct all five recipes and replay their sealed exit behavior."""

    validation = validate_runtime_recipes(root)
    base_result: dict[str, Any] = {
        "suite_id": SUITE_ID,
        "status": "BLOCKED",
        "execution_network": "none",
        "network_used": False,
        "recipe_digest": validation.get("recipe_digest"),
        "cases": [],
        "blockers": [],
        "errors": list(validation.get("errors", [])),
    }
    if not validation.get("valid"):
        base_result["blockers"] = ["HISTORICAL_BUILD_UNREPRODUCIBLE"]
        return base_result
    verification = verify_artifacts(root, SUITE_ID, artifact_root)
    base_result["artifact_verification"] = verification
    if verification.get("status") != "READY":
        base_result["blockers"] = ["ARTIFACT_UNAVAILABLE"]
        base_result["errors"].extend(verification.get("errors", []))
        return base_result
    docker = shutil.which("docker")
    if not docker:
        base_result["blockers"] = ["RUNTIME_UNAVAILABLE"]
        return base_result
    runtime = inspect_docker_runtime(executable=docker)
    if not runtime.supported:
        base_result["blockers"] = [runtime.reason or "PLATFORM_UNAVAILABLE"]
        return base_result
    document = load_runtime_recipes(root)
    build = cast(Mapping[str, Any], document["build"])
    recipes = cast(list[dict[str, Any]], document["recipes"])
    artifact_path = (artifact_root or root / "artifacts" / "external" / SUITE_ID).resolve()
    all_ready = True
    blockers: list[str] = []
    for raw_recipe in recipes:
        recipe = dict(raw_recipe)
        case_id = str(recipe["case_id"])
        recipe["_document_build"] = build
        reproducer, path_error = _safe_repo_path(root, recipe.get("reproducer"))
        if reproducer is None or path_error:
            all_ready = False
            blockers.append("HISTORICAL_BUILD_UNREPRODUCIBLE")
            base_result["cases"].append({"case_id": case_id, "status": "BLOCKED", "blockers": ["HISTORICAL_BUILD_UNREPRODUCIBLE"]})
            continue
        recipe["_reproducer_path"] = str(reproducer)
        image = str(cast(Mapping[str, Any], recipe["platform"])["container_image"])
        present, pulled, image_error = _ensure_base_image(docker, image)
        base_result["network_used"] = bool(base_result["network_used"] or pulled)
        if not present or image_error:
            all_ready = False
            reason = image_error or "BASE_IMAGE_UNAVAILABLE"
            blockers.append(reason)
            base_result["cases"].append({"case_id": case_id, "status": "BLOCKED", "blockers": [reason]})
            continue
        python_ok, python_error = _exact_python(docker, image, str(cast(Mapping[str, Any], recipe["platform"])["python"]))
        if not python_ok:
            all_ready = False
            reason = python_error or "BASE_IMAGE_RUNTIME_UNAVAILABLE"
            blockers.append(reason)
            base_result["cases"].append({"case_id": case_id, "status": "BLOCKED", "blockers": [reason]})
            continue
        case_result: dict[str, Any] = {"case_id": case_id, "recipe_id": recipe["recipe_id"], "status": "BLOCKED", "sides": {}}
        with tempfile.TemporaryDirectory(prefix="radar-runtime-") as temporary:
            work = Path(temporary)
            input_dir = work / "input"
            input_dir.mkdir()
            image_tags: list[str] = []
            side_errors: list[str] = []
            try:
                for side in ("control", "candidate"):
                    context = work / side
                    context.mkdir()
                    image_tag, build_error = _build_side(docker, recipe, side, artifact_path, context)
                    if image_tag:
                        image_tags.append(image_tag)
                    if build_error:
                        side_errors.append(build_error)
                        case_result["sides"][side] = {"status": "BLOCKED", "blockers": [build_error]}
                if not side_errors:
                    preparation = cast(list[Mapping[str, Any]], recipe["preparation"])
                    if preparation:
                        prep = preparation[0]
                        prep_result = _run_case_side(
                            docker,
                            image_tags[0],
                            "control",
                            cast(list[str], prep["command"]),
                            cast(Mapping[str, str], recipe["control"]["environment"]),
                            input_dir,
                            preparation=True,
                        )
                        case_result["preparation"] = prep_result
                        if prep_result.get("returncode") != 0:
                            side_errors.append("PREPARATION_FAILED")
                    for index, side in enumerate(("control", "candidate")):
                        if side_errors:
                            break
                        side_data = cast(Mapping[str, Any], recipe[side])
                        result = _run_case_side(
                            docker,
                            image_tags[index],
                            side,
                            cast(list[str], side_data["command"]),
                            cast(Mapping[str, str], side_data["environment"]),
                            input_dir,
                        )
                        expected = int(side_data["expected_exit"])
                        result["expected_exit"] = expected
                        result["status"] = "READY" if result.get("returncode") == expected else "BLOCKED"
                        case_result["sides"][side] = result
                        if result["status"] != "READY":
                            side_errors.append("HISTORICAL_BUILD_UNREPRODUCIBLE" if result.get("returncode") is not None else "EXECUTION_TIMEOUT")
            finally:
                for tag in image_tags:
                    _remove_image(docker, tag)
        if side_errors:
            all_ready = False
            blockers.extend(side_errors)
            case_result["blockers"] = list(dict.fromkeys(side_errors))
        else:
            case_result["status"] = "READY"
        base_result["cases"].append(case_result)
    base_result["blockers"] = list(dict.fromkeys(blockers))
    base_result["status"] = "READY" if all_ready else "BLOCKED"
    return base_result


__all__ = [
    "HISTORICAL_CASE_IDS",
    "RUNTIME_RECIPES_RELATIVE",
    "load_runtime_recipes",
    "reconstruct_historical_cases",
    "validate_runtime_recipes",
]
