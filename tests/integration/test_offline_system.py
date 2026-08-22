"""Offline application integration gate.

This suite exercises the software-only path that is available without ROS 2,
Docker, a model server or physical hardware:

    template planner -> semantic TaskGraph -> read-only backend -> replay model

The test deliberately uses the same public entry points as the offline runbook
and never turns fixture data into hardware evidence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "services" / "backend")]

from workbench_backend.server import create_server


DATA_DIR = ROOT / "apps" / "dashboard" / "data"
RUNNER = ROOT / "tools" / "scripts" / "local_runner.py"


def _read_json(base_url: str, route: str) -> tuple[int, dict]:
    with urllib.request.urlopen(f"{base_url}{route}", timeout=2) as response:
        return response.status, json.loads(response.read())


@pytest.fixture
def backend():
    server = create_server("127.0.0.1", 0, data_dir=DATA_DIR)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_offline_template_runner_emits_a_bounded_task_graph() -> None:
    pytest.importorskip("pydantic", reason="project runtime dependencies are installed in CI")
    environment = os.environ.copy()
    environment["WORKBENCH_OFFLINE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--goal", "Place the red block in the tray"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["offline"] is True
    assert payload["provider"] == "template"
    assert payload["network_access"] == "disabled"
    actions = [step["action"]["action_type"] for step in payload["task_graph"]["steps"]]
    assert actions == ["observe", "grasp", "place"]
    assert all(action in {"observe", "grasp", "place", "ask_confirm", "express", "stop"} for action in actions)


def test_backend_exposes_health_readiness_replay_and_all_status_states(backend: str) -> None:
    health_status, health = _read_json(backend, "/healthz")
    ready_status, ready = _read_json(backend, "/readyz")
    runs_status, runs = _read_json(backend, "/api/v1/runs")

    assert (health_status, health["status"]) == (200, "ok")
    assert (ready_status, ready["status"]) == (200, "ready")
    assert runs_status == 200
    assert runs["read_only"] is True

    summaries = {run["run_id"]: run for run in runs["runs"]}
    assert {run["status"] for run in summaries.values()} == {"confirmed", "insufficient_evidence"}
    assert summaries["run-recovery"]["recovery_count"] == 1

    status, replay = _read_json(backend, "/api/v1/runs/run-recovery/events")
    assert status == 200
    assert [event["sequence_no"] for event in replay["events"]] == list(range(len(replay["events"])))
    assert replay["events"]
    assert any(
        event["event_type"] == "verification" and event["payload"].get("status") == "refuted"
        for event in replay["events"]
    )


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_backend_control_methods_fail_closed(backend: str, method: str) -> None:
    request = urllib.request.Request(f"{backend}/api/v1/runs/run-confirmed", data=b"{}", method=method)
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=2)
    assert caught.value.code == 405
    assert json.loads(caught.value.read())["error"] == "read_only"


def test_offline_backend_is_not_ready_for_an_invalid_event_source(tmp_path: Path) -> None:
    (tmp_path / "broken.jsonl").write_text("{not-json}\n", encoding="utf-8")
    server = create_server("127.0.0.1", 0, data_dir=tmp_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{base_url}/readyz", timeout=2)
        assert caught.value.code == 503
        assert _read_json(base_url, "/healthz")[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
