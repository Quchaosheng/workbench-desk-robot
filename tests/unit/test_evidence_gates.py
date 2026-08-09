import unittest

from validate_cold_start import validate


def participant(identifier: str, result: str = "pass", elapsed: float = 12) -> dict:
    return {
        "participant_id": identifier,
        "os": "Ubuntu 24.04",
        "docker_version": "29.0",
        "started_at": "2026-08-08T00:00:00Z",
        "first_ready_at": "2026-08-08T00:12:00Z",
        "elapsed_minutes": elapsed,
        "result": result,
    }


class EvidenceGateTests(unittest.TestCase):
    def test_two_of_three_passes_is_accepted(self) -> None:
        summary = validate({"participants": [participant("one"), participant("two"), participant("three", "fail")]})
        self.assertEqual(summary, {"participant_count": 3, "pass_count": 2, "accepted": True})

    def test_duplicate_participants_and_slow_passes_are_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unique"):
            validate({"participants": [participant("one"), participant("one"), participant("three")]})
        with self.assertRaisesRegex(RuntimeError, "exceeded"):
            validate({"participants": [participant("one", elapsed=61), participant("two"), participant("three")]})


if __name__ == "__main__":
    unittest.main()
