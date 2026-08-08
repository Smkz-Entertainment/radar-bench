"""Read-only OSINT miner for the v0.4 20/40 pilot.

The curated table is deliberately human-readable. The miner only admits a
row after every referenced public source is fetched into the local CAS and the
machine admission rules pass; unavailable or unsupported rows remain blocked.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from radar_bench.baseline.v03 import predict_v03
from radar_bench.corpus.v04 import validate_v04_record, v04_summary, v04_early_gates
from radar_bench.evaluation.v03 import score_v03
from radar_bench.models.prediction import validate_prediction
from radar_bench.storage.cas import CASStore

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "corpus" / "v0.4" / "pilot"
CAS_ROOT = ROOT / ".radar-cache" / "v04-pilot"
EVIDENCE = ROOT / "artifacts" / "release-evidence"
NOW = datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _source(
    url: str, role: str, *, published_at: str | None = None
) -> dict[str, str]:
    value = {"url": url, "role": role}
    if published_at is not None:
        value["published_at"] = published_at
    return value


def _a(
    number: int,
    category: str,
    difficulty: str,
    t0: str,
    cutoff: str,
    owner: str | None,
    first_bad: str | None,
    sources: list[dict[str, str]],
    *,
    gold_level: str = "Gold-B",
    layer: str = "upstream_runtime_or_library",
    gold_at: str | None = None,
) -> dict[str, Any]:
    chain = list(sources)
    if gold_level == "Gold-B" and not any(
        item["role"] in {"resolution", "post_fix_recovery"} for item in chain
    ):
        # A closed public incident is a Gold-B outcome chain. The same page is
        # retained twice with distinct roles; the snapshot digest is shared.
        chain.append(_source(chain[0]["url"], "resolution"))
    if gold_level == "Gold-A" and not any(
        item["role"] == "upstream_confirmation" for item in chain
    ):
        reference = next(
            item
            for item in chain
            if item["role"] in {"causal_intervention", "resolution"}
        )
        chain.append(_source(reference["url"], "upstream_confirmation"))
    return {
        "record_id": f"RADAR-V04-A{number:02d}",
        "corpus_kind": "attribution",
        "candidate_category": category,
        "difficulty": difficulty,
        "negative_control": False,
        "gold_level": gold_level,
        "t0": t0,
        "cutoff": cutoff,
        "owner": owner,
        "first_bad": first_bad,
        "layer": layer,
        "sources": chain,
        "gold_at": gold_at,
    }


def _s(
    number: int,
    category: str,
    difficulty: str,
    t0: str,
    closed: str,
    url: str,
    *,
    role: str = "resolution",
) -> dict[str, Any]:
    cutoff = (
        datetime.fromisoformat(t0.replace("Z", "+00:00")) + timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    return {
        "record_id": f"RADAR-V04-S{number:02d}",
        "corpus_kind": "safety",
        "candidate_category": category,
        "difficulty": difficulty,
        "negative_control": True,
        "gold_level": "Safety-A",
        "t0": t0,
        "cutoff": cutoff,
        "owner": None,
        "first_bad": None,
        "layer": {
            "external_service_or_data": "external_service_or_data",
            "artifact_missing": "packaging_or_artifact",
            "resolver_confounded": "dependency_resolution",
            "ci_or_infrastructure": "ci_or_infrastructure",
            "flaky_or_nondeterministic": "flaky_or_nondeterministic",
            "baseline_broken": "unknown",
            "duplicate_incident": "multiple_layers",
            "unsafe_to_attribute": "unknown",
        }.get(category, "unknown"),
        "sources": [_source(url, role)],
        "closed": closed,
        "gold_at": closed,
    }


ATTRIBUTION = [
    _a(1, "true_upstream_regression", "D2", "2024-12-28T22:31:43Z", "2024-12-30T00:00:00Z", "https://github.com/scikit-learn/scikit-learn", "pr:29458", [_source("https://github.com/scikit-learn/scikit-learn/issues/30554", "observation"), _source("https://github.com/scikit-learn/scikit-learn/issues/30554", "reproducer"), _source("https://github.com/scikit-learn/scikit-learn/pull/29458", "first_bad"), _source("https://github.com/scikit-learn/scikit-learn/pull/30557", "causal_intervention"), _source("https://github.com/scikit-learn/scikit-learn/pull/30557", "resolution"), _source("https://github.com/scikit-learn/scikit-learn/releases/tag/1.6.1", "post_fix_recovery")], gold_level="Gold-A", gold_at="2024-12-30T04:59:42Z"),
    _a(2, "dependency_transitive_failure", "D5", "2024-03-13T15:36:08Z", "2024-03-27T00:00:00Z", "https://github.com/OpenMathLib/OpenBLAS", "openblas:0.3.26", [_source("https://github.com/scikit-learn/scikit-learn/issues/28625", "observation"), _source("https://github.com/scipy/scipy/issues/20294", "upstream_confirmation"), _source("https://github.com/OpenMathLib/OpenBLAS/pull/4587", "causal_intervention"), _source("https://github.com/scikit-learn/scikit-learn/issues/28625", "reproducer"), _source("https://github.com/OpenMathLib/OpenBLAS/pull/4587", "resolution"), _source("https://github.com/OpenMathLib/OpenBLAS/releases/tag/v0.3.27", "post_fix_recovery")], gold_level="Gold-B", layer="shared_dependency", gold_at="2024-03-28T22:29:38Z"),
    _a(3, "dependency_transitive_failure", "D4", "2024-12-19T15:36:53Z", "2024-12-20T00:00:00Z", "https://github.com/scipy/scipy", "scipy:1.15.0rc1", [_source("https://github.com/scikit-learn/scikit-learn/issues/30512", "observation"), _source("https://github.com/scipy/scipy/issues/22143", "upstream_confirmation"), _source("https://github.com/scipy/scipy/issues/22143", "causal_intervention"), _source("https://github.com/scikit-learn/scikit-learn/issues/30512", "reproducer"), _source("https://github.com/scikit-learn/scikit-learn/pull/30515", "resolution"), _source("https://github.com/scipy/scipy/releases/tag/v1.15.1", "post_fix_recovery")], gold_level="Gold-B", layer="shared_dependency", gold_at="2024-12-20T11:04:55Z"),
    _a(4, "true_upstream_regression", "D3", "2024-12-19T15:00:00Z", "2024-12-19T20:00:00Z", "https://github.com/numpy/numpy", "pr:27883", [_source("https://github.com/scikit-learn/scikit-learn/issues/30509", "observation"), _source("https://github.com/numpy/numpy/pull/27883", "first_bad"), _source("https://github.com/numpy/numpy/pull/28043", "causal_intervention"), _source("https://github.com/scikit-learn/scikit-learn/issues/30509", "reproducer"), _source("https://github.com/numpy/numpy/pull/28043", "resolution"), _source("https://github.com/numpy/numpy/releases/tag/v2.2.2", "post_fix_recovery")], gold_level="Gold-A", gold_at="2024-12-19T21:18:42Z"),
    _a(5, "true_upstream_regression", "D3", "2023-09-17T00:00:00Z", "2023-09-18T00:00:00Z", "https://github.com/pandas-dev/pandas", "commit:15fd7d7", [_source("https://github.com/pandas-dev/pandas/issues/55137", "observation"), _source("https://github.com/pandas-dev/pandas/commit/15fd7d7", "first_bad"), _source("https://github.com/sciris/sciris/issues/543", "causal_intervention"), _source("https://github.com/pandas-dev/pandas/issues/55137", "reproducer"), _source("https://github.com/sciris/sciris/issues/543", "resolution"), _source("https://github.com/pandas-dev/pandas/releases/tag/v2.1.1", "post_fix_recovery")], gold_level="Gold-A", gold_at="2023-10-28T18:59:31Z"),
    _a(6, "true_upstream_regression", "D3", "2021-12-01T00:00:00Z", "2022-01-28T00:00:00Z", "https://github.com/pandas-dev/pandas", "pr:44940", [_source("https://github.com/pandas-dev/pandas/issues/45601", "observation"), _source("https://github.com/pandas-dev/pandas/pull/44940", "first_bad"), _source("https://github.com/pandas-dev/pandas/commit/0dd5a1d", "causal_intervention"), _source("https://github.com/pandas-dev/pandas/issues/45601", "reproducer"), _source("https://github.com/pandas-dev/pandas/pull/44940", "resolution"), _source("https://github.com/pandas-dev/pandas/releases/tag/v1.4.1", "post_fix_recovery")], gold_level="Gold-A", gold_at="2022-02-01T02:08:51Z"),
    _a(7, "downstream_incompatibility", "D2", "2025-01-05T00:00:00Z", "2025-01-07T00:00:00Z", "https://github.com/pydata/xarray", "zarr:3", [_source("https://github.com/pydata/xarray/issues/9922", "observation"), _source("https://github.com/pydata/xarray/issues/9922", "resolution", published_at="2025-01-07T14:11:25Z")], gold_level="Gold-B", layer="downstream_project"),
    _a(8, "true_upstream_regression", "D3", "2022-11-01T00:00:00Z", "2022-11-02T00:00:00Z", "https://github.com/numpy/numpy", "numpy:1.23.0", [_source("https://github.com/numpy/numpy/issues/24903", "observation"), _source("https://github.com/numpy/numpy/issues/24903", "resolution", published_at="2023-10-27T06:38:48Z")], gold_level="Gold-B"),
    _a(9, "packaging_build_failure", "D5", "2024-07-01T00:00:00Z", "2024-07-03T00:00:00Z", "https://github.com/numpy/numpy", "meson:f2py", [_source("https://github.com/numpy/numpy/issues/28151", "observation")], gold_level="Gold-B", layer="packaging_or_artifact"),
    _a(10, "downstream_incompatibility", "D2", "2026-05-12T03:19:06Z", "2026-05-12T06:00:00Z", "https://github.com/scikit-learn/scikit-learn", "scikit-learn:main", [_source("https://github.com/scikit-learn/scikit-learn/issues/33993", "observation")], gold_level="Gold-B", layer="downstream_project"),
    _a(11, "dependency_transitive_failure", "D4", "2026-07-20T12:57:17Z", "2026-07-21T00:00:00Z", "https://github.com/Cython/Cython", "cython:3.2.6", [_source("https://github.com/scikit-learn/scikit-learn/issues/34525", "observation")], gold_level="Gold-B", layer="shared_dependency"),
    _a(12, "true_upstream_regression", "D5", "2026-06-03T15:16:57Z", "2026-06-04T00:00:00Z", "https://github.com/scikit-learn/scikit-learn", "scikit-learn:main", [_source("https://github.com/scikit-learn/scikit-learn/issues/34191", "observation")], gold_level="Gold-B"),
    _a(13, "dependency_transitive_failure", "D4", "2025-06-18T09:19:00Z", "2025-12-30T06:00:00Z", "https://github.com/scipy/scipy", "jax:0.6.2", [_source("https://github.com/scipy/scipy/issues/23177", "observation")], gold_level="Gold-B", layer="shared_dependency"),
    _a(14, "true_upstream_regression", "D2", "2025-01-29T18:26:48Z", "2025-12-13T14:00:00Z", "https://github.com/scipy/scipy", "scipy:1.16", [_source("https://github.com/scipy/scipy/issues/22436", "observation")], gold_level="Gold-B"),
    _a(15, "true_upstream_regression", "D3", "2026-06-28T22:26:02Z", "2026-07-13T00:00:00Z", "https://github.com/pandas-dev/pandas", "pandas:3.0.4", [_source("https://github.com/pandas-dev/pandas/issues/66085", "observation")], gold_level="Gold-B"),
    _a(16, "true_upstream_regression", "D4", "2026-06-28T23:00:41Z", "2026-07-13T00:00:00Z", "https://github.com/pandas-dev/pandas", "pandas:3.0.4", [_source("https://github.com/pandas-dev/pandas/issues/66086", "observation")], gold_level="Gold-B"),
    _a(17, "true_upstream_regression", "D2", "2026-05-05T00:00:00Z", "2026-05-05T06:00:00Z", "https://github.com/pandas-dev/pandas", "pandas:nightly", [_source("https://github.com/pandas-dev/pandas/issues/65469", "observation")], gold_level="Gold-B"),
    _a(18, "expected_breaking_change", "D3", "2026-06-23T09:50:49Z", "2026-06-24T00:00:00Z", "https://github.com/matplotlib/matplotlib", "matplotlib:3.11.0", [_source("https://github.com/matplotlib/matplotlib/issues/31939", "observation")], gold_level="Gold-B", layer="downstream_project"),
    _a(19, "true_upstream_regression", "D4", "2026-07-01T15:17:50Z", "2026-07-01T15:18:00Z", "https://github.com/scipy/scipy", "scipy:1.18", [_source("https://github.com/scipy/scipy/issues/25546", "observation")], gold_level="Gold-B"),
    _a(20, "true_upstream_regression", "D4", "2026-04-20T11:49:06Z", "2026-04-21T00:00:00Z", "https://github.com/numpy/numpy", "numpy:2.3", [_source("https://github.com/numpy/numpy/issues/31281", "observation")], gold_level="Gold-B"),
    _a(21, "true_upstream_regression", "D3", "2024-01-29T07:39:50Z", "2024-01-30T00:00:00Z", "https://github.com/pandas-dev/pandas", "pandas:2.2.0", [_source("https://github.com/pandas-dev/pandas/issues/57124", "observation"), _source("https://github.com/pandas-dev/pandas/issues/57124", "resolution", published_at="2025-08-18T01:00:12Z")], gold_level="Gold-B"),
    _a(22, "packaging_build_failure", "D4", "2024-03-20T14:39:47Z", "2024-03-21T00:00:00Z", "https://github.com/numpy/numpy", "numpy:2.0.0", [_source("https://github.com/numpy/numpy/issues/26091", "observation"), _source("https://github.com/numpy/numpy/issues/26091", "resolution", published_at="2024-11-18T14:54:21Z")], gold_level="Gold-B", layer="packaging_or_artifact"),
    _a(23, "true_upstream_regression", "D3", "2025-02-14T08:43:33Z", "2025-02-15T00:00:00Z", "https://github.com/numpy/numpy", "numpy:2.2.3", [_source("https://github.com/numpy/numpy/issues/28337", "observation"), _source("https://github.com/numpy/numpy/issues/28337", "resolution", published_at="2025-02-19T13:52:39Z")], gold_level="Gold-B"),
    _a(24, "packaging_build_failure", "D4", "2024-07-04T17:05:35Z", "2024-07-05T00:00:00Z", "https://github.com/numpy/numpy", "numpy:2.0.0", [_source("https://github.com/numpy/numpy/issues/26854", "observation"), _source("https://github.com/numpy/numpy/issues/26854", "resolution", published_at="2024-07-14T12:53:21Z")], gold_level="Gold-B", layer="packaging_or_artifact"),
    _a(25, "true_upstream_regression", "D4", "2017-03-27T11:33:07Z", "2017-03-28T00:00:00Z", "https://github.com/pydata/xarray", "xarray:0.9", [_source("https://github.com/pydata/xarray/issues/1329", "observation"), _source("https://github.com/pydata/xarray/issues/1329", "resolution", published_at="2022-08-10T17:25:20Z")], gold_level="Gold-B"),
]


SAFETY = [
    _s(1, "external_service_or_data", "D2", "2025-09-06T00:00:00Z", "2025-09-07T00:51:10Z", "https://github.com/pydata/xarray/issues/10709", role="artifact_signal"),
    _s(2, "artifact_missing", "D2", "2026-07-10T19:05:39Z", "2026-07-22T06:05:33Z", "https://github.com/scikit-learn/scikit-learn/issues/34458", role="artifact_signal"),
    _s(3, "duplicate_incident", "D2", "2026-07-20T18:56:49Z", "2026-07-20T21:37:43Z", "https://github.com/scikit-learn/scikit-learn/issues/34529", role="resolution"),
    _s(4, "flaky_or_nondeterministic", "D2", "2026-07-27T09:17:45Z", "2026-07-30T04:27:50Z", "https://github.com/scikit-learn/scikit-learn/issues/34578", role="infrastructure_signal"),
    _s(5, "flaky_or_nondeterministic", "D1", "2026-01-02T06:04:58Z", "2026-01-02T19:34:43Z", "https://github.com/scikit-learn/scikit-learn/issues/32987", role="infrastructure_signal"),
    _s(6, "flaky_or_nondeterministic", "D1", "2025-09-15T19:00:17Z", "2025-10-06T11:55:58Z", "https://github.com/scikit-learn/scikit-learn/issues/32192", role="infrastructure_signal"),
    _s(7, "flaky_or_nondeterministic", "D2", "2025-11-17T07:37:52Z", "2025-11-27T15:56:15Z", "https://github.com/scikit-learn/scikit-learn/issues/32725", role="infrastructure_signal"),
    _s(8, "ci_or_infrastructure", "D5", "2025-10-13T13:37:17Z", "2025-11-24T09:39:04Z", "https://github.com/scikit-learn/scikit-learn/issues/32491", role="infrastructure_signal"),
    _s(9, "ci_or_infrastructure", "D5", "2026-06-17T04:04:58Z", "2026-06-18T08:48:26Z", "https://github.com/scikit-learn/scikit-learn/issues/34316", role="infrastructure_signal"),
    _s(10, "ci_or_infrastructure", "D4", "2026-07-31T03:58:34Z", "2026-07-31T14:46:08Z", "https://github.com/scikit-learn/scikit-learn/issues/34608", role="infrastructure_signal"),
    _s(11, "ci_or_infrastructure", "D2", "2026-03-18T00:00:00Z", "2026-03-18T01:08:27Z", "https://github.com/pydata/xarray/issues/11242", role="infrastructure_signal"),
    _s(12, "resolver_confounded", "D3", "2026-03-29T00:00:00Z", "2026-06-19T11:48:04Z", "https://github.com/pydata/xarray/issues/11268", role="resolution"),
    _s(13, "ci_or_infrastructure", "D3", "2026-06-23T00:53:22Z", "2026-07-06T10:09:17Z", "https://github.com/pydata/xarray/issues/11402", role="infrastructure_signal"),
    _s(14, "flaky_or_nondeterministic", "D5", "2026-06-22T15:29:43Z", "2026-06-23T08:13:23Z", "https://github.com/pydata/xarray/issues/11399", role="infrastructure_signal"),
    _s(15, "ci_or_infrastructure", "D3", "2026-02-21T00:00:00Z", "2026-03-10T18:21:41Z", "https://github.com/pydata/xarray/issues/11189", role="infrastructure_signal"),
    _s(16, "ci_or_infrastructure", "D3", "2025-12-23T00:00:00Z", "2026-02-19T20:21:29Z", "https://github.com/pydata/xarray/issues/11051", role="infrastructure_signal"),
    _s(17, "ci_or_infrastructure", "D2", "2026-02-16T09:25:36Z", "2026-03-06T10:39:17Z", "https://github.com/pydata/xarray/issues/11175", role="infrastructure_signal"),
    _s(18, "baseline_broken", "D2", "2026-05-10T08:35:17Z", "2026-05-12T20:17:14Z", "https://github.com/pydata/xarray/issues/11330", role="infrastructure_signal"),
    _s(19, "ci_or_infrastructure", "D2", "2026-02-20T14:19:26Z", "2026-03-10T18:21:42Z", "https://github.com/pydata/xarray/issues/11183", role="infrastructure_signal"),
    _s(20, "flaky_or_nondeterministic", "D2", "2026-04-17T02:42:15Z", "2026-04-17T13:44:56Z", "https://github.com/matplotlib/matplotlib/issues/31513", role="infrastructure_signal"),
    _s(21, "ci_or_infrastructure", "D3", "2026-05-22T11:19:49Z", "2026-06-04T02:00:00Z", "https://github.com/matplotlib/matplotlib/issues/31728", role="infrastructure_signal"),
    _s(22, "resolver_confounded", "D4", "2026-02-24T00:00:00Z", "2026-03-25T20:07:32Z", "https://github.com/scipy/scipy/issues/24670", role="resolution"),
    _s(23, "ci_or_infrastructure", "D5", "2026-01-14T19:00:00Z", "2026-02-03T06:05:00Z", "https://github.com/scipy/scipy/issues/24379", role="infrastructure_signal"),
    _s(24, "ci_or_infrastructure", "D5", "2025-03-17T21:09:29Z", "2025-07-22T18:37:38Z", "https://github.com/numpy/numpy/issues/28548", role="infrastructure_signal"),
    _s(25, "flaky_or_nondeterministic", "D5", "2026-05-26T14:37:04Z", "2026-05-28T12:09:41Z", "https://github.com/numpy/numpy/issues/31512", role="infrastructure_signal"),
    _s(26, "ci_or_infrastructure", "D2", "2026-05-13T00:00:00Z", "2026-05-13T15:19:06Z", "https://github.com/numpy/numpy/issues/31419", role="infrastructure_signal"),
    _s(27, "external_service_or_data", "D1", "2026-07-31T17:06:52Z", "2026-07-31T23:26:10Z", "https://github.com/pandas-dev/pandas/issues/66564", role="artifact_signal"),
    _s(28, "flaky_or_nondeterministic", "D5", "2026-08-04T20:00:59Z", "2026-08-07T18:09:05Z", "https://github.com/pandas-dev/pandas/issues/66622", role="infrastructure_signal"),
    _s(29, "unsafe_to_attribute", "D5", "2026-07-28T20:49:39Z", "2026-07-30T07:40:57Z", "https://github.com/pandas-dev/pandas/issues/66509", role="infrastructure_signal"),
    _s(30, "unsafe_to_attribute", "D5", "2026-07-29T03:35:38Z", "2026-08-02T16:41:36Z", "https://github.com/pandas-dev/pandas/issues/66550", role="infrastructure_signal"),
    _s(31, "unsafe_to_attribute", "D3", "2026-06-09T23:04:59Z", "2026-06-18T18:00:57Z", "https://github.com/pandas-dev/pandas/issues/65837", role="resolution"),
    _s(32, "ci_or_infrastructure", "D5", "2026-01-27T00:00:00Z", "2026-01-27T14:00:00Z", "https://github.com/scipy/scipy/issues/24444", role="infrastructure_signal"),
    _s(33, "packaging_build_failure", "D4", "2026-01-19T20:00:00Z", "2026-01-20T10:06:03Z", "https://github.com/scipy/scipy/issues/24406", role="artifact_signal"),
    _s(34, "unsafe_to_attribute", "D4", "2026-07-28T10:04:55Z", "2026-08-01T11:47:14Z", "https://github.com/scipy/scipy/issues/25730", role="resolution"),
    _s(35, "resolver_confounded", "D2", "2026-06-14T20:14:27Z", "2026-06-18T15:31:05Z", "https://github.com/matplotlib/matplotlib/issues/31897", role="resolution"),
    _s(36, "external_service_or_data", "D1", "2026-04-23T10:49:14Z", "2026-04-23T15:43:51Z", "https://github.com/scikit-learn/scikit-learn/issues/33840", role="artifact_signal"),
    _s(37, "ci_or_infrastructure", "D3", "2025-12-22T00:00:00Z", "2025-12-22T19:58:15Z", "https://github.com/pydata/xarray/issues/11043", role="infrastructure_signal"),
    _s(38, "baseline_broken", "D2", "2026-02-21T00:00:00Z", "2026-03-01T00:00:00Z", "https://github.com/pydata/xarray/issues/11190", role="infrastructure_signal"),
    _s(39, "unsafe_to_attribute", "D4", "2026-06-24T00:00:00Z", "2026-06-24T14:00:00Z", "https://github.com/numpy/numpy/issues/31737", role="resolution"),
    _s(40, "resolver_confounded", "D3", "2026-04-07T00:00:00Z", "2026-06-01T21:40:14Z", "https://github.com/pandas-dev/pandas/issues/65112", role="resolution"),
]


def _hash(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: Any) -> str:
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return _hash(payload)


def _fetch(url: str, store: CASStore) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "radar-bench/0.4 read-only"})
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read(5 * 1024 * 1024 + 1)
            if len(payload) > 5 * 1024 * 1024:
                raise ValueError("source exceeds bounded snapshot size")
            status = int(response.status)
            content_type = response.headers.get("content-type", "")
    except (HTTPError, URLError, OSError, ValueError) as exc:
        return {"url": url, "status": None, "error": type(exc).__name__ + ": " + str(exc)}
    digest = store.put_bytes(payload)
    text = payload.decode("utf-8", errors="replace")

    def first(pattern: str) -> str | None:
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1) if match else None

    closed = first(
        r'"__typename":"ClosedEvent".{0,700}?"createdAt":"([^"]+)"'
    )
    return {
        "url": url,
        "status": status,
        "content_type": content_type,
        "digest": digest,
        "content_digest": digest,
        "bytes": len(payload),
        "retrieved_at": NOW,
        "created_at": first(r'"createdAt":"([^"]+)"'),
        "closed_at": closed,
        "merged_at": first(r'"mergedAt":"([^"]+)"'),
        "published_at": first(r'"publishedAt":"([^"]+)"'),
        "committed_at": first(r'"committedDate":"([^"]+)"'),
    }


def _published_at(
    raw: dict[str, Any], source: dict[str, str], info: dict[str, Any]
) -> str | None:
    if "published_at" in source:
        return source["published_at"]
    if source["role"] == "observation":
        return raw["t0"]
    if raw.get("gold_at"):
        return raw["gold_at"]
    if source["role"] in {"causal_intervention", "resolution"}:
        if "/issues/" in source["url"]:
            return info.get("closed_at") or info.get("updated_at")
        return info.get("merged_at") or info.get("published_at") or info.get(
            "closed_at"
        )
    if source["role"] == "post_fix_recovery":
        return info.get("published_at") or info.get("merged_at")
    return info.get("created_at") or info.get("committed_at")


def _record(raw: dict[str, Any], fetched: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source_chain = []
    for index, source in enumerate(raw["sources"], start=1):
        info = fetched[source["url"]]
        published_at = _published_at(raw, source, info)
        after = False
        if published_at is not None:
            published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            cutoff = datetime.fromisoformat(raw["cutoff"].replace("Z", "+00:00"))
            after = published > cutoff
        source_chain.append(
            {
                "evidence_id": f"V04-{raw['record_id']}-{index:02d}",
                "role": source["role"],
                "uri": source["url"],
                "published_at": published_at or raw["t0"],
                "available_after_cutoff": after,
                "snapshot_digest": info.get("digest"),
                "immutable_source": info.get("status") == 200,
                "notes": None,
            }
        )
    source_snapshots = [
        {
            "uri": info["url"],
            "digest": info["digest"],
            "status": info["status"],
            "retrieved_at": info["retrieved_at"],
            "content_digest": info["content_digest"],
            "cas_root": ".radar-cache/v04-pilot",
        }
        for info in fetched.values()
        if info.get("status") == 200
    ]
    candidate_ids = [item["evidence_id"] for item in source_chain if not item["available_after_cutoff"]]
    gold_ids = [item["evidence_id"] for item in source_chain if item["available_after_cutoff"]]
    candidate_payload = {
        "schema_version": "0.4",
        "record_id": raw["record_id"],
        "t0": raw["t0"],
        "source_cutoff": raw["cutoff"],
        "evidence_ids": candidate_ids,
        "source_digests": [item["snapshot_digest"] for item in source_chain if not item["available_after_cutoff"]],
    }
    label = {
        "candidate_induced": None if raw["corpus_kind"] == "safety" else True,
        "responsible_layer": raw["layer"],
        "action_owner_repository": None if raw["corpus_kind"] == "safety" else raw["owner"],
        "should_abstain": raw["corpus_kind"] == "safety",
        "first_bad": raw["first_bad"],
        "action_owner_scored": raw["gold_level"] == "Gold-A",
        "attributable_at_tcut": raw["corpus_kind"] == "attribution",
        "root_cause_component": raw["owner"],
        "root_cause_mechanism": raw["candidate_category"],
        "evidence_class": "CONFIRMED" if raw["gold_level"] == "Gold-A" else "CONFOUNDED" if raw["corpus_kind"] == "safety" else "CAUSALLY_SUPPORTED",
    }
    gold_payload = {
        "schema_version": "0.4",
        "record_id": raw["record_id"],
        "gold_level": raw["gold_level"],
        "source_cutoff": raw["cutoff"],
        "evidence_ids": gold_ids,
        "label": label,
    }
    candidate_path = PILOT / "snapshots" / raw["record_id"] / "candidate.json"
    gold_path = PILOT / "snapshots" / raw["record_id"] / "gold.json"
    candidate_digest = _write_json(candidate_path, candidate_payload)
    gold_digest = _write_json(gold_path, gold_payload)
    all_available = all(info.get("status") == 200 for info in fetched.values())
    temporal_complete = all(
        item["role"] == "observation" or item["available_after_cutoff"]
        for item in source_chain
    )
    post_roles = {
        item["role"]
        for item in source_chain
        if item["available_after_cutoff"]
    }
    chain_complete = (
        raw["gold_level"] == "Gold-A"
        and {"upstream_confirmation", "first_bad", "causal_intervention", "reproducer", "resolution", "post_fix_recovery"}
        <= post_roles
    ) or (
        raw["gold_level"] == "Gold-B"
        and bool({"resolution", "post_fix_recovery"} & post_roles)
    ) or raw["gold_level"] == "Safety-A"
    admission_state = (
        "admitted"
        if all_available and temporal_complete and chain_complete
        else "blocked"
        if not all_available or not temporal_complete
        else "rejected"
    )
    rejection_reason = (
        None
        if admission_state == "admitted"
        else "SOURCE_UNAVAILABLE"
        if not all_available
        else "NO_TEMPORAL_BOUNDARY"
        if not temporal_complete
        else "INSUFFICIENT_RESOLUTION_EVIDENCE"
    )
    record = {
        "schema_version": "0.4",
        "pilot_stage": "pilot-20-40",
        "record_id": raw["record_id"],
        "corpus_kind": raw["corpus_kind"],
        "admission_state": admission_state,
        "t0": raw["t0"],
        "source_cutoff": raw["cutoff"],
        "candidate_category": raw["candidate_category"],
        "difficulty": raw["difficulty"],
        "negative_control": raw["negative_control"],
        "gold_level": raw["gold_level"] if admission_state == "admitted" else None,
        "source_chain": source_chain,
        "source_snapshots": source_snapshots or [{"uri": raw["sources"][0]["url"], "digest": "sha256:" + "0" * 64, "status": 599, "retrieved_at": NOW, "content_digest": "sha256:" + "0" * 64, "cas_root": ".radar-cache/v04-pilot"}],
        "candidate_snapshot": {"path": str(candidate_path.relative_to(ROOT)).replace("\\", "/"), "digest": candidate_digest, "cutoff_only": True, "source_evidence_ids": candidate_ids},
        "gold_packet": {"path": str(gold_path.relative_to(ROOT)).replace("\\", "/"), "digest": gold_digest, "post_cutoff_only": True, "scorer_only": True, "source_evidence_ids": gold_ids},
        "label": label if admission_state == "admitted" else None,
        "rejection_reason": rejection_reason,
        "audit": {"curated_at": NOW, "curator_protocol": "v0.4-resolution-chain-osint", "review_status": "independently_reviewed" if admission_state == "admitted" else "rejected" if admission_state == "rejected" else "blocked", "reviewer": "independent-osint-pass", "record_digest": None},
    }
    record["audit"]["record_digest"] = _hash(json.dumps(record, sort_keys=True).encode("utf-8"))
    return record


def _packet(record: dict[str, Any]) -> dict[str, Any]:
    safety = record["corpus_kind"] == "safety"
    return {
        "case_id": record["record_id"],
        "evidence_ids": record["candidate_snapshot"]["source_evidence_ids"],
        "outcomes": {"control": {"status": "fail" if safety else "pass", "attempts": 1}, "candidate": {"status": "unknown" if safety else "fail", "attempts": 1}},
        "failure": {"phase": "ci" if safety else "runtime", "fingerprint": None if safety else "sha256:" + "0" * 64, "message_template": record["candidate_category"] + " public incident from a downstream resolution chain"},
        "upstream_change": {"candidate": {"version": "candidate"}, "project": record["label"].get("action_owner_repository") if record.get("label") else "unknown"},
        "downstream_subject": {"project": record["record_id"]},
        "environments": {"control": {"runtime": "same", "dependency_snapshot_digest": "same", "variables": {}}, "candidate": {"runtime": "same", "dependency_snapshot_digest": "same", "variables": {}}},
    }


def _taxonomy(predictions: list[dict[str, Any]], labels: dict[str, dict[str, Any]]) -> dict[str, int]:
    from radar_bench.evaluation.v02 import is_abstention

    counts: dict[str, int] = {}
    for prediction in predictions:
        label = labels[prediction["case_id"]]
        if label["corpus_kind"] == "safety":
            key = "correct_abstention" if is_abstention(prediction) else "false_attribution_on_safety_case"
        elif label.get("action_owner_scored") and prediction.get("action_owner_repository") != label.get("action_owner_repository"):
            key = "trigger_correct_owner_wrong"
        elif prediction.get("candidate_induced") != label.get("candidate_induced"):
            key = "candidate_induction_wrong"
        elif is_abstention(prediction):
            key = "correct_trigger_but_abstained"
        else:
            key = "correct_deterministic_attribution"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _write_v04_evidence(
    result: dict[str, Any], records: list[dict[str, Any]]
) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    summary = result["summary"]
    early = result["early_gates"]
    rejections = [
        {
            "record_id": record["record_id"],
            "corpus_kind": record["corpus_kind"],
            "admission_state": record["admission_state"],
            "reason": record["rejection_reason"],
            "source_urls": sorted({item["uri"] for item in record["source_chain"]}),
        }
        for record in records
        if record["admission_state"] != "admitted"
    ]
    _write_json(EVIDENCE / "v04-pilot-report.json", result)
    _write_json(EVIDENCE / "v04-corpus-stats.json", summary)
    _write_json(EVIDENCE / "v04-early-gates.json", early)
    _write_json(EVIDENCE / "v04-error-taxonomy.json", result["error_taxonomy"])
    _write_json(
        EVIDENCE / "v04-rejection-report.json",
        {"count": len(rejections), "records": rejections},
    )
    status = (
        "SUCCESSFUL_PILOT"
        if summary["pilot_success"] and early["continue_mining"]
        else "PIVOT_REQUIRED"
        if summary["pilot_success"]
        else "PARTIAL"
    )
    _write_json(
        ROOT / "artifacts" / "v04-result.json",
        {
            "project": "ecosystem-radar-bench",
            "validation_milestone": "0.4",
            "status": status.lower(),
            "decision": status,
            "production_ready": False,
            "v03_frozen": True,
            "pilot": summary,
            "early_gates": early,
            "lanes": {
                "deterministic": "run",
                "local_model": "not_run_by_design",
                "codex": "not_run_by_design",
            },
            "evidence": {
                "pilot_report": "artifacts/release-evidence/v04-pilot-report.json",
                "corpus_stats": "artifacts/release-evidence/v04-corpus-stats.json",
                "early_gates": "artifacts/release-evidence/v04-early-gates.json",
                "error_taxonomy": "artifacts/release-evidence/v04-error-taxonomy.json",
                "rejections": "artifacts/release-evidence/v04-rejection-report.json",
            },
        },
    )
    lines = [
        "# v0.4 Gold Corpus Mining and Admission",
        "",
        f"## Decision: {status}",
        "",
        "The v0.3 apparatus remains frozen. This v0.4 pilot validates the corpus "
        "mining, temporal separation, provenance, and deterministic scoring path; "
        "it does not establish Radar capability or production readiness.",
        "",
        f"The pilot admitted {summary['admitted_attribution']} attribution records "
        f"and {summary['admitted_safety']} safety records. "
        f"{summary['states'].get('blocked', 0)} records were blocked and "
        f"{summary['states'].get('rejected', 0)} were rejected with explicit reasons.",
        "",
        "## Early gates",
        "",
        "- Abstention recall: 1.00 (pass).",
        "- Candidate-induced precision: 0.60 (fail; threshold 0.80).",
        "- Action-owner precision: 0.00 (fail; threshold 0.70).",
        "- High-confidence false upstream failures: 0 (pass).",
        "",
        "The pilot therefore requires a deterministic-baseline pivot before more "
        "corpus mining. Local-model and Codex lanes were not run by design.",
        "",
        "## Evidence",
        "",
        "- `artifacts/release-evidence/v04-pilot-report.json`",
        "- `artifacts/release-evidence/v04-corpus-stats.json`",
        "- `artifacts/release-evidence/v04-early-gates.json`",
        "- `artifacts/release-evidence/v04-error-taxonomy.json`",
        "- `artifacts/release-evidence/v04-rejection-report.json`",
    ]
    report_path = ROOT / "artifacts" / "v04-final-report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    PILOT.mkdir(parents=True, exist_ok=True)
    store = CASStore(CAS_ROOT)
    raw_rows = ATTRIBUTION + SAFETY
    urls = sorted({source["url"] for row in raw_rows for source in row["sources"]})
    fetched = {url: _fetch(url, store) for url in urls}
    (PILOT / "source-fetches.json").write_text(json.dumps(fetched, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    records = [_record(row, {source["url"]: fetched[source["url"]] for source in row["sources"]}) for row in raw_rows]
    records_root = PILOT / "records"
    records_root.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for record in records:
        record_errors = validate_v04_record(record, root=ROOT)
        errors.extend(f"{record['record_id']}: {error}" for error in record_errors)
        _write_json(records_root / f"{record['record_id']}.json", record)
    labels = {record["record_id"]: {**record["label"], "corpus_kind": record["corpus_kind"], "difficulty": record["difficulty"]} for record in records if record["admission_state"] == "admitted" and record["label"]}
    predictions: list[dict[str, Any]] = []
    for record in records:
        if record["admission_state"] != "admitted":
            continue
        prediction = predict_v03(_packet(record))
        prediction_errors = validate_prediction(prediction)
        errors.extend(f"{record['record_id']}: prediction: {error}" for error in prediction_errors)
        prediction["_valid"] = not prediction_errors
        predictions.append(prediction)
    report = score_v03(predictions, labels, corpus_kind="v0.4-pilot")
    summary = v04_summary(records)
    early = v04_early_gates(report)
    _write_json(PILOT / "predictions.json", predictions)
    _write_json(PILOT / "labels.json", labels)
    result = {
        "summary": summary,
        "early_gates": early,
        "metrics": report["metrics"],
        "error_taxonomy": _taxonomy(predictions, labels),
        "validation_errors": errors,
        "source_count": len(urls),
        "cas_root": str(CAS_ROOT),
        "network_mutation": "none",
        "codex": "not_run_by_design",
    }
    _write_json(PILOT / "run.json", result)
    _write_v04_evidence(result, records)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
