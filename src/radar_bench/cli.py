"""Small, fail-closed CLI for the public Radar Bench contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from radar_bench import __version__
from radar_bench.artifacts import fetch_artifacts, verify_artifacts
from radar_bench.config import project_root
from radar_bench.errors import RadarError, ValidationError
from radar_bench.release import (
    SUITE_ID,
    evaluate_decisive_suite,
    inspect_case,
    validate_decisive_suite,
)
from radar_bench.result_contract import validate_result_document

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_EXTERNAL = 4


def _root() -> Path:
    return project_root()


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def command_doctor(_args: argparse.Namespace) -> int:
    root = _root()
    _print_json(
        {
            "version": __version__,
            "suite": SUITE_ID,
            "resource_source": "repository"
            if (root / "pyproject.toml").is_file()
            else "installed-package",
            "python": sys.version.split()[0],
            "schemas": [
                "benchmark-result-v1.1.schema.json",
                "decisive-suite-v1.1.schema.json",
            ],
            "execution": {
                "platform": "linux/x86_64 Docker engine",
                "network": "denied during evaluation",
            },
        }
    )
    return EXIT_OK


def command_list_suites(_args: argparse.Namespace) -> int:
    _print_json(
        {
            "suites": [
                {
                    "suite_id": SUITE_ID,
                    "release_version": "1.0.1",
                    "case_count": 25,
                    "status": "corrected-executable-reference",
                }
            ]
        }
    )
    return EXIT_OK


def command_validate(args: argparse.Namespace) -> int:
    audit = validate_decisive_suite(
        _root(), artifact_root=Path(args.artifact_root).resolve()
        if args.artifact_root
        else None
    )
    _print_json(audit)
    return EXIT_OK if audit.get("valid") else EXIT_INVALID


def command_inspect_case(args: argparse.Namespace) -> int:
    try:
        _print_json(inspect_case(_root(), args.case_id))
        return EXIT_OK
    except (OSError, ValueError, ValidationError) as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID


def command_evaluate(args: argparse.Namespace) -> int:
    root = _root()
    artifact_root = Path(args.artifact_root).resolve() if args.artifact_root else None
    result = evaluate_decisive_suite(root, artifact_root=artifact_root)
    if args.output:
        _write_json(Path(args.output).resolve(), result)
    _print_json(result)
    return EXIT_OK if result.get("status") == "COMPLETED" else EXIT_EXTERNAL


def command_artifacts(args: argparse.Namespace) -> int:
    root = _root()
    artifact_root = Path(args.output_root).resolve() if args.output_root else None
    if args.action == "fetch":
        result = fetch_artifacts(root, args.suite, artifact_root)
    else:
        result = verify_artifacts(root, args.suite, artifact_root)
    _print_json(result)
    return EXIT_OK if result.get("status") == "READY" else EXIT_EXTERNAL


def command_verify_results(args: argparse.Namespace) -> int:
    root = _root()
    path = Path(args.path).resolve()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("result must be a JSON object")
        validate_result_document(document, root)
    except (OSError, ValueError, ValidationError) as exc:
        _print_json({"valid": False, "errors": [str(exc)]})
        return EXIT_INVALID
    _print_json({"valid": True, "suite_id": document["suite_id"], "status": document["status"]})
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar-bench",
        description="Validate and execute the fail-closed Radar Bench v1.0.1 suite.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor", help="show installation and runtime requirements").set_defaults(
        handler=command_doctor
    )
    commands.add_parser("list-suites", help="list immutable public suites").set_defaults(
        handler=command_list_suites
    )

    validate = commands.add_parser("validate", help="validate a suite contract")
    validate.add_argument("--suite", choices=[SUITE_ID], required=True)
    validate.add_argument("--artifact-root")
    validate.set_defaults(handler=command_validate)

    inspect = commands.add_parser("inspect-case", help="inspect a case without loading gold")
    inspect.add_argument("case_id")
    inspect.set_defaults(handler=command_inspect_case)

    evaluate = commands.add_parser("evaluate", help="execute and score a suite")
    evaluate.add_argument("--suite", choices=[SUITE_ID], required=True)
    evaluate.add_argument("--artifact-root", required=True)
    evaluate.add_argument("--output")
    evaluate.set_defaults(handler=command_evaluate)

    artifacts = commands.add_parser("artifacts", help="fetch or verify external artifacts")
    artifact_commands = artifacts.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("fetch", "reconstruct approved wheel artifacts"),
        ("verify", "verify local artifact bytes and hashes"),
    ):
        child = artifact_commands.add_parser(action, help=help_text)
        child.add_argument("--suite", choices=[SUITE_ID], required=True)
        child.add_argument("--output-root")
        child.set_defaults(handler=command_artifacts)

    verify = commands.add_parser("verify-results", help="validate a strict result document")
    verify.add_argument("path")
    verify.set_defaults(handler=command_verify_results)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except RadarError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
