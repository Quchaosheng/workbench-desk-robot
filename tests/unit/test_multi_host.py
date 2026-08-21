import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from workbench_backend.read_model import ReadModelError, RemoteDashboardReadModel
from workbench_backend.server import create_server


class MultiHostReadModelTests(unittest.TestCase):
    def test_remote_json_rejects_top_level_and_nested_duplicate_keys(self) -> None:
        model = RemoteDashboardReadModel("http://127.0.0.1:1")
        cases = {
            "runs": b'{"runs":[],"runs":[]}',
            "task_id": b'{"runs":[{"task_id":"secret-marker","task_id":"trusted"}]}',
        }
        for duplicate_key, body in cases.items():
            with (
                self.subTest(duplicate_key=duplicate_key),
                mock.patch("workbench_backend.read_model.urllib.request.urlopen", return_value=io.BytesIO(body)),
                self.assertRaisesRegex(ReadModelError, rf"duplicate JSON key: '{duplicate_key}'") as caught,
            ):
                model.list_runs()
            self.assertNotIn("secret-marker", str(caught.exception))

        with mock.patch(
            "workbench_backend.read_model.urllib.request.urlopen",
            return_value=io.BytesIO(b'{"status":"not_ready","status":"ready"}'),
        ):
            self.assertFalse(model.ready())

    def test_controller_reads_remote_source_and_fails_ready_when_peer_is_down(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            data_dir.joinpath("run-remote.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "event_id": "evt-1",
                                "run_id": "run-remote",
                                "sequence_no": 0,
                                "event_type": "task_accepted",
                                "occurred_at": "2026-08-08T00:00:00Z",
                                "payload": {"task_id": "task-1", "goal": "test"},
                                "evidence_refs": [],
                            }
                        ),
                        json.dumps(
                            {
                                "event_id": "evt-2",
                                "run_id": "run-remote",
                                "sequence_no": 1,
                                "event_type": "task_terminal",
                                "occurred_at": "2026-08-08T00:00:01Z",
                                "payload": {},
                                "evidence_refs": [],
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            sim = create_server("127.0.0.1", 0, data_dir=data_dir)
            sim_thread = threading.Thread(target=sim.serve_forever, daemon=True)
            sim_thread.start()
            sim_url = f"http://127.0.0.1:{sim.server_address[1]}"
            controller = create_server("127.0.0.1", 0, event_source_url=sim_url)
            controller_thread = threading.Thread(target=controller.serve_forever, daemon=True)
            controller_thread.start()
            controller_url = f"http://127.0.0.1:{controller.server_address[1]}"
            try:
                with urllib.request.urlopen(f"{controller_url}/readyz", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.loads(response.read())["data_source"], "remote-simulation-event-source")
                with urllib.request.urlopen(f"{controller_url}/api/v1/runs/run-remote/events", timeout=2) as response:
                    payload = json.loads(response.read())
                    self.assertEqual(payload["events"][0]["run_id"], "run-remote")
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    urllib.request.urlopen(f"{controller_url}/api/v1/runs/missing/events", timeout=2)
                self.assertEqual(missing.exception.code, 404)
                sim.shutdown()
                sim.server_close()
                sim_thread.join(timeout=2)
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(f"{controller_url}/readyz", timeout=3)
                self.assertEqual(caught.exception.code, 503)
            finally:
                controller.shutdown()
                controller.server_close()
                controller_thread.join(timeout=2)
                if sim_thread.is_alive():
                    sim.shutdown()
                    sim.server_close()
                    sim_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
