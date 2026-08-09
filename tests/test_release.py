from __future__ import annotations

import json
import unittest
from pathlib import Path

from radar_bench.cli import main
from radar_bench.release import evaluate_decisive_suite, validate_decisive_suite

ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    def test_decisive_suite_is_structurally_valid_and_opaque(self) -> None:
        audit = validate_decisive_suite(ROOT)
        self.assertTrue(audit["valid"], audit["errors"])
        self.assertEqual(len(audit["historical"]), 5)
        self.assertEqual(audit["safety"]["count"], 20)
        self.assertTrue(audit["opacity"]["valid"])
        self.assertTrue(audit["safety"]["evaluator_labels_outside_runtime"])

    def test_evaluate_fails_closed_on_noncanonical_runtime(self) -> None:
        result = evaluate_decisive_suite(ROOT)
        self.assertEqual(result["suite_id"], "decisive-v1")
        self.assertIn(result["status"], {"BLOCKED", "COMPLETED"})
        if result["status"] == "BLOCKED":
            self.assertEqual(result["certification"], "INCONCLUSIVE")
            self.assertEqual(result["cases"]["executed"], 0)
            self.assertFalse(result["reference"]["used_as_runtime_evidence"])

    def test_canonical_reference_preserves_decisive_negative(self) -> None:
        reference = json.loads(
            (ROOT / "artifacts" / "v1.0" / "canonical-results.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(reference["case_count"], 25)
        self.assertEqual(
            reference["baselines"]["agentic-v0.5-frozen"]["cross_repository_resolution"]["numerator"],
            0,
        )
        self.assertFalse(reference["mandatory_case_gates"]["scikit-learn-30512-resolves-to-scipy"])

    def test_cli_version_and_suite_validation(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(main(["validate", "--suite", "decisive-v1"]), 0)


if __name__ == "__main__":
    unittest.main()
