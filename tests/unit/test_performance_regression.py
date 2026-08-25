import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "scripts"))

from performance_regression import PerformanceGateError, evaluate, load_json


ENVIRONMENT = {"platform": "test-linux", "python": "3.12.0", "machine": "x86_64"}


def startup(ready: float = 1.0, full: float = 8.0) -> dict:
    return {
        "schema_version": 1,
        "cache_mode": "standard",
        "environment": ENVIRONMENT,
        "phases_s": {
            "image_build": 7.0,
            "container_start_to_health": ready,
            "container_start_to_ready": ready,
            "full_stack_clone_to_ready": full,
        },
    }


def resources(cpu: float = 2.0, memory: float = 16_000_000) -> dict:
    return {
        "schema_version": 1,
        "sample_count": 5,
        "environment": ENVIRONMENT,
        "resources": {
            "dashboard": {
                "samples": 5,
                "cpu_percent_p50": cpu / 2,
                "cpu_percent_p95": cpu,
                "cpu_percent_max": cpu + 1,
                "memory_bytes_p50": memory - 1_000_000,
                "memory_bytes_p95": memory,
                "memory_bytes_max": memory + 1_000_000,
            }
        },
    }


def telemetry(p95: float = 10.0) -> dict:
    return {
        "schema_version": 1,
        "environment": ENVIRONMENT,
        "sources": {
            "simulation": {
                "stages": {
                    "end_to_end": {
                        "samples": 30,
                        "p50_ms": p95 / 2,
                        "p95_ms": p95,
                        "max_ms": p95 + 1,
                    }
                }
            }
        },
    }


def policy() -> dict:
    path = ROOT / "docs" / "performance" / "software-regression-policy-v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def bundle(
    *,
    ready: float = 1.0,
    full: float = 8.0,
    cpu: float = 2.0,
    memory: float = 16_000_000,
    p95: float = 10.0,
) -> dict:
    return {
        "startup": startup(ready, full),
        "resources": resources(cpu, memory),
        "telemetry": telemetry(p95),
    }


def test_gate_passes_comparable_reports_within_budgets() -> None:
    current = bundle(ready=1.1, full=9.0, cpu=2.2, memory=17_000_000, p95=11.0)
    report = evaluate(bundle(), current, policy())

    assert report["status"] == "PASS"
    assert all(check["status"] == "PASS" for check in report["checks"])
    assert report["evidence_class"] == "local_software"
    assert report["target_hardware_measurement"] == "NOT_EXECUTED"


def test_gate_fails_relative_regression_even_below_absolute_budget() -> None:
    report = evaluate(bundle(), bundle(p95=20.0), policy())

    failed = {check["metric"] for check in report["checks"] if check["status"] == "FAIL"}
    assert report["status"] == "FAIL"
    assert failed == {"telemetry.end_to_end.p95_ms"}


def test_gate_fails_absolute_budget_even_with_slow_baseline() -> None:
    report = evaluate(bundle(full=119.0), bundle(full=121.0), policy())

    check = next(item for item in report["checks"] if item["metric"] == "startup.full_stack_clone_to_ready")
    assert check["status"] == "FAIL"
    assert check["current"] > check["absolute_limit"]


def test_gate_rejects_incomparable_environment_and_cache_mode() -> None:
    current = bundle()
    current["startup"]["cache_mode"] = "disabled"
    with pytest.raises(PerformanceGateError, match="not comparable"):
        evaluate(bundle(), current, policy())

    current = bundle()
    current["resources"]["environment"] = {**ENVIRONMENT, "python": "3.13.0"}
    with pytest.raises(PerformanceGateError, match="not comparable"):
        evaluate(bundle(), current, policy())


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, True, "slow"])
def test_gate_rejects_invalid_numeric_evidence(invalid: object) -> None:
    current = bundle()
    current["telemetry"]["sources"]["simulation"]["stages"]["end_to_end"]["p95_ms"] = invalid
    with pytest.raises(PerformanceGateError, match="finite non-negative"):
        evaluate(bundle(), current, policy())


def test_gate_rejects_hardware_telemetry_and_insufficient_samples() -> None:
    current = bundle()
    current["telemetry"]["sources"]["hardware"] = current["telemetry"]["sources"]["simulation"]
    with pytest.raises(PerformanceGateError, match="simulation telemetry only"):
        evaluate(bundle(), current, policy())

    current = bundle()
    current["resources"]["sample_count"] = 4
    with pytest.raises(PerformanceGateError, match="at least 5 samples"):
        evaluate(bundle(), current, policy())


def test_json_loader_rejects_non_finite_constants(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text('{"value": NaN}', encoding="utf-8")
    with pytest.raises(PerformanceGateError, match="non-finite"):
        load_json(path)


def test_cli_writes_failed_report_and_exits_nonzero(tmp_path: Path) -> None:
    paths = {}
    for prefix, reports in (("baseline", bundle()), ("current", bundle(p95=20.0))):
        for kind, payload in reports.items():
            path = tmp_path / f"{prefix}-{kind}.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            paths[f"{prefix}-{kind}"] = path
    output = tmp_path / "gate.json"
    command = [
        sys.executable,
        str(ROOT / "tools" / "scripts" / "performance_regression.py"),
        "--policy",
        str(ROOT / "docs" / "performance" / "software-regression-policy-v1.json"),
    ]
    for kind in ("startup", "resources", "telemetry"):
        command.extend([f"--baseline-{kind}", str(paths[f"baseline-{kind}"])])
        command.extend([f"--current-{kind}", str(paths[f"current-{kind}"])])
    command.extend(["--output", str(output)])

    completed = subprocess.run(command, capture_output=True, text=True, check=False)

    assert completed.returncode == 1
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "FAIL"
    assert any(check["status"] == "FAIL" for check in report["checks"])
