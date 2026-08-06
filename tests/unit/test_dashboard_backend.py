import io
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "backend"))

from workbench_backend.expression import ExpressionMachine, ExpressionState, derive_expression
from workbench_backend.logging import StructuredLogger
from workbench_backend.read_model import DashboardReadModel
from workbench_backend.server import create_server


class ExpressionTests(unittest.TestCase):
    def test_all_four_states_are_reachable_through_valid_transitions(self) -> None:
        machine = ExpressionMachine()
        self.assertEqual(machine.state, ExpressionState.IDLE)
        self.assertEqual(machine.transition(ExpressionState.THINKING), ExpressionState.THINKING)
        self.assertEqual(machine.transition(ExpressionState.UNCERTAIN), ExpressionState.UNCERTAIN)
        self.assertEqual(machine.transition(ExpressionState.THINKING), ExpressionState.THINKING)
        self.assertEqual(machine.transition(ExpressionState.PLEASED), ExpressionState.PLEASED)

    def test_expression_is_derived_from_verifier_status(self) -> None:
        events = [
            {"event_type": "task_accepted", "payload": {}},
            {"event_type": "verification", "payload": {"status": "insufficient_evidence"}},
        ]
        self.assertEqual(derive_expression([]), ExpressionState.IDLE)
        self.assertEqual(derive_expression(events[:1]), ExpressionState.THINKING)
        self.assertEqual(derive_expression(events), ExpressionState.UNCERTAIN)
        events[-1]["payload"]["status"] = "confirmed"
        self.assertEqual(derive_expression(events), ExpressionState.PLEASED)


class ReadModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = DashboardReadModel(ROOT / "apps" / "dashboard" / "data")

    def test_replay_is_ordered_and_uncertain_lists_missing_evidence(self) -> None:
        events = self.model.list_events("run-uncertain")
        self.assertEqual([event["sequence_no"] for event in events], list(range(len(events))))
        summary = self.model.summarize(events)
        self.assertEqual(summary["status"], "insufficient_evidence")
        self.assertEqual(summary["expression"], "uncertain")
        self.assertEqual(summary["missing_evidence"], ["fresh_camera_frame", "target_confidence_above_0.80"])

    def test_recovery_path_retains_refuted_attempt_and_finishes_confirmed(self) -> None:
        events = self.model.list_events("run-recovery")
        final = self.model.summarize(events)
        first_attempt = self.model.summarize(events, replay_index=4)
        self.assertEqual(first_attempt["status"], "refuted")
        self.assertEqual(first_attempt["expression"], "uncertain")
        self.assertEqual(final["status"], "confirmed")
        self.assertEqual(final["recovery_count"], 1)


class LoggingTests(unittest.TestCase):
    def test_json_log_contains_run_id_and_monotonic_sequence(self) -> None:
        stream = io.StringIO()
        logger = StructuredLogger("test-service", stream)
        first = logger.emit("started", "one", run_id="run-1")
        second = logger.emit("finished", "two", run_id="run-1", source="hardware")
        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual([first["sequence_no"], second["sequence_no"]], [0, 1])
        self.assertEqual(records[1]["source"], "hardware")
        self.assertEqual(records[1]["run_id"], "run-1")


class DashboardApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = create_server("127.0.0.1", 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def read_json(self, path: str) -> tuple[int, dict]:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=2) as response:
            return response.status, json.loads(response.read())

    def test_health_ready_runs_and_replay_endpoints(self) -> None:
        health_status, health = self.read_json("/healthz")
        ready_status, ready = self.read_json("/readyz")
        runs_status, runs = self.read_json("/api/runs")
        events_status, replay = self.read_json("/api/runs/run-recovery/events")
        self.assertEqual((health_status, health["status"]), (200, "ok"))
        self.assertEqual((ready_status, ready["status"]), (200, "ready"))
        self.assertEqual(runs_status, 200)
        self.assertTrue(runs["read_only"])
        self.assertEqual(events_status, 200)
        self.assertEqual(replay["events"][0]["sequence_no"], 0)

    def test_write_requests_fail_closed(self) -> None:
        request = urllib.request.Request(f"{self.base_url}/api/runs/run-confirmed", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        payload = json.loads(caught.exception.read())
        self.assertEqual(caught.exception.code, 405)
        self.assertEqual(payload["error"], "read_only")


if __name__ == "__main__":
    unittest.main()
