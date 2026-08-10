from __future__ import annotations

import json
from pathlib import Path

import pytest

from radar_bench import config
from radar_bench import cli
from radar_bench.cli import main
from radar_bench.result_contract import (
    empty_metrics,
    file_digest,
    _normalise_metrics,
    _prediction,
    _runs_by_case,
    canonical_digest,
    compare_reference,
    validate_result,
)


ROOT = Path(__file__).resolve().parents[1]


def test_config_paths_and_installed_resource_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert config.project_root(ROOT) == ROOT
    monkeypatch.setenv("RADAR_BENCH_CACHE", str(tmp_path / "cache"))
    assert config.cache_root() == (tmp_path / "cache").resolve()
    assert config.schema_root(ROOT).is_dir()
    assert config.package_resource_root().is_dir()
    monkeypatch.delenv("RADAR_BENCH_CACHE")
    assert config.cache_root().name == "radar-bench"
    assert config.project_root(tmp_path).is_dir()
    assert config.schema_root(tmp_path).name == "schema"
    monkeypatch.setattr(config, "project_root", lambda _start=None: tmp_path / "missing-root")
    assert config.schema_root(tmp_path).name == "schema"


def test_result_contract_helpers_cover_metrics_and_runs() -> None:
    metrics = _normalise_metrics(
        {
            "historical_positive_resolution": {
                "value": 1.0,
                "numerator": 1,
                "denominator": 1,
                "status": "evaluable",
            },
            "candidate_induced_correctness": {"value": "bad"},
        }
    )
    assert metrics["historical_positive_resolution"]["value"] == 1.0
    assert metrics["candidate_induced_correctness"]["status"] == "not_evaluable"
    run = {"terminal": {"state": "CAUSALLY_ATTRIBUTED", "candidate_induced": True}, "attempts": [1]}
    assert _prediction("A", run)["substantive_experiments"] == 1
    raw = {
        "case_records": [{"case_id": "A", "episode_id": "opaque"}],
        "lanes": {"agentic-v0.5-frozen": {"runs": [{"episode_id": "opaque", "run": run}]}},
    }
    assert _runs_by_case(raw, "agentic-v0.5-frozen")["A"] == run
    assert canonical_digest({"b": 1, "a": 2}) == canonical_digest({"a": 2, "b": 1})
    assert len(empty_metrics()) == 11
    assert file_digest(ROOT / "reference" / "decisive-v1.1-result.json").startswith("sha256:")
    assert _runs_by_case({"harness": {"cases": [{"case_id": "B", "episode_id": "opaque-b"}]}, "lanes": {}}, "agentic-v0.5-frozen") == {}
    assert _runs_by_case({"cases": [{"case_id": "C", "episode_id": "opaque-c"}], "lanes": {}}, "agentic-v0.5-frozen") == {}


def test_reference_comparison_and_semantic_metric_validation() -> None:
    reference = json.loads(
        (ROOT / "reference" / "decisive-v1.1-result.json").read_text(encoding="utf-8")
    )
    assert compare_reference(reference, reference)["status"] == "EXACT_MATCH"
    changed = json.loads(json.dumps(reference))
    changed["mandatory_case_gates"]["pandas-45601-keeps-semantic-ambiguity-open"] = False
    assert compare_reference(changed, reference)["status"] == "MISMATCH"
    assert compare_reference(reference, None)["status"] == "NOT_AVAILABLE"
    assert compare_reference({"cases": []}, {"cases": {}})["status"] == "MISMATCH"
    invalid = json.loads(json.dumps(reference))
    invalid["baselines"]["static-v0.4"]["metrics"]["historical_positive_resolution"][
        "numerator"
    ] = 6
    with pytest.raises(Exception):
        validate_result(invalid)
    invalid["cases"]["blocked"] = 1
    with pytest.raises(Exception):
        validate_result(invalid)
    invalid["cases"]["blocked"] = 0
    metric = invalid["baselines"]["static-v0.4"]["metrics"]["historical_positive_resolution"]
    metric["numerator"] = 0
    metric["denominator"] = 0
    metric["status"] = "evaluable"
    with pytest.raises(Exception):
        validate_result(invalid)
    metric["status"] = "not_evaluable"
    metric["value"] = 1.0
    with pytest.raises(Exception):
        validate_result(invalid)


def test_cli_outputs_and_result_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert main(["doctor"]) == 0
    assert main(["list-suites"]) == 0
    assert main(["validate", "--suite", "decisive-v1.1"]) == 0
    assert main(["artifacts", "verify", "--suite", "decisive-v1.1", "--output-root", str(tmp_path)]) == 4
    monkeypatch.setattr(cli, "fetch_artifacts", lambda *_args: {"status": "BLOCKED"})
    assert main(["artifacts", "fetch", "--suite", "decisive-v1.1", "--output-root", str(tmp_path)]) == 4
    reference = ROOT / "reference" / "decisive-v1.1-result.json"
    assert main(["verify-results", str(reference)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert main(["verify-results", str(bad)]) == 2
    output = tmp_path / "blocked.json"
    assert main(
        [
            "evaluate",
            "--suite",
            "decisive-v1.1",
            "--artifact-root",
            str(tmp_path),
            "--output",
            str(output),
        ]
    ) == 4
    assert output.is_file()
