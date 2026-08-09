from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_validator():
    path = ROOT / "hardware/tools/validate_operations_readiness.py"
    spec = importlib.util.spec_from_file_location("operations_readiness", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_operations_baseline_has_all_quantitative_gates() -> None:
    report = load_validator().validate()
    assert report["pass"]
    assert report["status"] == "EXTERNAL_EVIDENCE_REQUIRED"
    assert all(report["checks"].values())


def test_planning_values_are_not_claimed_as_physical_evidence() -> None:
    procurement = (ROOT / "hardware/procurement/planning-baseline.md").read_text(encoding="utf-8")
    mechanical = (ROOT / "hardware/mechanical/system-integration.md").read_text(encoding="utf-8")
    compliance = (ROOT / "hardware/compliance/README.md").read_text(encoding="utf-8")
    assert "not a quote" in procurement
    assert "not a measured result" in mechanical
    assert "NOT_CERTIFIED" in compliance


def test_demo_schedule_totals_90_minutes() -> None:
    runbook = (ROOT / "docs/user-guide/demo-runbook.md").read_text(encoding="utf-8")
    expected_windows = ["0-10", "10-20", "20-30", "30-45", "45-60", "60-75", "75-85", "85-90"]
    assert all(window in runbook for window in expected_windows)


def test_task_packet_is_bounded_and_fail_closed() -> None:
    packet = json.loads((ROOT / "docs/task_packets/operations-readiness-020-027.json").read_text(encoding="utf-8"))
    assert packet["issues"] == list(range(20, 28))
    assert "firmware/**" in packet["forbidden"]
    assert "interfaces/**" in packet["forbidden"]
    assert any("invented" in condition for condition in packet["stop_conditions"])


def test_structured_evidence_attachments_are_complete() -> None:
    report = load_validator().validate()
    checks = report["checks"]
    for name in (
        "bms_has_fail_closed_states",
        "bms_transition_graph_uses_known_states",
        "bms_run_entry_requires_precharge_or_derate_recovery",
        "bms_fault_transitions_open_and_latch",
        "mass_ledger_sums_to_55kg",
        "mass_ledger_cg_is_calculated",
        "planning_bom_rows_sum_to_5100",
        "station_map_has_six_unique_stations",
        "fixture_budget_rows_sum_to_4000",
        "all_fmea_actions_are_above_rpn_threshold",
        "compliance_matrix_has_three_required_programs",
        "support_has_four_severity_levels",
        "documentation_build_is_in_ci",
    ):
        assert checks[name], name

    assert report["metrics"] == {
        "mass_kg": 55.0,
        "center_of_gravity_mm": [0.0, -9.1, 470.0],
        "planning_bom_total_usd": 5100.0,
        "fixture_budget_total_usd": 4000.0,
        "station_count": 6,
    }
