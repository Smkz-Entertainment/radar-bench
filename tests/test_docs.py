from __future__ import annotations

from pathlib import Path

from scripts.check_links import check as check_links
from scripts.check_public_state import scan as scan_public_state

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
        "radar-bench artifacts fetch --suite decisive-v1.2 --output-root",
        "--evaluator-bundle",
        "--candidate-image",
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
    assert "security/advisories/new" in security
    assert "multi-tenant isolation" in security


def test_current_public_state_and_local_links_are_clean() -> None:
    assert scan_public_state(ROOT)["status"] == "PASS"
    assert check_links(ROOT)["status"] == "PASS"


def test_public_state_scanner_rejects_obsolete_current_wording(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "The repository remains private until publication.\n", encoding="utf-8"
    )
    assert scan_public_state(tmp_path)["status"] == "FAIL"
