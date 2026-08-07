import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "scripts"))

from collect_metrics import collect
from compare_evaluations import compare, wilson_interval
from run_evaluation import (
    EvaluationInputError,
    load_scenario_manifests,
    scripted_events,
    validate_event_log,
    validate_label,
    write_jsonl,
)
from scenario_tools import canonical_hash, materialize_scenario
from validate_golden_set import validate, validate_diverse


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
        diverse = json.loads((ROOT / "evaluation" / "golden-set-v0.2.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_diverse(diverse), [])


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
        self.assertEqual(
            verification["payload"]["evaluated_conditions"],
            verification["payload"]["required_conditions"],
        )
        self.assertNotEqual(
            verification["payload"]["satisfied_conditions"],
            verification["payload"]["required_conditions"],
        )

    def test_multi_object_scenario_generates_three_entity_task_evidence(self) -> None:
        manifest = json.loads(
            (ROOT / "sim" / "scenarios" / "expanded" / "multi-object-003.json").read_text(encoding="utf-8")
        )
        events = scripted_events("v-test", manifest, "abc123", 1000)
        observations = [event for event in events if event["event_type"] == "observation"]
        self.assertEqual(
            {event["payload"]["entity_id"] for event in observations},
            {"red_block", "blue_cylinder", "green_gear"},
        )
        final = [event for event in events if event["event_type"] == "verification"][-1]
        self.assertEqual(final["payload"]["task_id"], "task-kit-three-parts")
        self.assertEqual(len(final["payload"]["required_conditions"]), 4)

    def test_metrics_keep_unaudited_false_completion_unknown(self) -> None:
        manifest = json.loads(
            (ROOT / "sim" / "scenarios" / "frozen" / "occlusion-001.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            version_dir = root / "v-test"
            version_dir.mkdir()
            events = scripted_events("v-test", manifest, "abc123", 1000)
            log_path = version_dir / "occlusion-001.jsonl"
            write_jsonl(log_path, events)
            validate_event_log(log_path, "v-test--occlusion-001")
            (root / "summary.json").write_text(
                json.dumps({"runner": "scripted", "release_eligible": False}),
                encoding="utf-8",
            )
            metrics = collect(version_dir)
        self.assertIsNone(metrics["false_completion_count"])
        self.assertFalse(metrics["release_eligible"])
        self.assertEqual(metrics["evidence_coverage"], 1.0)
        self.assertEqual(metrics["task_family_count"], 1)
        self.assertEqual(metrics["complex_task_rate"], 0.0)
        self.assertEqual(metrics["goal_condition_coverage"], 1.0)

    def test_metrics_expose_task_diversity_and_multi_entity_complexity(self) -> None:
        manifests = [
            json.loads((ROOT / "sim" / "scenarios" / "frozen" / "normal-001.json").read_text(encoding="utf-8")),
            json.loads((ROOT / "sim" / "scenarios" / "expanded" / "multi-object-003.json").read_text(encoding="utf-8")),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            version_dir = root / "v-test"
            version_dir.mkdir()
            for manifest in manifests:
                write_jsonl(
                    version_dir / f"{manifest['scenario_id']}.jsonl",
                    scripted_events("v-test", manifest, "abc123", 1000),
                )
            (root / "summary.json").write_text(
                json.dumps({"runner": "scripted", "release_eligible": False}),
                encoding="utf-8",
            )
            metrics = collect(version_dir)
        self.assertEqual(metrics["task_family_count"], 2)
        self.assertEqual(metrics["complex_task_rate"], 0.5)
        self.assertEqual(metrics["mean_observed_entities"], 2.0)
        self.assertEqual(metrics["task_family_distribution"]["task-kit-three-parts"], 1)

    def test_duplicate_or_unsafe_run_inputs_are_rejected_before_execution(self) -> None:
        manifest = json.loads((ROOT / "sim" / "scenarios" / "frozen" / "normal-001.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.json"
            second = root / "second.json"
            first.write_text(json.dumps(manifest), encoding="utf-8")
            second.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(EvaluationInputError, "duplicate scenario_id"):
                load_scenario_manifests([first, second])
        with self.assertRaisesRegex(EvaluationInputError, "filesystem-safe"):
            validate_label("../outside", "version")

    def test_event_log_rejects_bad_json_missing_verification_and_boolean_sequence(self) -> None:
        manifest = json.loads((ROOT / "sim" / "scenarios" / "frozen" / "normal-001.json").read_text(encoding="utf-8"))
        events = scripted_events("v-test", manifest, "abc123", 1000)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            path.write_text("{bad-json}\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unreadable JSONL"):
                validate_event_log(path, "v-test--normal-001")

            without_verification = [event for event in events if event["event_type"] != "verification"]
            for index, event in enumerate(without_verification):
                event["sequence_no"] = index
            write_jsonl(path, without_verification)
            with self.assertRaisesRegex(RuntimeError, "no verification"):
                validate_event_log(path, "v-test--normal-001")

            events[0]["sequence_no"] = False
            write_jsonl(path, events)
            with self.assertRaisesRegex(RuntimeError, "non-contiguous"):
                validate_event_log(path, "v-test--normal-001")

            for index, event in enumerate(events):
                event["sequence_no"] = index
            events[0]["event_type"] = []
            write_jsonl(path, events)
            with self.assertRaisesRegex(RuntimeError, "unknown event_type"):
                validate_event_log(path, "v-test--normal-001")

    def test_event_metadata_must_match_the_requested_scenario(self) -> None:
        manifest = json.loads((ROOT / "sim" / "scenarios" / "frozen" / "normal-001.json").read_text(encoding="utf-8"))
        events = scripted_events("v-test", manifest, "abc123", 1000)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            write_jsonl(path, events)
            with self.assertRaisesRegex(RuntimeError, "seed drift"):
                validate_event_log(
                    path,
                    "v-test--normal-001",
                    scenario_id="normal-001",
                    seed=999,
                    commit="abc123",
                )

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
