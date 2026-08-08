from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from radar_bench.baseline.engine import predict
from radar_bench.errors import SecurityError, ValidationError
from radar_bench.github.urls import parse_github_url
from radar_bench.models.case import validate_case
from radar_bench.models.experiment import validate_experiment_plan
from radar_bench.normalize.base import normalize_text
from radar_bench.normalize.redaction import redact
from radar_bench.schema.loader import validate_json
from radar_bench.snapshots.builder import build_snapshot
from radar_bench.snapshots.leakage import scan_leakage
from radar_bench.storage.cas import CASStore

ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    def test_worked_case_is_valid(self):
        case = json.loads(
            (ROOT / "examples" / "regression-case-openblas.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(validate_case(case, root=ROOT), [])

    def test_invalid_prediction_rejected(self):
        with self.assertRaises(ValidationError):
            validate_json({"schema_version": "0.1"}, "prediction", ROOT)


class SnapshotTests(unittest.TestCase):
    def test_gold_is_not_in_input(self):
        case = json.loads(
            (ROOT / "examples" / "regression-case-openblas.json").read_text(
                encoding="utf-8"
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            result = build_snapshot(case, Path(directory), root=ROOT)
            packet = json.loads(
                (Path(directory) / "input" / "snapshot.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(result["gold_count"], 4)
            self.assertNotIn("E-OPENBLAS-FIX", json.dumps(packet))

    def test_future_evidence_leak_is_detected(self):
        case = json.loads(
            (ROOT / "examples" / "regression-case-openblas.json").read_text(
                encoding="utf-8"
            )
        )
        packet = {
            "evidence_ids": ["E-OPENBLAS-FIX"],
            "resolution": {
                "pull_request": "https://github.com/OpenMathLib/OpenBLAS/pull/4587"
            },
        }
        errors = scan_leakage(case, packet)
        self.assertTrue(errors)


class SecurityTests(unittest.TestCase):
    def test_common_secret_patterns_are_redacted(self):
        value = redact(
            "Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz123456 token=secret-value"
        )
        self.assertNotIn("ghp_", value)
        self.assertNotIn("secret-value", value)

    def test_github_ssrf_host_is_rejected(self):
        with self.assertRaises(SecurityError):
            parse_github_url("https://127.0.0.1/owner/repo/issues/1")

    def test_github_comment_and_commit_urls_are_canonical(self):
        self.assertEqual(
            parse_github_url("https://github.com/a/b/issues/4#issuecomment-9").kind,
            "issue_comment",
        )
        self.assertEqual(
            parse_github_url("https://github.com/a/b/commit/abc123").suffix, "abc123"
        )

    def test_cas_path_and_digest_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CASStore(Path(directory))
            digest = store.put_bytes(b"public evidence")
            self.assertEqual(store.read_bytes(digest), b"public evidence")
            with self.assertRaises(SecurityError):
                store.object_path("sha256:" + "0" * 63 + "!")

    def test_plan_rejects_shell_construction(self):
        plan = json.loads(
            (ROOT / "examples" / "experiment-plan-example.json").read_text(
                encoding="utf-8"
            )
        )
        plan["commands"] = [["python", "-c", "print('unsafe')"]]
        self.assertTrue(validate_experiment_plan(plan, root=ROOT))


class BaselineTests(unittest.TestCase):
    def test_unsupported_packet_abstains(self):
        packet = {
            "case_id": "RADAR-TEST-001",
            "evidence_ids": ["E-1"],
            "outcomes": {
                "control": {"status": "unknown", "attempts": 0},
                "candidate": {"status": "unknown", "attempts": 0},
            },
            "failure": {"phase": "unknown", "fingerprint": "sha256:" + "0" * 64},
            "upstream_change": {"candidate": {}},
        }
        prediction = predict(packet)
        self.assertEqual(prediction["verdict"], "inconclusive")
        self.assertEqual(prediction["confidence"], "inconclusive")


class NormalizationTests(unittest.TestCase):
    def test_noise_normalizes_stably(self):
        left = normalize_text(
            "2024-01-01T10:00:00Z File C:\\tmp\\a\\test.py:12:3 UUID 123e4567-e89b-12d3-a456-426614174000"
        )
        right = normalize_text(
            "2025-02-02T11:00:00Z File D:\\other\\b\\test.py:99:8 UUID 123e4567-e89b-12d3-a456-426614174000"
        )
        self.assertEqual(left.fingerprint, right.fingerprint)


if __name__ == "__main__":
    unittest.main()
