import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "scripts"))

from collect_metrics import collect
from compare_evaluations import compare, wilson_interval
from run_evaluation import scripted_events, validate_event_log, write_jsonl
from scenario_tools import canonical_hash, materialize_scenario
from validate_golden_set import validate


class ScenarioToolTests(unittest.TestCase):
    def test_same_seed_produces_same_scene_hash(self) -> None:
        manifest = json.loads((ROOT / "sim" / "scenarios" / "frozen" / "normal-001.json").read_text())
        first = materialize_scenario(manifest)
        second = materialize_scenario(manifest)
        self.assertEqual(first, second)
        self.assertEqual(canonical_hash(first), canonical_hash(second))

    def test_golden_set_counts_and_fail_closed_policy(self) -> None:
        payload = json.loads((ROOT / "evaluation" / "golden-set-v0.1.json").read_text(encoding="utf-8"))
        self.assertEqual(validate(payload), [])


class EvaluationPipelineTests(unittest.TestCase):
    def test_scripted_log_has_metadata_sequence_and_verification_evidence(self) -> None:
        manifest = json.loads(
            (ROOT / "sim" / "scenarios" / "frozen" / "occlusion-001.json").read_text(encoding="utf-8")
        )
        events = scripted_events("v-test", manifest, "abc123", 1000)
        self.assertEqual([event["sequence_no"] for event in events], list(range(len(events))))
        self.assertTrue(all(event["evaluation"]["seed"] == 1104 for event in events))
        verification = [event for event in events if event["event_type"] == "verification"][-1]
        self.assertEqual(verification["payload"]["status"], "insufficient_evidence")
        self.assertTrue(verification["payload"]["evidence_refs"])

    def test_metrics_keep_unaudited_false_completion_unknown(self) -> None:
        manifest = json.loads((ROOT / "sim" / "scenarios" / "frozen" / "normal-001.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            version_dir = root / "v-test"
            version_dir.mkdir()
            events = scripted_events("v-test", manifest, "abc123", 1000)
            log_path = version_dir / "normal-001.jsonl"
            write_jsonl(log_path, events)
            validate_event_log(log_path, "v-test--normal-001")
            (root / "summary.json").write_text(
                json.dumps({"runner": "scripted", "release_eligible": False}),
                encoding="utf-8",
            )
            metrics = collect(version_dir)
        self.assertIsNone(metrics["false_completion_count"])
        self.assertFalse(metrics["release_eligible"])
        self.assertEqual(metrics["evidence_coverage"], 1.0)

    def test_statistical_report_marks_identical_versions_not_significant(self) -> None:
        metrics = [
            {"run_count": 30, "vtcr": 0.8},
            {"run_count": 30, "vtcr": 0.8},
            {"run_count": 30, "vtcr": 0.8},
        ]
        report = compare(metrics, ["A", "B", "C"])
        self.assertTrue(all(not item["statistically_significant"] for item in report["pairwise"]))
        lower, upper = wilson_interval(24, 30)
        self.assertLess(lower, 0.8)
        self.assertGreater(upper, 0.8)


if __name__ == "__main__":
    unittest.main()
