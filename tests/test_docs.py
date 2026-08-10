from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_quickstart_uses_the_supported_artifact_and_evaluation_commands() -> None:
    documents = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in ("README.md", "docs/QUICKSTART.md", "docs/REPRODUCIBILITY.md")
    )
    required = (
        "radar-bench artifacts fetch --suite decisive-v1.1 --output-root",
        "radar-bench artifacts verify --suite decisive-v1.1 --artifact-root",
        "radar-bench evaluate --suite decisive-v1.1 --artifact-root",
        "radar-bench verify-results",
    )
    for command in required:
        assert command in documents
    assert "artifacts verify --suite decisive-v1.1 --output-root" not in documents


def test_documentation_describes_the_fail_closed_scientific_boundary() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    threat_model = (ROOT / "docs/THREAT_MODEL.md").read_text(encoding="utf-8")
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "decisive-v1.1" in readme
    assert "UNSAFE" in readme
    assert "BLOCKED" in readme
    assert "network-denied" in readme
    assert "Gold is loaded only by the evaluator" in threat_model
    assert "no verified" in security
    assert "release remains blocked" in security
