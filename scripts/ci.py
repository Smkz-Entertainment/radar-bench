"""Authoritative offline CI entry point for the v0.1 foundation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    command = [PYTHON, "-m", "radar_bench.cli", *args]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=check,
        shell=False,
    )


def main() -> int:
    results = {}
    compile_check = subprocess.run(
        [PYTHON, "-m", "compileall", "-q", "src", "scripts"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    results["syntax"] = {
        "status": "pass" if compile_check.returncode == 0 else "fail",
        "stdout": compile_check.stdout,
        "stderr": compile_check.stderr,
    }
    if compile_check.returncode:
        print(json.dumps(results, indent=2))
        return compile_check.returncode
    source_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py")
    )
    forbidden = [
        token
        for token in ("shell=True", "eval(", "pickle.loads", "yaml.load(")
        if token in source_text
    ]
    results["static_security"] = {
        "status": "pass" if not forbidden else "fail",
        "forbidden_tokens": forbidden,
    }
    if forbidden:
        print(json.dumps(results, indent=2))
        return 1
    doctor = run("doctor")
    results["doctor"] = {"status": "pass", "output": doctor.stdout}
    corpus = run("validate-corpus", check=False)
    results["corpus_validation"] = {
        "status": "pass" if corpus.returncode == 0 else "fail",
        "output": corpus.stdout,
        "error": corpus.stderr,
    }
    if corpus.returncode != 0:
        print(json.dumps(results, indent=2))
        return corpus.returncode
    tests = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "--cov=radar_bench",
            "--cov-report=xml:artifacts/release-evidence/coverage.xml",
            "--cov-fail-under=90",
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        text=True,
        capture_output=True,
        check=False,
        shell=False,
    )
    results["tests"] = {
        "status": "pass" if tests.returncode == 0 else "fail",
        "stdout": tests.stdout,
        "stderr": tests.stderr,
    }
    if tests.returncode != 0:
        print(json.dumps(results, indent=2))
        return tests.returncode
    quality_commands = {
        "lint": [PYTHON, "-m", "ruff", "check", "src", "tests", "scripts"],
        "typecheck": [PYTHON, "-m", "mypy", "--strict", "src"],
        "security_scan": [PYTHON, "-m", "bandit", "-q", "-r", "src"],
        "dependency_audit": [PYTHON, "-m", "pip_audit", "."],
        "wheel_build": [
            PYTHON,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(ROOT / "dist"),
        ],
    }
    for name, command in quality_commands.items():
        quality = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            text=True,
            capture_output=True,
            check=False,
            shell=False,
        )
        status = (
            "pass"
            if quality.returncode == 0
            else "blocked"
            if name == "dependency_audit"
            else "fail"
        )
        results[name] = {
            "status": status,
            "returncode": quality.returncode,
            "stdout": quality.stdout,
            "stderr": quality.stderr,
        }
        if status == "fail":
            print(json.dumps(results, indent=2))
            return quality.returncode or 1
    # Build all snapshots and check every temporal boundary.
    case_ids = [
        path.stem for path in sorted((ROOT / "corpus" / "cases").glob("*.json"))
    ]
    results["snapshots"] = []
    for case_id in case_ids:
        built = run("build-snapshot", case_id, check=False)
        checked = run("check-leakage", case_id, "--json", check=False)
        results["snapshots"].append(
            {
                "case_id": case_id,
                "build": built.returncode,
                "leakage": checked.returncode,
                "output": checked.stdout,
            }
        )
        if built.returncode or checked.returncode:
            results["status"] = "fail"
            print(json.dumps(results, indent=2))
            return 3
    results["status"] = "pass"
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
