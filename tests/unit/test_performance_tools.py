import json
import tempfile
import unittest
from pathlib import Path

from performance_tools import (
    file_sha256,
    load_telemetry,
    parse_memory_bytes,
    summarize_resource_samples,
    summarize_telemetry,
    validate_hardware_evidence,
)


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
