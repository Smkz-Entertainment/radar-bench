"""Reject obsolete pre-publication wording in current public surfaces."""

from __future__ import annotations

import json
import sys
from pathlib import Path


OBSOLETE_PHRASES = (
    "repository remains private",
    "repository is private",
    "the repository is private",
    "has not been tagged",
    "has not been released",
    "awaiting independent release audit",
    "independent release audit remains required",
    "publication requires an independent release audit",
    "no verified private vulnerability",
    "private reporting is currently unavailable",
    "candidate-release-blocked-until-gates-pass",
    "decisive-v1.2 is blocked pending",
    "clean-clone reproduction remains pending",
)

ROOT_FILES = (
    "README.md",
    "BENCHMARK.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "benchmark-card.json",
    "src/radar_bench/cli.py",
)


def _paths(root: Path) -> list[Path]:
    paths = [root / item for item in ROOT_FILES]
    paths.extend(sorted((root / "docs").glob("*.md")))
    paths.append(root / "evidence" / "README.md")
    paths.extend(sorted((root / "evidence").glob("decisive-*/*")))
    return [path for path in paths if path.is_file()]


def scan(root: Path) -> dict[str, object]:
    findings: list[dict[str, object]] = []
    for path in _paths(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            findings.append({"path": path.relative_to(root).as_posix(), "error": type(exc).__name__})
            continue
        lowered = text.lower()
        for phrase in OBSOLETE_PHRASES:
            start = 0
            while True:
                index = lowered.find(phrase, start)
                if index < 0:
                    break
                line = lowered.count("\n", 0, index) + 1
                findings.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "line": line,
                        "phrase": phrase,
                    }
                )
                start = index + len(phrase)
    return {"status": "PASS" if not findings else "FAIL", "findings": findings}


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    root = Path(arguments[0]).resolve() if arguments else Path(__file__).resolve().parents[1]
    result = scan(root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
