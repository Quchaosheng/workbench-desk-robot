import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "scripts"))

from collect_metrics import collect
from compare_evaluations import compare, wilson_interval
from generate_report import release_reasons
from run_evaluation import (
    EvaluationInputError,
    load_scenario_manifests,
    scripted_events,
    validate_event_log,
    validate_label,
    write_jsonl,
)
from scenario_tools import canonical_hash, materialize_scenario
from validate_golden_set import validate, validate_diverse, validate_parcels


def canonical_metric_events(
    run_id: str,
    *,
    task_id: str,
    entity_ids: tuple[str, ...],
    status: str = "confirmed",
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []

    def append(event_type: str, payload: dict[str, object], evidence_refs: list[str] | None = None) -> None:
        sequence_no = len(events)
        events.append(
            {
                "event_id": f"{run_id}-evt-{sequence_no:03d}",
                "run_id": run_id,
                "sequence_no": sequence_no,
                "event_type": event_type,
                "occurred_at": f"2026-08-30T00:00:{sequence_no:02d}Z",
                "payload": payload,
                "evidence_refs": evidence_refs or [],
            }
        )

    append("task_accepted", {"task_id": task_id})
    evidence_refs = []
    for index, entity_id in enumerate(entity_ids):
        evidence_ref = f"frame://{run_id}/{entity_id}"
        evidence_refs.append(evidence_ref)
        append(
            "observation",
            {
                "observation_id": f"{run_id}-obs-{index:03d}",
                "run_id": run_id,
                "entity_id": entity_id,
                "entity_type": "fixture",
                "location": "on:table",
                "confidence": 0.9 - index * 0.1,
            },
            [evidence_ref],
        )
    append(
        "verification",
        {
            "status": status,
            "required_conditions": ["known-entities-observed"],
            "evaluated_conditions": ["known-entities-observed"],
            "evidence_refs": evidence_refs,
        },
        evidence_refs,
    )
    return events


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
        parcels = json.loads((ROOT / "evaluation" / "golden-set-parcel-v0.1.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_parcels(parcels), [])


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

    def test_parcel_scenario_carries_per_entity_attributes_and_routes(self) -> None:
        manifest = json.loads(
            (ROOT / "sim" / "scenarios" / "expanded" / "parcel-intake-003.json").read_text(encoding="utf-8")
        )
        scene = materialize_scenario(manifest)
        self.assertEqual(scene["task_id"], "task-sort-parcels")
        self.assertEqual(len(scene["objects"]), 3)
        self.assertEqual(
            next(item for item in scene["objects"] if item["entity_id"] == "parcel_damaged")["attributes"],
            {"label_status": "verified", "condition": "damaged", "barcode": "WBX-DMG-20260807"},
        )
        self.assertEqual(
            next(item for item in scene["objects"] if item["entity_id"] == "parcel_unreadable")["attributes"],
            {"label_status": "unreadable", "condition": "intact", "parcel_uid": "WBX-UNK-20260807"},
        )
        events = scripted_events("v-test", manifest, "abc123", 1000)
        observations = [event for event in events if event["event_type"] == "observation"]
        observe_requests = [event for event in events if event["event_type"] == "action_request"]
        graph = next(event for event in events if event["event_type"] == "task_graph")["payload"]
        self.assertEqual(graph["planner"], "parcel-policy-v3")
        self.assertTrue(graph["observation_barrier"])
        self.assertTrue(graph["manipulation_serial"])
        self.assertEqual(graph["routing_policy"], "manifest_matched_verified_intact_only")
        self.assertEqual(graph["policy_version"], "parcel-routing-v3")
        self.assertEqual(graph["manifest_id"], "WB-INBOUND-20260807-003")
        self.assertEqual(set(graph["manifest_statuses"].values()), {"matched"})
        self.assertEqual(graph["destination_capacities"], {"pickup_shelf": 4, "quarantine_bin": 4})
        self.assertEqual(graph["destination_occupancy"], {"pickup_shelf": 0, "quarantine_bin": 0})
        self.assertEqual(
            graph["routing_priorities"],
            {
                "parcel_box": "standard",
                "parcel_unreadable": "label_exception",
                "parcel_damaged": "condition_exception",
            },
        )
        self.assertEqual(
            graph["actions"][0:3],
            [
                "observe:parcel_box",
                "observe:parcel_unreadable",
                "observe:parcel_damaged",
            ],
        )
        self.assertEqual(graph["actions"][3], "grasp:parcel_damaged")
        self.assertTrue(all(event["payload"]["attributes"] for event in observations))
        self.assertTrue(
            all(
                event["payload"]["attributes"] == ["label_status", "condition", "tracking_id", "barcode", "parcel_uid"]
                for event in observe_requests[:3]
            )
        )
        parcel_place_request = next(
            event
            for event in observe_requests
            if event["payload"].get("action_type") == "place" and event["payload"].get("target_id") == "parcel_damaged"
        )
        self.assertEqual(parcel_place_request["payload"]["identity_guard"], "unique_across_supported_fields")
        self.assertEqual(parcel_place_request["payload"]["manifest_guard"], "matched")
        self.assertEqual(parcel_place_request["payload"]["manifest_id"], "WB-INBOUND-20260807-003")
        self.assertEqual(parcel_place_request["payload"]["routing_priority"], "condition_exception")
        self.assertEqual(parcel_place_request["payload"]["destination_remaining_after"], 3)
        destinations = {
            event["payload"]["resulting_location"]
            for event in events
            if event["event_type"] == "action_result" and event["payload"].get("resulting_location")
        }
        self.assertEqual(destinations, {"in:pickup_shelf", "in:quarantine_bin"})

    def test_metrics_keep_unaudited_false_completion_unknown(self) -> None:
        manifest = json.loads(
            (ROOT / "sim" / "scenarios" / "frozen" / "occlusion-001.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            version_dir = root / "v-test"
            version_dir.mkdir()
            events = canonical_metric_events(
                "v-test--occlusion-001",
                task_id=manifest["task_id"],
                entity_ids=("red_block",),
                status="insufficient_evidence",
            )
            log_path = version_dir / "occlusion-001.jsonl"
            write_jsonl(log_path, events)
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
                    canonical_metric_events(
                        f"v-test--{manifest['scenario_id']}",
                        task_id=manifest["task_id"],
                        entity_ids=(
                            ("red_block",)
                            if manifest["scenario_id"] == "normal-001"
                            else ("red_block", "blue_cylinder", "green_gear")
                        ),
                    ),
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

    def test_evaluation_manifest_adapter_accepts_reviewed_extension_only(self) -> None:
        expanded = ROOT / "sim" / "scenarios" / "expanded" / "multi-object-003.json"
        loaded = load_scenario_manifests([expanded])
        self.assertEqual(loaded[0][1]["scene_variant"], "multi_object")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "unknown-extension.json"
            payload = dict(loaded[0][1])
            payload["unreviewed_extension"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(EvaluationInputError, "unknown simulation manifest fields"):
                load_scenario_manifests([path])

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

    def test_release_report_requires_all_five_task_families(self) -> None:
        metrics = {
            "release_eligible": True,
            "false_completion_count": 0,
            "collision_count": 0,
            "policy_violation_count": 0,
            "vtcr": 0.8,
            "task_duration_p95_s": 119,
            "evidence_coverage": 1.0,
            "recovery_rate": 0.7,
            "state_hash_consistency": 1.0,
            "replay_success_rate": 0.95,
            "task_family_count": 4,
            "complex_task_rate": 0.5,
            "mean_observed_entities": 2.0,
            "goal_condition_coverage": 1.0,
        }
        self.assertIn("评测任务族少于 5 类", release_reasons(metrics))
        metrics["task_family_count"] = 5
        self.assertEqual(release_reasons(metrics), [])

        published_thresholds = {
            "recovery_rate": (0.0, "恢复率缺失或低于 70%"),
            "state_hash_consistency": (0.0, "state hash 一致性不是 100%"),
            "replay_success_rate": (0.0, "回放成功率缺失或低于 95%"),
            "mean_observed_entities": (0.0, "平均观测实体数缺失或低于 2"),
        }
        for metric, (failed_value, expected_reason) in published_thresholds.items():
            with self.subTest(metric=metric):
                candidate = {**metrics, metric: failed_value}
                self.assertIn(expected_reason, release_reasons(candidate))
                candidate.pop(metric)
                self.assertIn(expected_reason, release_reasons(candidate))

        all_numeric_thresholds = {
            "vtcr": "VTCR 低于 80%",
            "task_duration_p95_s": "任务 P95 缺失或未低于 120 秒",
            "evidence_coverage": "验证证据覆盖率不是 100%",
            "recovery_rate": "恢复率缺失或低于 70%",
            "state_hash_consistency": "state hash 一致性不是 100%",
            "replay_success_rate": "回放成功率缺失或低于 95%",
            "task_family_count": "评测任务族少于 5 类",
            "complex_task_rate": "复杂任务占比低于 50%",
            "mean_observed_entities": "平均观测实体数缺失或低于 2",
            "goal_condition_coverage": "目标条件覆盖率不是 100%",
        }
        for metric, expected_reason in all_numeric_thresholds.items():
            for invalid_value in (float("nan"), float("inf"), "not-a-number", True):
                with self.subTest(metric=metric, invalid_value=invalid_value):
                    candidate = {**metrics, metric: invalid_value}
                    self.assertIn(expected_reason, release_reasons(candidate))


if __name__ == "__main__":
    unittest.main()
