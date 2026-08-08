from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError

from radar_bench import cli
from radar_bench.baseline.rules import apply_rules
from radar_bench.config import cache_root, project_root, schema_root
from radar_bench.errors import ExternalBlocked, SecurityError, ValidationError
from radar_bench.evaluation.gates import evaluate_gates
from radar_bench.evaluation.reports import markdown_report
from radar_bench.evaluation.scoring import load_predictions, score
from radar_bench.github.client import GitHubClient, _next_link
from radar_bench.github.collector import collect_url
from radar_bench.github.temporal import classify_temporal
from radar_bench.github.urls import GitHubResource, api_url, parse_github_url
from radar_bench.models.case import parse_aware, validate_case
from radar_bench.models.experiment import (
    render_experiment_plan,
    validate_experiment_plan,
)
from radar_bench.models.prediction import make_prediction, validate_prediction
from radar_bench.normalize.fingerprint import fingerprint
from radar_bench.normalize.github_annotations import normalize_annotations
from radar_bench.normalize.junit import normalize_junit
from radar_bench.normalize.pytest_text import normalize_pytest
from radar_bench.normalize.redaction import redact
from radar_bench.providers.base import inference_packet
from radar_bench.providers.deterministic import DeterministicProvider
from radar_bench.providers.replay import ReplayProvider
from radar_bench.providers.subprocess_provider import SubprocessProvider
from radar_bench.runner.policy import validate_plan_policy
from radar_bench.schema.loader import load_schema
from radar_bench.schema.validator import (
    _format_ok,
    _resolve,
    _type_ok,
    assert_valid,
    validate,
)
from radar_bench.snapshots.cutoff import parse_cutoff, visible_before_cutoff
from radar_bench.snapshots.integrity import check_snapshot
from radar_bench.storage.index import EvidenceIndex
from radar_bench.storage.manifests import load_queue, mark_queue_item

ROOT = Path(__file__).resolve().parents[1]


def case() -> dict:
    return json.loads(
        (ROOT / "examples" / "regression-case-openblas.json").read_text(
            encoding="utf-8"
        )
    )


def packet(case_id="RADAR-TEST-001", control="unknown", candidate="unknown", text=""):
    return {
        "case_id": case_id,
        "evidence_ids": ["E-TEST"],
        "outcomes": {
            "control": {"status": control, "attempts": 1},
            "candidate": {"status": candidate, "attempts": 1},
        },
        "failure": {
            "phase": "test",
            "fingerprint": "sha256:" + "0" * 64,
            "message_template": text,
        },
        "upstream_change": {"candidate": {"version": "1"}, "project": "test"},
    }


class RulesAndModels(unittest.TestCase):
    def test_rule_families(self):
        for text, expected in [
            ("404 remote fixture", "external_service_or_data"),
            ("artifact missing", "packaging_or_artifact"),
            ("flaky worker crash", "flaky_or_nondeterministic"),
        ]:
            result = apply_rules(
                {
                    "text": text,
                    "control_status": "unknown",
                    "candidate_status": "unknown",
                    "fingerprint": None,
                    "evidence_ids": [],
                }
            )
            self.assertEqual(result[1], expected)
        result = apply_rules(
            {
                "text": "",
                "control_status": "fail",
                "candidate_status": "fail",
                "fingerprint": "x",
                "evidence_ids": [],
            }
        )
        self.assertEqual(result[0], "not_candidate_induced")
        result = apply_rules(
            {
                "text": "",
                "control_status": "fail",
                "candidate_status": "fail",
                "fingerprint": None,
                "evidence_ids": [],
            }
        )
        self.assertEqual(result[0], "inconclusive")
        result = apply_rules(
            {
                "text": "",
                "control_status": "pass",
                "candidate_status": "fail",
                "fingerprint": None,
                "evidence_ids": [],
            }
        )
        self.assertEqual(result[0], "confirmed_regression")

    def test_prediction_policy_and_plan_render(self):
        prediction = make_prediction(
            case_id="RADAR-TEST-001",
            verdict="inconclusive",
            candidate_induced=None,
            responsible_layer="unknown",
            confidence="inconclusive",
            rationale="abstain",
            evidence_ids=[],
            provider="deterministic",
            provider_version="0.1.0",
        )
        self.assertEqual(validate_prediction(prediction), [])
        invalid = dict(prediction)
        invalid["verdict"] = "bad"
        self.assertTrue(validate_prediction(invalid))
        plan = json.loads(
            (ROOT / "examples" / "experiment-plan-example.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(validate_experiment_plan(plan, root=ROOT), [])
        self.assertIn("DRY RUN", render_experiment_plan(plan))
        self.assertTrue(
            validate_plan_policy(
                {
                    "risk_classification": "unsafe",
                    "commands": [],
                    "environment_allowlist": [],
                    "expected_outputs": [],
                    "limits": {"network_policy": "unrestricted"},
                }
            )
        )

    def test_case_semantic_edges(self):
        value = case()
        value["lifecycle"]["updated_at"] = "2020-01-01T00:00:00Z"
        self.assertTrue(validate_case(value, root=ROOT))
        with self.assertRaises(ValidationError):
            parse_aware("2024-01-01", "x")
        value = case()
        value["evidence"].append(dict(value["evidence"][0]))
        self.assertTrue(validate_case(value, root=ROOT))
        value = case()
        value["evidence"][0]["available_before_cutoff"] = True
        value["evidence"][0]["collected_at"] = "2030-01-01T00:00:00Z"
        self.assertTrue(validate_case(value, root=ROOT))
        value = case()
        value["lifecycle"]["state"] = "retracted"
        self.assertTrue(validate_case(value, root=ROOT))


class EvaluationAndStorage(unittest.TestCase):
    def test_metrics_gates_and_reports(self):
        labels = {
            "RADAR-TEST-001": {
                "candidate_induced": True,
                "responsible_layer": "upstream_runtime_or_library",
            },
            "RADAR-TEST-002": {
                "candidate_induced": False,
                "responsible_layer": "unknown",
            },
        }
        predictions = [
            make_prediction(
                case_id="RADAR-TEST-001",
                verdict="confirmed_regression",
                candidate_induced=True,
                responsible_layer="upstream_runtime_or_library",
                confidence="medium",
                rationale="r",
                evidence_ids=["E-1"],
                provider="deterministic",
                provider_version="0.1.0",
            ),
            make_prediction(
                case_id="RADAR-TEST-002",
                verdict="inconclusive",
                candidate_induced=None,
                responsible_layer="unknown",
                confidence="inconclusive",
                rationale="r",
                evidence_ids=[],
                provider="deterministic",
                provider_version="0.1.0",
            ),
        ]
        for value in predictions:
            value["_valid"] = True
        result = score(predictions, labels)
        self.assertEqual(result["metrics"]["candidate_induced_precision"]["value"], 1.0)
        self.assertIn("Metric", markdown_report(result))
        gates = evaluate_gates(result)
        self.assertIn("candidate_induced_regression_precision", gates["gates"])

    def test_scoring_loads_invalid_jsonl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.jsonl"
            path.write_text("not-json\n", encoding="utf-8")
            values = load_predictions(path)
            self.assertFalse(values[0]["_valid"])

    def test_index_and_queue_are_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = EvidenceIndex(root / "index.sqlite3")
            index.upsert(
                source_uri="https://github.com/a/b/issues/1",
                canonical_identity="github:a/b:issue/1",
                retrieved_at="2024-01-01T00:00:00Z",
                http_status=200,
                etag=None,
                last_modified=None,
                digest=None,
                media_type="application/json",
                cutoff_relation="pre",
                visibility="public",
                parser_version="0.1",
                error_state=None,
                retry_count=0,
            )
            self.assertEqual(
                index.get("https://github.com/a/b/issues/1")["http_status"], 200
            )
            index.close()
            queue = root / "queue.json"
            mark_queue_item(queue, "x", status="blocked", detail="offline")
            self.assertEqual(load_queue(queue)["items"]["x"]["status"], "blocked")


class GithubAndNormalization(unittest.TestCase):
    def test_url_variants_and_temporal_edges(self):
        self.assertEqual(
            api_url(GitHubResource("a", "b", "release", suffix="v1")),
            "https://api.github.com/repos/a/b/releases/tags/v1",
        )
        self.assertEqual(
            api_url(GitHubResource("a", "b", "commit", suffix="abc")),
            "https://api.github.com/repos/a/b/commits/abc",
        )
        self.assertEqual(
            api_url(parse_github_url("https://github.com/a/b/releases/tag/v1")),
            "https://api.github.com/repos/a/b/releases/tags/v1",
        )
        self.assertEqual(
            parse_github_url("https://github.com/a/b/tree/main").kind, "tag"
        )
        self.assertEqual(
            parse_github_url("https://github.com/a/b/actions/runs/4").kind,
            "workflow_run",
        )
        self.assertEqual(
            parse_github_url("https://github.com/a/b/pull/4#discussion_r9").kind,
            "review_comment",
        )
        with self.assertRaises(SecurityError):
            parse_github_url("http://github.com/a/b/issues/1")
        self.assertEqual(
            _next_link('<https://api.github.com/?page=2>; rel="next"'),
            "https://api.github.com/?page=2",
        )
        cutoff = datetime(2024, 1, 1, tzinfo=UTC)
        self.assertEqual(
            classify_temporal({"created_at": "2025-01-01T00:00:00Z"}, cutoff)[0],
            "post-cutoff",
        )
        self.assertEqual(classify_temporal({}, cutoff)[0], "unknown")
        self.assertEqual(
            classify_temporal(
                {
                    "created_at": "2023-01-01T00:00:00Z",
                    "updated_at": "2025-01-02T00:00:00Z",
                },
                cutoff,
            )[0],
            "temporally-unverifiable",
        )
        self.assertEqual(
            classify_temporal(
                {
                    "created_at": "2023-01-01T00:00:00Z",
                    "updated_at": "2023-01-02T00:00:00Z",
                },
                cutoff,
            )[0],
            "pre-cutoff",
        )

    def test_fake_client_pages_and_collection(self):
        class Fake(GitHubClient):
            def __init__(self):
                super().__init__(retries=0)
                self.calls = 0

            def get_json(self, url):
                self.calls += 1
                return (
                    200,
                    {"id": self.calls},
                    {
                        "link": '<https://api.github.com/repos/a/b/issues/1?page=2>; rel="next"'
                    }
                    if self.calls == 1
                    else {},
                )

        fake = Fake()
        self.assertEqual(
            len(fake.get_pages("https://api.github.com/repos/a/b/issues/1")), 2
        )
        with tempfile.TemporaryDirectory() as directory:
            result = collect_url(
                "https://github.com/a/b/issues/1",
                Path(directory),
                "2024-01-01T00:00:00Z",
                client=fake,
            )
            self.assertTrue(result["digest"])

    def test_client_success_and_url_checks(self):
        class Response:
            def __init__(self):
                self.status = 200
                self.headers = {"ETag": "etag"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                return b'{"ok": true}'

        class Opener:
            def open(self, request, timeout):
                return Response()

        client = GitHubClient(retries=0)
        client.opener = Opener()
        status, payload, headers = client.get_json("https://api.github.com/repos/a/b")
        self.assertEqual((status, payload["ok"], headers["etag"]), (200, True, "etag"))
        with self.assertRaises(SecurityError):
            client.get_json("https://example.com/")

    def test_normalizer_adapters(self):
        self.assertEqual(
            normalize_pytest("FAILED test_a.py::test_x").source_format, "pytest"
        )
        self.assertEqual(
            normalize_junit(
                "<testsuite><testcase classname='a' name='b'><failure message='bad'>Error</failure></testcase></testsuite>"
            ).source_format,
            "junit",
        )
        self.assertEqual(
            normalize_annotations(
                {"annotations": [{"message": "bad", "path": "x.py"}]}
            ).source_format,
            "github",
        )
        self.assertTrue(fingerprint("Failure: x").startswith("sha256:"))
        self.assertIn("REDACTED", redact("secret=abc"))


class ProvidersAndCli(unittest.TestCase):
    def test_providers_and_inference_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input").mkdir()
            (root / "gold").mkdir()
            packet_value = globals()["packet"](case_id="RADAR-TEST-001")
            (root / "input" / "snapshot.json").write_text(
                json.dumps(packet_value), encoding="utf-8"
            )
            (root / "gold" / "label.json").write_text("{}", encoding="utf-8")
            self.assertEqual(inference_packet(root)["case_id"], "RADAR-TEST-001")
            with self.assertRaises(ValueError):
                inference_packet(root / "gold")
            self.assertEqual(
                DeterministicProvider().predict(packet_value)["case_id"],
                "RADAR-TEST-001",
            )
            replay_path = root / "predictions.jsonl"
            replay_path.write_text(
                json.dumps(
                    make_prediction(
                        case_id="RADAR-TEST-001",
                        verdict="inconclusive",
                        candidate_induced=None,
                        responsible_layer="unknown",
                        confidence="inconclusive",
                        rationale="r",
                        evidence_ids=[],
                        provider="imported",
                        provider_version="0.1",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                ReplayProvider(replay_path).predict(packet_value)["case_id"],
                "RADAR-TEST-001",
            )
            result = SubprocessProvider([sys.executable, "-m", "json.tool"]).predict(
                packet_value
            )
            self.assertEqual(result["case_id"], "RADAR-TEST-001")

    def test_cli_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            prediction_path = Path(directory) / "predictions.jsonl"
            prediction_path.write_text(
                json.dumps(
                    make_prediction(
                        case_id="RADAR-OSINT-004",
                        verdict="inconclusive",
                        candidate_induced=None,
                        responsible_layer="unknown",
                        confidence="inconclusive",
                        rationale="r",
                        evidence_ids=[],
                        provider="imported",
                        provider_version="0.1",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            gate_path = Path(directory) / "gates.json"
            gate_path.write_text(json.dumps({"metrics": {}}), encoding="utf-8")
            self.assertEqual(cli.main(["doctor"]), 0)
            self.assertEqual(
                cli.main(
                    [
                        "validate-case",
                        str(ROOT / "examples" / "regression-case-openblas.json"),
                        "--json",
                    ]
                ),
                0,
            )
            self.assertEqual(cli.main(["normalize-failure", "failure text"]), 0)
            self.assertEqual(
                cli.main(
                    [
                        "baseline",
                        str(ROOT / "corpus" / "snapshots" / "RADAR-OSINT-004"),
                        "--json",
                    ]
                ),
                0,
            )
            self.assertEqual(cli.main(["import-predictions", str(prediction_path)]), 0)
            self.assertEqual(cli.main(["evaluate", str(prediction_path)]), 0)
            self.assertEqual(cli.main(["gates", str(gate_path), "--json"]), 0)
            self.assertEqual(
                cli.main(
                    [
                        "plan",
                        "validate",
                        str(ROOT / "examples" / "experiment-plan-example.json"),
                    ]
                ),
                0,
            )
            self.assertEqual(
                cli.main(
                    [
                        "plan",
                        "render",
                        str(ROOT / "examples" / "experiment-plan-example.json"),
                    ]
                ),
                0,
            )
            self.assertEqual(cli.main(["validate-corpus", "--json"]), 0)
            self.assertEqual(cli.main(["build-snapshot", "RADAR-OSINT-004"]), 0)
            self.assertEqual(
                cli.main(["check-leakage", "RADAR-OSINT-004", "--json"]), 0
            )
            exported = Path(directory) / "packet.json"
            self.assertEqual(
                cli.main(
                    ["export-inference", "RADAR-OSINT-004", "--output", str(exported)]
                ),
                0,
            )
            self.assertEqual(
                cli.main(
                    [
                        "ablation",
                        str(prediction_path),
                        str(prediction_path),
                        str(prediction_path),
                    ]
                ),
                0,
            )
            self.assertEqual(
                cli.main(
                    [
                        "collect",
                        "--issue",
                        "not-a-url",
                        "--cutoff",
                        "2024-01-01T00:00:00Z",
                        "--output",
                        str(Path(directory) / "cache"),
                    ]
                ),
                2,
            )


class BranchCoverage(unittest.TestCase):
    def test_config_cutoff_integrity_and_schema_helpers(self):
        self.assertTrue(project_root().exists())
        self.assertTrue(schema_root(ROOT).exists())
        self.assertTrue(cache_root(ROOT))
        self.assertEqual(parse_cutoff("2024-01-01T00:00:00Z").tzinfo, UTC)
        with self.assertRaises(ValueError):
            parse_cutoff("2024-01-01T00:00:00")
        evidence = {
            "available_before_cutoff": True,
            "collected_at": "2023-01-01T00:00:00Z",
        }
        self.assertTrue(
            visible_before_cutoff(evidence, parse_cutoff("2024-01-01T00:00:00Z"))[0]
        )
        self.assertFalse(
            visible_before_cutoff(
                {
                    "available_before_cutoff": False,
                    "collected_at": "2023-01-01T00:00:00Z",
                },
                parse_cutoff("2024-01-01T00:00:00Z"),
            )[0]
        )
        self.assertFalse(
            visible_before_cutoff(
                {"available_before_cutoff": True}, parse_cutoff("2024-01-01T00:00:00Z")
            )[0]
        )
        self.assertFalse(
            visible_before_cutoff(
                {"available_before_cutoff": True, "collected_at": "bad"},
                parse_cutoff("2024-01-01T00:00:00Z"),
            )[0]
        )
        self.assertFalse(
            visible_before_cutoff(
                {
                    "available_before_cutoff": True,
                    "collected_at": "2024-01-01T00:00:00",
                },
                parse_cutoff("2024-01-01T00:00:00Z"),
            )[0]
        )
        self.assertFalse(
            visible_before_cutoff(
                {
                    "available_before_cutoff": True,
                    "collected_at": "2023-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z",
                },
                parse_cutoff("2024-01-01T00:00:00Z"),
            )[0]
        )
        self.assertFalse(
            visible_before_cutoff(
                {
                    "available_before_cutoff": True,
                    "collected_at": "2023-01-01T00:00:00Z",
                    "updated_at": "bad",
                },
                parse_cutoff("2024-01-01T00:00:00Z"),
            )[0]
        )
        self.assertEqual(load_schema("case")["title"], "RegressionCase v0.1")
        with self.assertRaises(ValueError):
            load_schema("missing")
        with self.assertRaises(ValidationError):
            assert_valid({}, {"type": "object", "required": ["x"]})
        self.assertTrue(
            validate({}, {"oneOf": [{"type": "string"}, {"type": "integer"}]})
        )

    def test_integrity_and_cas_edges(self):
        from radar_bench.snapshots.builder import build_snapshot
        from radar_bench.storage.cas import CASStore

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            build_snapshot(case(), root, root=ROOT)
            self.assertEqual(
                check_snapshot(
                    ROOT / "examples" / "regression-case-openblas.json", root
                ),
                [],
            )
            store = CASStore(root, max_bytes=2)
            digest = store.put_bytes(b"a")
            self.assertEqual(store.put_bytes(b"a"), digest)
            with self.assertRaises(SecurityError):
                store.put_bytes(b"abc")
            with self.assertRaises(SecurityError):
                store.object_path("bad")
        with self.assertRaises(SecurityError):
            SubprocessProvider([])

    def test_schema_validator_branches(self):
        self.assertTrue(
            all(
                _type_ok(value, kind)
                for value, kind in [
                    ({}, "object"),
                    ([], "array"),
                    ("x", "string"),
                    (1, "integer"),
                    (1.0, "number"),
                    (True, "boolean"),
                    (None, "null"),
                ]
            )
        )
        self.assertFalse(_type_ok(True, "integer"))
        self.assertTrue(_type_ok("x", "unknown"))
        self.assertTrue(_format_ok("2024-01-01T00:00:00Z", "date-time"))
        self.assertFalse(_format_ok("bad", "date-time"))
        self.assertTrue(_format_ok("https://example.com", "uri"))
        self.assertFalse(_format_ok("bad", "uri"))
        self.assertTrue(_format_ok("x", "other"))
        with self.assertRaises(ValueError):
            _resolve("https://external.invalid/schema", {})
        with self.assertRaises(TypeError):
            _resolve("#/x", {"x": 1})
        schema = {
            "type": "object",
            "required": ["x"],
            "additionalProperties": False,
            "properties": {
                "x": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 3,
                    "pattern": "[a-z]+",
                    "format": "uri",
                }
            },
        }
        self.assertTrue(validate({}, schema))
        self.assertTrue(validate({"x": "x", "extra": 1}, schema))
        self.assertTrue(validate({"x": "https://a"}, schema))
        self.assertTrue(
            validate(
                [],
                {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "integer"},
                },
            )
        )
        self.assertTrue(
            validate(
                [1, 1],
                {"type": "array", "uniqueItems": True, "items": {"type": "integer"}},
            )
        )
        self.assertTrue(
            validate(
                {"x": 1, "y": "bad"},
                {
                    "type": "object",
                    "maxProperties": 1,
                    "additionalProperties": {"type": "integer"},
                },
            )
        )
        self.assertTrue(validate("abcd", {"type": "string", "maxLength": 3}))
        self.assertTrue(validate(0, {"type": "number", "minimum": 1, "maximum": -1}))
        self.assertTrue(validate("x", {"const": "y", "enum": ["z"]}))

    def test_case_prediction_and_cutoff_policy_errors(self):
        value = case()
        value["evidence"].append(dict(value["evidence"][0]))
        value["evidence"][1]["evidence_id"] = value["evidence"][0]["evidence_id"]
        self.assertTrue(validate_case(value, root=ROOT))
        value = case()
        value["experiments"][0]["evidence_ids"] = ["E-MISSING"]
        self.assertTrue(validate_case(value, root=ROOT))
        value = case()
        value["experiments"][1]["experiment_id"] = value["experiments"][0][
            "experiment_id"
        ]
        self.assertTrue(validate_case(value, root=ROOT))
        value = case()
        value["evidence"][0]["available_before_cutoff"] = True
        value["evidence"][0]["collected_at"] = "2030-01-01T00:00:00Z"
        self.assertTrue(validate_case(value, root=ROOT, strict=True))
        prediction = make_prediction(
            case_id="RADAR-TEST",
            verdict="confirmed_regression",
            candidate_induced=True,
            responsible_layer="unknown",
            confidence="high",
            rationale="confident",
            evidence_ids=["E-1"],
            provider="codex",
            provider_version="0.1",
        )
        self.assertTrue(
            validate_prediction(prediction, {"E-1": {"available_before_cutoff": False}})
        )
        self.assertTrue(validate_prediction(prediction))

    def test_github_client_failures_and_cas_digest(self):
        class FailingOpener:
            def __init__(self, error):
                self.error = error

            def open(self, request, timeout):
                raise self.error

        client = GitHubClient(retries=0)
        client.opener = FailingOpener(URLError("offline"))
        with self.assertRaises(ExternalBlocked):
            client.get_json("https://api.github.com/repos/a/b")
        client = GitHubClient(retries=0)
        client.opener = FailingOpener(
            HTTPError("https://api.github.com", 404, "no", {}, None)
        )
        with self.assertRaises(ExternalBlocked):
            client.get_json("https://api.github.com/repos/a/b")
        from radar_bench.storage.cas import CASStore

        with tempfile.TemporaryDirectory() as directory:
            store = CASStore(Path(directory))
            digest = store.put_bytes(b"payload")
            path = store.object_path(digest)
            path.write_bytes(b"tampered")
            with self.assertRaises(SecurityError):
                store.read_bytes(digest)


if __name__ == "__main__":
    unittest.main()
