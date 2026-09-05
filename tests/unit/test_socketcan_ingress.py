import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "kernel" / "wbcan" / "test_socketcan_ingress.py"
SPEC = importlib.util.spec_from_file_location("socketcan_ingress_probe", MODULE_PATH)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def test_not_executed_report_is_valid_and_keeps_physical_claims_unexecuted() -> None:
    report = probe._not_executed_report("wbcan0", "virtual-wbcan", "root is unavailable")

    probe.validate_report(report)

    assert report["result"] == "NOT_EXECUTED"
    assert report["physical_can"] == "NOT_EXECUTED"
    assert report["mcu"] == "NOT_EXECUTED"
    assert report["actuator"] == "NOT_EXECUTED"
    assert report["hard_real_time"] == "NOT_EXECUTED"


def test_failed_report_with_partial_evidence_is_valid_but_cannot_satisfy_require_pass() -> None:
    report = probe._base_report("wbcan0", "virtual-wbcan")
    report.update(
        {
            "result": "FAIL",
            "error": "peer did not answer",
            "checks": [{"name": "peer response", "result": "FAIL", "detail": "timeout"}],
            "records": {},
            "cleanup": {
                "socket_open": None,
                "peer_closed": None,
                "worker_alive": None,
                "external_depth": None,
            },
        }
    )

    probe.validate_report(report)

    with pytest.raises(ValueError, match="required PASS"):
        probe.validate_report(report, require_pass=True)


def test_pass_validation_requires_a_lowercase_kernel_config_digest() -> None:
    report = probe._base_report("wbcan0", "virtual-wbcan")
    report.update(
        {
            "result": "FAIL",
            "error": "synthetic failure",
            "checks": [{"name": "probe", "result": "FAIL", "detail": "synthetic"}],
            "records": {},
            "cleanup": {
                "socket_open": None,
                "peer_closed": None,
                "worker_alive": None,
                "external_depth": None,
            },
            "kernel_config_sha256": "not-a-digest",
        }
    )

    with pytest.raises(ValueError, match="kernel_config_sha256"):
        probe.validate_report(report)


def test_cli_can_materialize_a_valid_fallback_report(tmp_path: Path) -> None:
    report_path = tmp_path / "fallback.json"
    result = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "wbcan0",
            "--source",
            "virtual-wbcan",
            "--write-not-executed-report",
            str(report_path),
            "--not-executed-reason",
            "module setup failed",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    probe.validate_report(payload)
    assert payload["result"] == "NOT_EXECUTED"
