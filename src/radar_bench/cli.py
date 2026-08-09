"""Primary radar-bench command line interface with stable exit codes."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from radar_bench import __version__
from radar_bench.baseline.engine import predict
from radar_bench.baseline.engine import predict_v02
from radar_bench.baseline.v03 import predict_v03
from radar_bench.artifacts import fetch_artifacts, verify_artifacts
from radar_bench.config import project_root
from radar_bench.corpus.admission import admission_summary, validate_admission
from radar_bench.corpus.v03 import validate_gold_admission, v03_corpus_summary
from radar_bench.corpus.v04 import validate_v04_record, v04_summary
from radar_bench.investigation.v01 import validate_episode
from radar_bench.integrity.v06 import REQUIRED_V06_ARTIFACTS
from radar_bench.execution.v07 import REQUIRED_V07_ARTIFACTS, validate_manifest
from radar_bench.evaluation.ablation import compare_lanes
from radar_bench.errors import ExternalBlocked, RadarError, ValidationError
from radar_bench.evaluation.gates import evaluate_gates
from radar_bench.evaluation.reports import markdown_report, write_json
from radar_bench.evaluation.scoring import load_predictions, score
from radar_bench.evaluation.v03 import score_v03
from radar_bench.github.collector import collect_manifest, collect_url
from radar_bench.models.case import validate_case
from radar_bench.models.experiment import (
    render_experiment_plan,
    validate_experiment_plan,
)
from radar_bench.models.prediction import validate_prediction
from radar_bench.normalize.base import normalize_text
from radar_bench.normalize.github_annotations import normalize_annotations
from radar_bench.normalize.junit import normalize_junit
from radar_bench.normalize.pytest_text import normalize_pytest
from radar_bench.snapshots.builder import build_snapshot
from radar_bench.snapshots.integrity import check_snapshot
from radar_bench.release import (
    SUITE_ID,
    evaluate_decisive_suite,
    inspect_case,
    load_suite,
    validate_decisive_suite,
)

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_LEAKAGE = 3
EXIT_EXTERNAL = 4
EXIT_GATE = 5


def _json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _root() -> Path:
    return project_root()


def _case_paths(case_id: str) -> tuple[Path, Path]:
    root = _root()
    case_path = root / "corpus" / "cases" / f"{case_id}.json"
    snapshot_path = root / "corpus" / "snapshots" / case_id
    return case_path, snapshot_path


def command_doctor(args: argparse.Namespace) -> int:
    result: dict[str, Any] = {
        "version": __version__,
        "root": str(_root()),
        "python": sys.version.split()[0],
        "schemas": sorted((_root() / "schema").glob("*.json")),
        "network": "optional",
    }
    result["schemas"] = [path.name for path in result["schemas"]]
    _json(result)
    return EXIT_OK


def command_validate_case(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    try:
        case = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_case(case, root=_root(), strict=args.strict)
    except (OSError, ValueError, ValidationError) as exc:
        errors = [str(exc)]
    result = {"path": str(path), "valid": not errors, "errors": errors}
    _json(result) if args.json else print(
        "VALID" if not errors else "INVALID\n" + "\n".join(errors)
    )
    return EXIT_OK if not errors else EXIT_INVALID


def command_validate_corpus(args: argparse.Namespace) -> int:
    root = _root()
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted((root / "corpus" / "cases").glob("*.json")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
            case_errors = validate_case(case, root=root)
        except (OSError, ValueError, ValidationError) as exc:
            case_errors = [str(exc)]
        results.append(
            {"case_id": path.stem, "valid": not case_errors, "errors": case_errors}
        )
        errors.extend(f"{path.name}: {item}" for item in case_errors)
    example = root / "examples" / "regression-case-openblas.json"
    if example.exists():
        example_errors = validate_case(
            json.loads(example.read_text(encoding="utf-8")), root=root
        )
        results.append(
            {
                "case_id": example.stem,
                "valid": not example_errors,
                "errors": example_errors,
            }
        )
        errors.extend(f"{example.name}: {item}" for item in example_errors)
    output = {
        "cases": results,
        "valid": not errors,
        "errors": errors,
        "count": len(results),
    }
    _json(output)
    return EXIT_OK if not errors else EXIT_INVALID


def command_validate_admission(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_admission(record, root=_root())
    except (OSError, ValueError, ValidationError) as exc:
        errors = [str(exc)]
    result = {"path": str(path), "valid": not errors, "errors": errors}
    _json(result) if args.json else print(
        "VALID" if not errors else "INVALID\n" + "\n".join(errors)
    )
    return EXIT_OK if not errors else EXIT_INVALID


def command_validate_v02_corpus(args: argparse.Namespace) -> int:
    directory = _root() / "corpus" / "v0.2" / "admissions"
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            record_errors = validate_admission(record, root=_root())
            records.append(record)
        except (OSError, ValueError, ValidationError) as exc:
            record = {}
            record_errors = [str(exc)]
        errors.extend(f"{path.name}: {error}" for error in record_errors)
    summary = admission_summary(records)
    plan_path = _root() / "corpus" / "v0.2" / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if summary["records"] != plan.get("total_target_cases"):
            errors.append("v0.2 plan count does not match admission records")
        if summary["admitted_gold"] != plan.get("gold_cases_admitted"):
            errors.append("v0.2 plan gold count does not match admission records")
    output = {"valid": not errors, "summary": summary, "errors": errors}
    _json(output)
    return EXIT_OK if not errors else EXIT_INVALID


def command_validate_v03_corpus(args: argparse.Namespace) -> int:
    root = _root() / "corpus" / "v0.3"
    paths = sorted(root.glob("**/admissions/*.json")) + sorted(
        root.glob("**/counterfactuals/*.json")
    )
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            record = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
            record_errors = validate_gold_admission(record, root=_root())
            errors.extend(f"{path.name}: {error}" for error in record_errors)
            records.append(record)
        except (OSError, ValueError, ValidationError) as exc:
            errors.append(f"{path.name}: {exc}")
    summary = v03_corpus_summary(records)
    plan_path = root / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if summary["attribution_gold"] != plan["attribution_gold_target"]:
            errors.append("v0.3 attribution plan count does not match records")
        if summary["safety_abstention"] != plan["safety_abstention_target"]:
            errors.append("v0.3 safety plan count does not match records")
        if summary["counterfactual_variants"] < plan["counterfactual_minimum"]:
            errors.append("v0.3 counterfactual count is below the required minimum")
    result = {"valid": not errors, "errors": errors, "summary": summary}
    _json(result) if getattr(args, "json", False) else print(json.dumps(result, indent=2, sort_keys=True))
    return EXIT_OK if not errors else EXIT_INVALID


def command_validate_v04_corpus(args: argparse.Namespace) -> int:
    root = _root() / "corpus" / "v0.4" / "pilot"
    paths = sorted((root / "records").glob("*.json"))
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            record = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
            record_errors = validate_v04_record(record, root=_root())
            errors.extend(f"{path.name}: {error}" for error in record_errors)
            records.append(record)
        except (OSError, ValueError, ValidationError) as exc:
            errors.append(f"{path.name}: {exc}")
    if not paths:
        errors.append("v0.4 pilot has no admission records")
    result = {"valid": not errors, "errors": errors, "summary": v04_summary(records)}
    _json(result) if getattr(args, "json", False) else print(
        json.dumps(result, indent=2, sort_keys=True)
    )
    return EXIT_OK if not errors else EXIT_INVALID


def command_validate_v05_episodes(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else _root() / "artifacts" / "release-evidence" / "investigation-episodes.json"
    errors: list[str] = []
    try:
        payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        episodes = payload.get("episodes", [])
        if not isinstance(episodes, list) or not episodes:
            errors.append("v0.5 episode artifact has no episodes")
            episodes = []
        for episode in episodes:
            errors.extend(f"{episode.get('episode_id', 'missing')}: {error}" for error in validate_episode(episode, root=_root()))
    except (OSError, ValueError, ValidationError) as exc:
        errors.append(str(exc))
        episodes = []
    result = {"path": str(path.resolve()), "valid": not errors, "episodes": len(episodes), "errors": errors}
    _json(result)
    return EXIT_OK if not errors else EXIT_INVALID


def command_validate_v06_integrity(args: argparse.Namespace) -> int:
    root = _root()
    result_path = Path(args.path) if args.path else root / "artifacts" / "v06-result.json"
    errors: list[str] = []
    try:
        result = cast(dict[str, Any], json.loads(result_path.read_text(encoding="utf-8")))
        if result.get("protocol_version") != "0.6":
            errors.append("v0.6 result has the wrong protocol version")
        for name in REQUIRED_V06_ARTIFACTS:
            if not (root / "artifacts" / "release-evidence" / name).exists():
                errors.append(f"missing v0.6 evidence artifact: {name}")
        gates = result.get("gates", {})
        if not isinstance(gates, dict) or "checks" not in gates:
            errors.append("v0.6 result has no gate report")
    except (OSError, ValueError, ValidationError) as exc:
        errors.append(str(exc))
        result = {}
    output = {"path": str(result_path.resolve()), "valid": not errors, "errors": errors, "decision": result.get("decision")}
    _json(output)
    return EXIT_OK if not errors else EXIT_INVALID


def command_validate_v07_executable(args: argparse.Namespace) -> int:
    root = _root()
    result_path = Path(args.path) if args.path else root / "artifacts" / "v07-result.json"
    errors: list[str] = []
    try:
        result = cast(dict[str, Any], json.loads(result_path.read_text(encoding="utf-8")))
        if result.get("protocol_version") != "0.7":
            errors.append("v0.7 result has the wrong protocol version")
        for name in REQUIRED_V07_ARTIFACTS:
            if not (root / "artifacts" / "release-evidence" / name).exists():
                errors.append(f"missing v0.7 evidence artifact: {name}")
        gates = result.get("gates", {})
        if not isinstance(gates, dict) or "decision" not in gates:
            errors.append("v0.7 result has no gate decision")
        manifest_path = root / "corpus" / "v0.7" / "executable-subset.json"
        manifest = cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))
        errors.extend(validate_manifest(manifest, root=root))
    except (OSError, ValueError, ValidationError) as exc:
        errors.append(str(exc))
        result = {}
    output = {"path": str(result_path.resolve()), "valid": not errors, "errors": errors, "decision": result.get("decision")}
    _json(output)
    return EXIT_OK if not errors else EXIT_INVALID


def command_collect(args: argparse.Namespace) -> int:
    try:
        if args.manifest:
            result = collect_manifest(
                Path(args.manifest), Path(args.output), args.cutoff
            )
        else:
            result = collect_url(args.issue, Path(args.output), args.cutoff)
        _json(result)
        return EXIT_OK if not result.get("blocked") else EXIT_EXTERNAL
    except ExternalBlocked as exc:
        _json({"status": "blocked", "error": str(exc)})
        return EXIT_EXTERNAL
    except (OSError, ValueError, RadarError) as exc:
        _json({"status": "invalid", "error": str(exc)})
        return EXIT_INVALID


def command_build_snapshot(args: argparse.Namespace) -> int:
    case_path, snapshot_path = _case_paths(args.case_id)
    try:
        case = json.loads(case_path.read_text(encoding="utf-8"))
        _json(build_snapshot(case, snapshot_path, root=_root()))
        return EXIT_OK
    except (OSError, ValueError, RadarError) as exc:
        _json({"status": "invalid", "error": str(exc)})
        return EXIT_LEAKAGE if "leak" in str(exc).lower() else EXIT_INVALID


def command_check_leakage(args: argparse.Namespace) -> int:
    case_path, snapshot_path = _case_paths(args.case_id)
    errors = check_snapshot(case_path, snapshot_path)
    result = {"case_id": args.case_id, "leakage": errors, "valid": not errors}
    _json(result) if args.json else print(
        "NO_LEAKAGE" if not errors else "LEAKAGE\n" + "\n".join(errors)
    )
    return EXIT_OK if not errors else EXIT_LEAKAGE


def command_normalize(args: argparse.Namespace) -> int:
    payload = (
        Path(args.input).read_text(encoding="utf-8")
        if Path(args.input).is_file()
        else args.input
    )
    if args.format == "pytest":
        result = normalize_pytest(payload)
    elif args.format == "junit":
        result = normalize_junit(payload)
    elif args.format == "github":
        result = normalize_annotations(json.loads(payload))
    else:
        result = normalize_text(payload, source_format="text")
    _json(result.to_dict())
    return EXIT_OK


def _load_packet(value: str) -> dict[str, Any]:
    path = Path(value)
    if path.is_dir():
        return cast(
            dict[str, Any],
            json.loads((path / "input" / "snapshot.json").read_text(encoding="utf-8")),
        )
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def command_baseline(args: argparse.Namespace) -> int:
    packet = _load_packet(args.value)
    result = predict_v03(packet) if args.v03 else predict_v02(packet) if args.v02 else predict(packet)
    errors = validate_prediction(result)
    if errors:
        _json({"valid": False, "errors": errors, "prediction": result})
        return EXIT_INVALID
    _json(result)
    return EXIT_OK


def command_export(args: argparse.Namespace) -> int:
    _, snapshot_path = _case_paths(args.case_id)
    packet = json.loads(
        (snapshot_path / "input" / "snapshot.json").read_text(encoding="utf-8")
    )
    write_json(Path(args.output), packet)
    _json(
        {
            "case_id": args.case_id,
            "output": str(Path(args.output).resolve()),
            "gold_loaded": False,
        }
    )
    return EXIT_OK


def command_import(args: argparse.Namespace) -> int:
    predictions = load_predictions(Path(args.path))
    output = {
        "count": len(predictions),
        "valid": sum(item.get("_valid", False) for item in predictions),
        "invalid": sum(not item.get("_valid", False) for item in predictions),
    }
    _json(output)
    return EXIT_OK if output["invalid"] == 0 else EXIT_INVALID


def _labels() -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for path in sorted((_root() / "corpus" / "cases").glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        labels[case["case_id"]] = case["attribution"]
    return labels


def _evidence_by_case() -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for path in sorted((_root() / "corpus" / "cases").glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result[case["case_id"]] = {
            item["evidence_id"]: item
            for item in case.get("evidence", [])
            if item.get("available_before_cutoff") is True
        }
    return result


def command_evaluate(args: argparse.Namespace) -> int:
    if args.suite:
        command = ["radar-bench", "evaluate", "--suite", args.suite]
        artifact_root = Path(args.artifact_root).resolve() if args.artifact_root else None
        if artifact_root is not None:
            command.extend(["--artifact-root", "<external-artifact-root>"])
        result = evaluate_decisive_suite(
            _root(),
            command=command,
            artifact_root=artifact_root,
        )
        if args.output:
            write_json(Path(args.output), result)
        _json(result)
        if result["status"] == "INVALID":
            return EXIT_INVALID
        if result["status"] == "BLOCKED":
            return EXIT_EXTERNAL
        return EXIT_GATE if result.get("certification") == "UNSAFE" else EXIT_OK
    if not args.path:
        raise ValidationError("evaluate requires a predictions path or --suite decisive-v1")
    report = score(load_predictions(Path(args.path), _evidence_by_case()), _labels())
    if args.output:
        write_json(Path(args.output), report)
    print(markdown_report(report))
    return EXIT_OK


def command_artifacts_fetch(args: argparse.Namespace) -> int:
    output_root = Path(args.output_root).resolve() if args.output_root else None
    result = fetch_artifacts(_root(), args.suite, output_root)
    _json(result)
    if result["status"] == "INVALID":
        return EXIT_INVALID
    return EXIT_OK if result["status"] == "READY" else EXIT_EXTERNAL


def command_artifacts_verify(args: argparse.Namespace) -> int:
    artifact_root = Path(args.artifact_root).resolve() if args.artifact_root else None
    result = verify_artifacts(_root(), args.suite, artifact_root)
    _json(result)
    if result["status"] == "INVALID":
        return EXIT_INVALID
    return EXIT_OK if result["status"] == "READY" else EXIT_EXTERNAL


def command_validate_suite(args: argparse.Namespace) -> int:
    if args.suite != SUITE_ID:
        _json({"valid": False, "errors": [f"unknown suite: {args.suite}"]})
        return EXIT_INVALID
    result = validate_decisive_suite(_root())
    _json(result)
    return EXIT_OK if result["valid"] else EXIT_INVALID


def command_list_suites(args: argparse.Namespace) -> int:
    suites = []
    path = _root() / "corpus" / "v0.7" / "decisive-v1" / "suite.json"
    if path.is_file():
        suite = load_suite(_root())
        suites.append(
            {
                "suite_id": suite["suite_id"],
                "release_version": suite["release_version"],
                "historical_cases": len(suite["historical_cases"]),
                "safety_cases": suite["safety_cases"]["count"],
                "platform": suite["platform"],
            }
        )
    _json({"suites": suites})
    return EXIT_OK


def command_inspect_case(args: argparse.Namespace) -> int:
    try:
        _json(inspect_case(_root(), args.case_id))
        return EXIT_OK
    except (OSError, ValueError, ValidationError) as exc:
        _json({"valid": False, "errors": [str(exc)]})
        return EXIT_INVALID


def command_verify_results(args: argparse.Namespace) -> int:
    path = Path(args.path).resolve()
    artifact_root = Path(args.artifact_root).resolve() if args.artifact_root else None
    errors: list[str] = []
    try:
        result = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        errors.extend(validate_decisive_suite(_root(), artifact_root=artifact_root).get("errors", []))
        if result.get("schema_version") != "1.0":
            errors.append("result has the wrong schema version")
        if result.get("suite_id") != SUITE_ID:
            errors.append("result is not for decisive-v1")
        if result.get("reference", {}).get("used_as_runtime_evidence") is True:
            errors.append("canonical reference was marked as runtime evidence")
    except (OSError, ValueError) as exc:
        errors.append(str(exc))
    _json({"path": str(path), "valid": not errors, "errors": errors})
    return EXIT_OK if not errors else EXIT_INVALID


def command_evaluate_v03(args: argparse.Namespace) -> int:
    predictions = load_predictions(Path(args.path))
    labels = cast(dict[str, dict[str, Any]], json.loads(Path(args.labels).read_text(encoding="utf-8")))
    report = score_v03(predictions, labels, corpus_kind=args.corpus_kind)
    if args.output:
        write_json(Path(args.output), report)
    _json(report)
    return EXIT_OK


def command_ablation(args: argparse.Namespace) -> int:
    labels = _labels()
    lanes: dict[str, dict[str, Any]] = {}
    prediction_lanes: dict[str, list[dict[str, Any]]] = {}
    for name, value in (
        ("deterministic", args.deterministic),
        ("local_model", args.local),
        ("codex", args.codex),
    ):
        if value:
            predictions = load_predictions(Path(value))
            prediction_lanes[name] = predictions
            lanes[name] = score(predictions, labels)
    if any(
        value.get("schema_version") == "0.2"
        for lane in prediction_lanes.values()
        for value in lane
    ):
        accounting: dict[str, list[dict[str, Any]]] = {}
        if args.accounting:
            payload = json.loads(Path(args.accounting).read_text(encoding="utf-8"))
            accounting = payload.get("lanes", payload)
        _json(compare_lanes(prediction_lanes, labels, accounting))
    else:
        _json(
            {
                "lanes": lanes,
                "qualification": "requires a measured gain and <=0.005 added false high-confidence blame; prose quality does not qualify",
            }
        )
    return EXIT_OK


def command_gates(args: argparse.Namespace) -> int:
    report = json.loads(Path(args.path).read_text(encoding="utf-8"))
    result = evaluate_gates(report)
    _json(result) if args.json else print(json.dumps(result, indent=2, sort_keys=True))
    return (
        EXIT_OK
        if all(
            item["status"] in {"pass", "not_evaluable"}
            for item in result["gates"].values()
        )
        else EXIT_GATE
    )


def command_plan(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.path).read_text(encoding="utf-8"))
    errors = validate_experiment_plan(plan, root=_root())
    if errors:
        _json({"valid": False, "errors": errors})
        return EXIT_INVALID
    if args.action == "render":
        print(render_experiment_plan(plan))
    else:
        _json(
            {
                "valid": True,
                "plan_id": plan["plan_id"],
                "execution": "not performed; v0.1 is plan-only",
            }
        )
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar-bench",
        description="Evidence-first downstream failure attribution benchmark",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor")
    p.set_defaults(function=command_doctor)
    p = sub.add_parser("validate-case")
    p.add_argument("path")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(function=command_validate_case)
    p = sub.add_parser("validate-corpus")
    p.add_argument("--json", action="store_true")
    p.set_defaults(function=command_validate_corpus)
    p = sub.add_parser("validate-admission")
    p.add_argument("path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(function=command_validate_admission)
    p = sub.add_parser("validate-v02-corpus")
    p.set_defaults(function=command_validate_v02_corpus)
    p = sub.add_parser("validate-v03-corpus")
    p.add_argument("--json", action="store_true")
    p.set_defaults(function=command_validate_v03_corpus)
    p = sub.add_parser("validate-v04-corpus")
    p.add_argument("--json", action="store_true")
    p.set_defaults(function=command_validate_v04_corpus)
    p = sub.add_parser("validate-v05-episodes")
    p.add_argument("--path")
    p.set_defaults(function=command_validate_v05_episodes)
    p = sub.add_parser("validate-v06-integrity")
    p.add_argument("--path")
    p.set_defaults(function=command_validate_v06_integrity)
    p = sub.add_parser("validate-v07-executable")
    p.add_argument("--path")
    p.set_defaults(function=command_validate_v07_executable)
    p = sub.add_parser("validate", help="validate a public benchmark suite contract")
    p.add_argument("--suite", required=True)
    p.set_defaults(function=command_validate_suite)
    p = sub.add_parser("list-suites", help="list public benchmark suites")
    p.set_defaults(function=command_list_suites)
    p = sub.add_parser("inspect-case", help="inspect non-gold case metadata")
    p.add_argument("case_id")
    p.set_defaults(function=command_inspect_case)
    p = sub.add_parser("collect")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--issue")
    group.add_argument("--manifest")
    p.add_argument("--cutoff", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(function=command_collect)
    p = sub.add_parser("build-snapshot")
    p.add_argument("case_id")
    p.set_defaults(function=command_build_snapshot)
    p = sub.add_parser("check-leakage")
    p.add_argument("case_id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(function=command_check_leakage)
    p = sub.add_parser("normalize-failure")
    p.add_argument("input")
    p.add_argument(
        "--format",
        choices=["auto", "pytest", "junit", "github", "text"],
        default="auto",
    )
    p.set_defaults(function=command_normalize)
    p = sub.add_parser("baseline")
    p.add_argument("value")
    p.add_argument("--v02", action="store_true")
    p.add_argument("--v03", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(function=command_baseline)
    p = sub.add_parser("export-inference")
    p.add_argument("case_id")
    p.add_argument("--output", required=True)
    p.set_defaults(function=command_export)
    p = sub.add_parser("import-predictions")
    p.add_argument("path")
    p.set_defaults(function=command_import)
    p = sub.add_parser("evaluate")
    p.add_argument("path", nargs="?")
    p.add_argument("--suite")
    p.add_argument(
        "--artifact-root",
        help="external directory containing content-addressed historical wheelhouses",
    )
    p.add_argument("--split", default="seed")
    p.add_argument("--output")
    p.set_defaults(function=command_evaluate)
    p = sub.add_parser("artifacts", help="acquire and verify external benchmark artifacts")
    artifact_sub = p.add_subparsers(dest="artifacts_command", required=True)
    fetch = artifact_sub.add_parser("fetch", help="reconstruct exact external artifacts")
    fetch.add_argument("--suite", required=True)
    fetch.add_argument("--output-root")
    fetch.set_defaults(function=command_artifacts_fetch)
    verify = artifact_sub.add_parser("verify", help="verify external artifacts locally")
    verify.add_argument("--suite", required=True)
    verify.add_argument("--artifact-root")
    verify.set_defaults(function=command_artifacts_verify)
    p = sub.add_parser("verify-results", help="verify a v1 result against current suite metadata")
    p.add_argument("path")
    p.add_argument("--artifact-root", help="external directory containing historical wheelhouses")
    p.set_defaults(function=command_verify_results)
    p = sub.add_parser("evaluate-v03")
    p.add_argument("path")
    p.add_argument("--labels", required=True)
    p.add_argument("--corpus-kind", default="attribution_gold")
    p.add_argument("--output")
    p.set_defaults(function=command_evaluate_v03)
    p = sub.add_parser("ablation")
    p.add_argument("deterministic")
    p.add_argument("local")
    p.add_argument("codex")
    p.add_argument("--accounting")
    p.set_defaults(function=command_ablation)
    p = sub.add_parser("gates")
    p.add_argument("path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(function=command_gates)
    p = sub.add_parser("plan")
    p.add_argument("action", choices=["validate", "render"])
    p.add_argument("path")
    p.set_defaults(function=command_plan)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        function = cast(Callable[[argparse.Namespace], int], args.function)
        return function(args)
    except ExternalBlocked as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_EXTERNAL
    except (OSError, ValueError, ValidationError, RadarError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
