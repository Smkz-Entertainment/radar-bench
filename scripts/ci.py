"""Authoritative offline CI entry point for frozen milestones plus v0.4."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run_process(
    command: list[str],
    *,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=env or os.environ.copy(),
            text=True,
            capture_output=True,
            check=check,
            shell=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return subprocess.CompletedProcess(
            command,
            124,
            stdout,
            f"timed out after {timeout_seconds}s\n{stderr}",
        )


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [PYTHON, "-m", "radar_bench.cli", *args]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return run_process(command, timeout_seconds=180, env=env, check=check)


def main() -> int:
    results = {}
    compile_check = run_process(
        [PYTHON, "-m", "compileall", "-q", "src", "scripts"],
        timeout_seconds=60,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
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
    v1_suite = run("validate", "--suite", "decisive-v1", check=False)
    results["v1_suite"] = {
        "status": "pass" if v1_suite.returncode == 0 else "fail",
        "output": v1_suite.stdout,
        "error": v1_suite.stderr,
    }
    if v1_suite.returncode != 0:
        print(json.dumps(results, indent=2))
        return v1_suite.returncode
    v02_corpus = run("validate-v02-corpus", check=False)
    results["v02_corpus_plan"] = {
        "status": "pass" if v02_corpus.returncode == 0 else "fail",
        "output": v02_corpus.stdout,
        "error": v02_corpus.stderr,
    }
    if v02_corpus.returncode != 0:
        print(json.dumps(results, indent=2))
        return v02_corpus.returncode
    v03_corpus = run("validate-v03-corpus", "--json", check=False)
    results["v03_corpus_plan"] = {
        "status": "pass" if v03_corpus.returncode == 0 else "fail",
        "output": v03_corpus.stdout,
        "error": v03_corpus.stderr,
    }
    if v03_corpus.returncode != 0:
        print(json.dumps(results, indent=2))
        return v03_corpus.returncode
    v04_corpus: subprocess.CompletedProcess[str] | None = None
    v04_records = ROOT / "corpus" / "v0.4" / "pilot" / "records"
    if any(v04_records.glob("*.json")):
        v04_corpus = run("validate-v04-corpus", "--json", check=False)
        results["v04_corpus"] = {
            "status": "pass" if v04_corpus.returncode == 0 else "fail",
            "output": v04_corpus.stdout,
            "error": v04_corpus.stderr,
        }
    if v04_corpus is not None and v04_corpus.returncode != 0:
        print(json.dumps(results, indent=2))
        return v04_corpus.returncode
    v05_episodes = ROOT / "artifacts" / "release-evidence" / "investigation-episodes.json"
    if v05_episodes.exists():
        v05_validation = run("validate-v05-episodes", check=False)
        results["v05_episodes"] = {
            "status": "pass" if v05_validation.returncode == 0 else "fail",
            "output": v05_validation.stdout,
            "error": v05_validation.stderr,
        }
        if v05_validation.returncode != 0:
            print(json.dumps(results, indent=2))
            return v05_validation.returncode
    v06_result = ROOT / "artifacts" / "v06-result.json"
    if v06_result.exists():
        v06_validation = run("validate-v06-integrity", check=False)
        results["v06_integrity"] = {
            "status": "pass" if v06_validation.returncode == 0 else "fail",
            "output": v06_validation.stdout,
            "error": v06_validation.stderr,
        }
        if v06_validation.returncode != 0:
            print(json.dumps(results, indent=2))
            return v06_validation.returncode
    v07_result = ROOT / "artifacts" / "v07-result.json"
    if v07_result.exists():
        v07_validation = run("validate-v07-executable", check=False)
        results["v07_executable"] = {
            "status": "pass" if v07_validation.returncode == 0 else "fail",
            "output": v07_validation.stdout,
            "error": v07_validation.stderr,
        }
        if v07_validation.returncode != 0:
            print(json.dumps(results, indent=2))
            return v07_validation.returncode
    tests = run_process(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "--cov=radar_bench",
            "--cov-report=xml:artifacts/release-evidence/coverage.xml",
            "--cov-fail-under=90",
        ],
        timeout_seconds=600,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
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
        quality = run_process(
            command,
            timeout_seconds=180,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
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
    blocked = any(item.get("status") == "blocked" for item in results.values() if isinstance(item, dict))
    results["status"] = "blocked" if blocked else "pass"
    print(json.dumps(results, indent=2))
    return 4 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
