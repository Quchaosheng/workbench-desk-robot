import ipaddress
import json
import os
import re
import socket
import subprocess
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_COMPOSE = ROOT / "deploy" / "multi-host" / "compose.controller.yaml"
SIM_COMPOSE = ROOT / "deploy" / "multi-host" / "compose.sim.yaml"
CONTROLLER_ENV_FIXTURE = ROOT / "tests" / "fixtures" / "issue-71-controller.env"
DEPLOYMENT_DOC = ROOT / "docs" / "deployment" / "multi-host.md"
SMOKE_IMAGE = "workbench-1:issue-71-smoke"
EVENT_SOURCE_ENVIRONMENT = {
    "WORKBENCH_EVENT_SOURCE_URL": "http://10.20.30.40:8090",
    "WORKBENCH_EVENT_SOURCE_ALLOWLIST": "10.20.30.0/24",
}


class ControllerComposeDeploymentTests(unittest.TestCase):
    def compose_environment(self, **overrides: str) -> dict[str, str]:
        environment = os.environ.copy()
        for variable in EVENT_SOURCE_ENVIRONMENT:
            environment.pop(variable, None)
        environment.update(EVENT_SOURCE_ENVIRONMENT)
        environment.update(overrides)
        return environment

    def render_controller(
        self,
        *,
        environment: dict[str, str] | None = None,
        env_file: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = ["docker", "compose"]
        if env_file is not None:
            command.extend(["--env-file", str(env_file.relative_to(ROOT))])
        command.extend(
            [
                "-f",
                str(CONTROLLER_COMPOSE.relative_to(ROOT)),
                "config",
                "--format",
                "json",
            ]
        )
        if environment is None:
            environment = os.environ.copy()
            for variable in EVENT_SOURCE_ENVIRONMENT:
                environment.pop(variable, None)
        return subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_controller_compose_requires_non_empty_event_source_settings(self) -> None:
        for variable in EVENT_SOURCE_ENVIRONMENT:
            missing_environment = self.compose_environment()
            missing_environment.pop(variable)
            with self.subTest(variable=variable, value="missing"):
                result = self.render_controller(environment=missing_environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(variable, result.stdout + result.stderr)

            with self.subTest(variable=variable, value="blank"):
                result = self.render_controller(environment=self.compose_environment(**{variable: ""}))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(variable, result.stdout + result.stderr)

    def test_controller_compose_passes_both_settings_without_permissive_default(self) -> None:
        source = CONTROLLER_COMPOSE.read_text(encoding="utf-8")
        for variable in EVENT_SOURCE_ENVIRONMENT:
            self.assertIn(f"${{{variable}:?", source)
        self.assertIn('"--event-source-url"', source)
        self.assertIn('"--event-source-allowlist"', source)
        self.assertNotIn("0.0.0.0/0", source)
        self.assertNotIn("::/0", source)

    def test_controller_compose_fixture_renders_expected_read_only_service(self) -> None:
        result = self.render_controller(env_file=CONTROLLER_ENV_FIXTURE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rendered = json.loads(result.stdout)
        controller = rendered["services"]["controller"]
        command = controller["command"]
        for argument, expected_value in (
            ("--event-source-url", EVENT_SOURCE_ENVIRONMENT["WORKBENCH_EVENT_SOURCE_URL"]),
            ("--event-source-allowlist", EVENT_SOURCE_ENVIRONMENT["WORKBENCH_EVENT_SOURCE_ALLOWLIST"]),
        ):
            argument_index = command.index(argument)
            self.assertEqual(command[argument_index + 1], expected_value)

        self.assertTrue(controller["read_only"])
        self.assertEqual(controller["cap_drop"], ["ALL"])
        self.assertEqual(controller["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(controller["tmpfs"], ["/tmp:size=32m"])
        for prohibited_capability in ("cap_add", "devices", "privileged", "volumes"):
            self.assertNotIn(prohibited_capability, controller)


class ControllerComposeRuntimeSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            image = subprocess.run(
                ["docker", "image", "inspect", SMOKE_IMAGE],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise unittest.SkipTest(f"Docker is unavailable: {exc}") from exc
        if image.returncode != 0:
            raise unittest.SkipTest(f"build {SMOKE_IMAGE!r} before running the split-host runtime smoke")

    def setUp(self) -> None:
        token = uuid.uuid4().hex[:12]
        self.sim_project = f"issue71-sim-{token}"
        self.controller_project = f"issue71-controller-{token}"
        with (
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sim_socket,
            socket.socket(socket.AF_INET, socket.SOCK_STREAM) as controller_socket,
        ):
            sim_socket.bind(("127.0.0.1", 0))
            controller_socket.bind(("127.0.0.1", 0))
            self.sim_port = sim_socket.getsockname()[1]
            self.controller_port = controller_socket.getsockname()[1]
        self.sim_environment = os.environ | {
            "WORKBENCH_IMAGE": SMOKE_IMAGE,
            "SIM_PORT": str(self.sim_port),
        }
        self.controller_environment = os.environ | {
            "WORKBENCH_IMAGE": SMOKE_IMAGE,
            "CONTROLLER_PORT": str(self.controller_port),
            "WORKBENCH_EVENT_SOURCE_URL": "http://127.0.0.1:1",
            "WORKBENCH_EVENT_SOURCE_ALLOWLIST": "127.0.0.1/32",
        }
        self.addCleanup(self._cleanup)

    def _run(
        self,
        command: list[str],
        *,
        environment: dict[str, str] | None = None,
        check: bool = True,
        timeout: float = 90,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and result.returncode != 0:
            self.fail(
                f"command failed ({result.returncode}): {' '.join(command)}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def _compose(
        self,
        project: str,
        compose_file: Path,
        environment: dict[str, str],
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return self._run(
            [
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(compose_file.relative_to(ROOT)),
                *arguments,
            ],
            environment=environment,
            check=check,
        )

    def _cleanup(self) -> None:
        self._compose(
            self.controller_project,
            CONTROLLER_COMPOSE,
            self.controller_environment,
            "down",
            "--remove-orphans",
            check=False,
        )
        self._compose(
            self.sim_project,
            SIM_COMPOSE,
            self.sim_environment,
            "down",
            "--remove-orphans",
            check=False,
        )

    def _wait_for_status(self, url: str, expected_status: int) -> dict[str, object]:
        deadline = time.monotonic() + 30
        last_status: int | None = None
        last_body = ""
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    last_status = response.status
                    last_body = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                last_status = exc.code
                last_body = exc.read().decode("utf-8")
            except (ConnectionError, TimeoutError, urllib.error.URLError):
                time.sleep(0.25)
                continue
            if last_status == expected_status:
                payload = json.loads(last_body)
                self.assertIsInstance(payload, dict)
                return payload
            time.sleep(0.25)
        self.fail(f"{url} returned status={last_status}, body={last_body!r}; expected {expected_status}")

    def test_controller_compose_runtime_enforces_event_source_allowlist(self) -> None:
        self._compose(self.sim_project, SIM_COMPOSE, self.sim_environment, "up", "-d")
        sim_payload = self._wait_for_status(f"http://127.0.0.1:{self.sim_port}/readyz", 200)
        self.assertEqual(sim_payload["status"], "ready")

        self._compose(
            self.controller_project,
            CONTROLLER_COMPOSE,
            self.controller_environment,
            "up",
            "-d",
        )
        network = self._run(
            [
                "docker",
                "network",
                "inspect",
                f"{self.controller_project}_default",
                "--format",
                "{{(index .IPAM.Config 0).Gateway}}",
            ]
        )
        gateway = network.stdout.strip()
        gateway_address = ipaddress.ip_address(gateway)
        self.assertFalse(gateway_address.is_loopback)

        event_source_url = f"http://{gateway}:{self.sim_port}"
        self.controller_environment |= {
            "WORKBENCH_EVENT_SOURCE_URL": event_source_url,
            "WORKBENCH_EVENT_SOURCE_ALLOWLIST": f"{gateway}/32",
        }
        self._compose(
            self.controller_project,
            CONTROLLER_COMPOSE,
            self.controller_environment,
            "up",
            "-d",
            "--force-recreate",
        )
        allowed_payload = self._wait_for_status(f"http://127.0.0.1:{self.controller_port}/readyz", 200)
        self.assertEqual(allowed_payload["status"], "ready")
        self.assertEqual(allowed_payload["data_source"], "remote-simulation-event-source")

        with urllib.request.urlopen(f"http://127.0.0.1:{self.controller_port}/api/v1/runs", timeout=2) as response:
            remote_runs = json.loads(response.read())
        self.assertTrue(remote_runs["runs"])

        self.controller_environment["WORKBENCH_EVENT_SOURCE_ALLOWLIST"] = "203.0.113.1/32"
        self._compose(
            self.controller_project,
            CONTROLLER_COMPOSE,
            self.controller_environment,
            "up",
            "-d",
            "--force-recreate",
        )
        denied_payload = self._wait_for_status(f"http://127.0.0.1:{self.controller_port}/readyz", 503)
        self.assertEqual(denied_payload["status"], "not_ready")
        self.assertEqual(denied_payload["data_source"], "remote-simulation-event-source")
        sim_after_denial = self._wait_for_status(f"http://127.0.0.1:{self.sim_port}/readyz", 200)
        self.assertEqual(sim_after_denial["status"], "ready")

        print(
            json.dumps(
                {
                    "allowed_status": 200,
                    "controller_gateway": gateway,
                    "denied_status": 503,
                    "event_source_url": event_source_url,
                    "sim_status_after_denial": 200,
                },
                sort_keys=True,
            )
        )


class MultiHostDeploymentDocumentationTests(unittest.TestCase):
    def test_allowlist_contract_is_ip_or_cidr_only_with_both_examples(self) -> None:
        documentation = DEPLOYMENT_DOC.read_text(encoding="utf-8")
        self.assertIn("WORKBENCH_EVENT_SOURCE_ALLOWLIST", documentation)
        self.assertIn("逗号分隔", documentation)
        self.assertIn("字面 IP 地址", documentation)
        self.assertIn("CIDR", documentation)
        self.assertIn("不能使用主机名", documentation)

        assignments = re.findall(
            r'(?:export WORKBENCH_EVENT_SOURCE_ALLOWLIST=|\$env:WORKBENCH_EVENT_SOURCE_ALLOWLIST = ")([^"\s]+)',
            documentation,
        )
        self.assertGreaterEqual(len(assignments), 2)
        for assignment in assignments:
            for entry in assignment.split(","):
                with self.subTest(entry=entry):
                    ipaddress.ip_network(entry, strict=False)


if __name__ == "__main__":
    unittest.main()
