import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from performance_tools import (
    file_sha256,
    hardware_log_hashes,
    load_telemetry,
    parse_memory_bytes,
    software_environment,
    summarize_resource_samples,
    summarize_telemetry,
    validate_hardware_evidence,
)
from register_hardware_evidence import main as register_hardware_evidence


def record(source: str, run_id: str, sequence: int, stage: str, duration_ms: float) -> dict:
    return {
        "timestamp": "2026-08-08T00:00:00+00:00",
        "level": "INFO",
        "service": "test-pipeline",
        "source": source,
        "run_id": run_id,
        "sequence_no": sequence,
        "event": "stage_completed",
        "message": f"{stage} complete",
        "details": {"stage": stage, "duration_ms": duration_ms},
    }


class TelemetryTests(unittest.TestCase):
    def test_software_environment_has_comparison_identity(self) -> None:
        environment = software_environment()
        self.assertEqual(set(environment), {"platform", "python", "machine"})
        self.assertTrue(all(isinstance(value, str) and value for value in environment.values()))

    def test_simulation_and_hardware_use_the_same_aggregator(self) -> None:
        simulation = [
            record("simulation", f"sim-{index}", 0, "planning", value) for index, value in enumerate((1, 2, 9))
        ]
        report = summarize_telemetry(simulation)
        self.assertEqual(report["sources"]["simulation"]["stages"]["planning"]["p50_ms"], 2)
        self.assertEqual(report["sources"]["simulation"]["stages"]["planning"]["p95_ms"], 9)

        hardware = [record("hardware", "hw-1", 0, "planning", 4)]
        with self.assertRaisesRegex(RuntimeError, "operator evidence"):
            summarize_telemetry(hardware)
        attested = summarize_telemetry(
            hardware,
            hardware_evidence={"hardware_id": "arm-01", "operator": "tester", "captured_at": "now"},
        )
        self.assertTrue(attested["hardware_evidence"]["verified"])

    def test_loader_checks_sequence_and_hardware_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "hardware.jsonl"
            log_path.write_text(json.dumps(record("hardware", "hw-1", 0, "planning", 3)) + "\n", encoding="utf-8")
            records, paths = load_telemetry([log_path])
            self.assertEqual(len(records), 1)
            evidence_path = root / "evidence.json"
            evidence_path.write_text(
                json.dumps(
                    {
                        "evidence_kind": "operator_attested_real_hardware",
                        "hardware_id": "arm-01",
                        "operator": "tester",
                        "captured_at": "2026-08-08T00:00:00Z",
                        "logs": {log_path.name: file_sha256(log_path)},
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(validate_hardware_evidence(paths, evidence_path)["hardware_id"], "arm-01")
            log_path.write_text(log_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "hashes"):
                validate_hardware_evidence(paths, evidence_path)

    def test_hardware_evidence_rejects_colliding_log_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first" / "run.jsonl"
            second = root / "second" / "run.jsonl"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "names must be unique"):
                hardware_log_hashes([first, second])

            evidence_path = root / "evidence.json"
            evidence_path.write_text(
                json.dumps(
                    {
                        "evidence_kind": "operator_attested_real_hardware",
                        "hardware_id": "arm-01",
                        "operator": "tester",
                        "captured_at": "2026-08-08T00:00:00Z",
                        "logs": {"run.jsonl": file_sha256(second)},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "names must be unique"):
                validate_hardware_evidence([first, second], evidence_path)

            output = root / "generated.json"
            with (
                patch(
                    "sys.argv",
                    [
                        "register_hardware_evidence.py",
                        str(first),
                        str(second),
                        "--hardware-id",
                        "arm-01",
                        "--operator",
                        "tester",
                        "--output",
                        str(output),
                    ],
                ),
                self.assertRaisesRegex(RuntimeError, "names must be unique"),
            ):
                register_hardware_evidence()
            self.assertFalse(output.exists())

    def test_resource_units_and_percentiles(self) -> None:
        self.assertEqual(parse_memory_bytes("1.5MiB"), 1572864)
        report = summarize_resource_samples(
            [
                {"Name": "dashboard", "CPUPerc": "1.00%", "MemUsage": "10MiB / 1GiB"},
                {"Name": "dashboard", "CPUPerc": "3.00%", "MemUsage": "12MiB / 1GiB"},
            ]
        )
        self.assertEqual(report["dashboard"]["cpu_percent_p95"], 3.0)
        self.assertEqual(report["dashboard"]["memory_bytes_max"], 12 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
