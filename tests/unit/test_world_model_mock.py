import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services/world_model")]

from workbench_world_model import mock_verification, mock_world_state

SCHEMA_DIR = ROOT / "interfaces" / "json_schema"
FIXED_TIMESTAMP = "2026-08-04T00:00:16.200Z"


def schema_validator(schema_name: str) -> Draft202012Validator:
    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resources.append((path.name, Resource.from_contents(contents)))
    registry = Registry().with_resources(resources)
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=registry)


class WorldModelMockTests(unittest.TestCase):
    def assert_schema_valid(self, payload: dict[str, object], schema_name: str) -> None:
        json.dumps(payload)
        errors = list(schema_validator(schema_name).iter_errors(payload))
        self.assertEqual(errors, [], [error.message for error in errors])

    def test_mock_world_state_is_complete_and_schema_valid(self) -> None:
        state = mock_world_state("run-test-001")

        self.assertIsInstance(state, dict)
        self.assertEqual(state["run_id"], "run-test-001")
        self.assertEqual(set(("run_id", "sequence_no", "state_hash", "entities", "reduced_at")) - state.keys(), set())
        self.assertRegex(state["state_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(state["reduced_at"], FIXED_TIMESTAMP)

        entities = {entity["entity_id"]: entity for entity in state["entities"]}
        self.assertIn("red_block", entities)
        self.assertEqual(entities["red_block"]["entity_type"], "block")
        self.assertGreater(len(entities["red_block"]["evidence_refs"]), 0)
        self.assertIn("tray", entities)
        self.assertEqual(entities["tray"]["entity_type"], "tray")
        self.assertGreater(len(entities["tray"]["evidence_refs"]), 0)

        inside_relations = [
            relation
            for relation in state["relations"]
            if relation["subject_id"] == "red_block"
            and relation["predicate"] == "inside"
            and relation["object_id"] == "tray"
        ]
        self.assertEqual(len(inside_relations), 1)
        self.assertGreater(len(inside_relations[0]["evidence_refs"]), 0)
        self.assert_schema_valid(state, "world_state.schema.json")

    def test_mock_verification_supports_all_schema_statuses(self) -> None:
        expected = {
            "confirmed": ("red_block inside tray", "goal_satisfied", 1.0, "none"),
            "refuted": ("red_block inside tray", "goal_not_satisfied", 1.0, "retry_action"),
            "insufficient_evidence": (
                "red_block inside tray could not be verified",
                "target_not_observed",
                0.5,
                "re_observe",
            ),
        }

        for status, (claim, reason_code, completeness, recovery_hint) in expected.items():
            with self.subTest(status=status):
                result = mock_verification(status)
                self.assertIsInstance(result, dict)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["claim"], claim)
                self.assertEqual(result["reason_code"], reason_code)
                self.assertEqual(result["completeness"], completeness)
                self.assertEqual(result["recovery_hint"], recovery_hint)
                self.assertEqual(result["verified_at"], FIXED_TIMESTAMP)
                self.assertGreater(len(result["evidence_refs"]), 0)
                self.assert_schema_valid(result, "verification_result.schema.json")

    def test_refuted_keeps_the_positive_claim(self) -> None:
        result = mock_verification("refuted")

        self.assertEqual(result["claim"], "red_block inside tray")

    def test_insufficient_evidence_has_reason_and_recovery(self) -> None:
        result = mock_verification("insufficient_evidence")

        self.assertEqual(result["reason_code"], "target_not_observed")
        self.assertEqual(result["recovery_hint"], "re_observe")
        self.assertGreater(len(result["evidence_refs"]), 0)

    def test_unknown_verification_status_raises_value_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported verification status"):
            mock_verification("unknown")

    def test_mock_outputs_are_deterministic_and_do_not_share_mutable_state(self) -> None:
        first_state = mock_world_state("run-test-001")
        second_state = mock_world_state("run-test-001")
        self.assertEqual(first_state, second_state)

        first_state["entities"][0]["evidence_refs"].append("mutated")
        self.assertNotIn("mutated", second_state["entities"][0]["evidence_refs"])
        self.assertEqual(second_state, mock_world_state("run-test-001"))

        first_verification = mock_verification("confirmed")
        second_verification = mock_verification("confirmed")
        self.assertEqual(first_verification, second_verification)

        first_verification["evidence_refs"].append("mutated")
        self.assertNotIn("mutated", second_verification["evidence_refs"])
        self.assertEqual(second_verification, mock_verification("confirmed"))

    def test_mock_generation_does_not_use_runtime_world_model_services(self) -> None:
        with (
            patch("sqlite3.connect", side_effect=AssertionError("database accessed")),
            patch("workbench_world_model.reducer.reduce_events", side_effect=AssertionError("reducer accessed")),
            patch(
                "workbench_world_model.verifier.verify_object_in_tray",
                side_effect=AssertionError("verifier accessed"),
            ),
        ):
            mock_world_state("run-test-001")
            mock_verification("confirmed")


if __name__ == "__main__":
    unittest.main()
