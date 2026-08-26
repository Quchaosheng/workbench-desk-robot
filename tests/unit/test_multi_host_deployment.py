import ipaddress
import json
import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_COMPOSE = ROOT / "deploy" / "multi-host" / "compose.controller.yaml"
CONTROLLER_ENV_FIXTURE = ROOT / "tests" / "fixtures" / "issue-71-controller.env"
DEPLOYMENT_DOC = ROOT / "docs" / "deployment" / "multi-host.md"
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
