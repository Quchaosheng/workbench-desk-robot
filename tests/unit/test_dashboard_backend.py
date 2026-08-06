import io
import json
import sys
import tempfile
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

    def test_event_cache_reuses_parse_and_invalidates_on_file_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "run-cache.jsonl"
            path.write_text(
                json.dumps({"run_id": "run-cache", "sequence_no": 0, "event_type": "task_accepted"}) + "\n",
                encoding="utf-8",
            )
            model = DashboardReadModel(temp_dir)
            first = model.list_events("run-cache")
            second = model.list_events("run-cache")
            self.assertIs(first, second)
            path.write_text(
                "\n".join(
                    [
                        json.dumps({"run_id": "run-cache", "sequence_no": 1, "event_type": "task_terminal"}),
                        json.dumps({"run_id": "run-cache", "sequence_no": 0, "event_type": "task_accepted"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            refreshed = model.list_events("run-cache")
            self.assertIsNot(first, refreshed)
            self.assertEqual([event["sequence_no"] for event in refreshed], [0, 1])


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
        with caught.exception as response:
            payload = json.loads(response.read())
            self.assertEqual(response.code, 405)
        self.assertEqual(payload["error"], "read_only")

    def test_static_assets_support_conditional_and_immutable_caching(self) -> None:
        with urllib.request.urlopen(f"{self.base_url}/", timeout=2) as response:
            etag = response.headers["ETag"]
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
        conditional = urllib.request.Request(f"{self.base_url}/", headers={"If-None-Match": etag})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(conditional, timeout=2)
        with caught.exception as response:
            self.assertEqual(response.code, 304)
        with urllib.request.urlopen(f"{self.base_url}/vendor/lucide.min.js", timeout=2) as response:
            self.assertEqual(response.headers["Cache-Control"], "public, max-age=31536000, immutable")


if __name__ == "__main__":
    unittest.main()
