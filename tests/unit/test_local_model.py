import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

from workbench_agent_runtime import (
    LocalModelError,
    OllamaModelProvider,
    build_local_model_plan,
    validate_local_endpoint,
)


class FakeOllamaHandler(BaseHTTPRequestHandler):
    route: ClassVar[dict[str, object]] = {
        "task_family": "parcel_sorting",
        "requires_navigation": False,
        "requires_joint_control": False,
        "requires_completion_claim": False,
        "reason": "Parcels are already in the tabletop intake area.",
    }
    request_payload: ClassVar[dict[str, object] | None] = None

    def log_message(self, format: str, *args) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        type(self).request_payload = json.loads(self.rfile.read(length))
        body = json.dumps(
            {
                "message": {"content": json.dumps(type(self).route)},
                "done_reason": "stop",
                "prompt_eval_count": 32,
                "eval_count": 12,
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class LocalModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self) -> None:
        FakeOllamaHandler.route = {
            "task_family": "parcel_sorting",
            "requires_navigation": False,
            "requires_joint_control": False,
            "requires_completion_claim": False,
            "reason": "Parcels are already in the tabletop intake area.",
        }

    def test_model_routes_then_trusted_code_builds_semantic_plan(self) -> None:
        provider = OllamaModelProvider("test-model", endpoint=self.endpoint)
        plan = build_local_model_plan("Handle everything waiting in the intake zone", provider)
        self.assertEqual(plan.model_route, "parcel_sorting")
        self.assertEqual(plan.planner, "local-model:ollama:test-model")
        self.assertTrue(all("joint" not in step.action.parameters for step in plan.steps))
        self.assertEqual(FakeOllamaHandler.request_payload["format"]["additionalProperties"], False)
        self.assertEqual(provider.last_call["endpoint_host"], "127.0.0.1")
        self.assertIsInstance(provider.last_call["latency_ms"], float)

    def test_unsafe_route_fails_closed_before_building_actions(self) -> None:
        FakeOllamaHandler.route = {
            "task_family": "parcel_sorting",
            "requires_navigation": True,
            "requires_joint_control": False,
            "requires_completion_claim": False,
            "reason": "The request needs a parcel locker visit.",
        }
        provider = OllamaModelProvider("test-model", endpoint=self.endpoint)
        with self.assertRaisesRegex(LocalModelError, "requires_navigation"):
            build_local_model_plan("Go downstairs and collect the parcel", provider)

    def test_model_cannot_override_deterministic_family_boundary(self) -> None:
        FakeOllamaHandler.route = {
            **FakeOllamaHandler.route,
            "task_family": "place",
        }
        provider = OllamaModelProvider("test-model", endpoint=self.endpoint)
        with self.assertRaisesRegex(LocalModelError, "disagrees"):
            build_local_model_plan("Handle the parcels already in the intake area", provider)

    def test_route_with_extra_fields_is_rejected(self) -> None:
        FakeOllamaHandler.route = {
            **FakeOllamaHandler.route,
            "joint_velocity": 10,
        }
        provider = OllamaModelProvider("test-model", endpoint=self.endpoint)
        with self.assertRaisesRegex(LocalModelError, "unexpected fields"):
            build_local_model_plan("Sort parcels", provider)

    def test_remote_or_credentialed_endpoint_is_rejected(self) -> None:
        for endpoint in ("https://example.com", "http://example.com", "http://user:pass@localhost:11434"):
            with self.subTest(endpoint=endpoint), self.assertRaises(LocalModelError):
                validate_local_endpoint(endpoint)
        self.assertEqual(validate_local_endpoint("http://model:11434", {"model"}), "http://model:11434")


if __name__ == "__main__":
    unittest.main()
