from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "hardware/power/tools/validate_bms_state_machine.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("bms_state_machine_validator", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def tables():
    module = load_validator()
    states = module.read_csv(module.STATE_MACHINE_PATH, module.STATE_FIELDS)
    transitions = module.read_csv(module.TRANSITIONS_PATH, module.TRANSITION_FIELDS)
    return module, states, transitions


def test_controlled_baseline_is_complete_and_physical_status_is_truthful(tables) -> None:
    module, states, transitions = tables
    report = module.validate(states, transitions, write_report=False)

    assert report["pass"]
    assert report["engineering_package_pass"]
    assert report["status"] == "DESIGN_BASELINE_ONLY"
    assert report["verification_status"] == "NOT_EXECUTED"
    assert report["physical_validation"] == "NOT_EXECUTED"
    assert report["physical_results"] == "NOT_EXECUTED"
    assert report["release_ready"] is False
    assert report["order_release_ready"] is False
    assert report["state_count"] == 9
    assert report["transition_count"] == 16
    assert len(report["transition_table_sha256"]) == 64
    assert int(report["transition_table_sha256"], 16) >= 0


def test_report_artifact_matches_the_deterministic_validator(tables, tmp_path: Path) -> None:
    module, states, transitions = tables
    output = tmp_path / "bms-report.json"
    report = module.validate(states, transitions, output_path=output)

    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == report
    assert written["transition_table_sha256"] == module.transition_table_hash(transitions)
    assert written["state_table_sha256"] == module.state_table_hash(states)
    first_bytes = output.read_bytes()
    assert module.validate(states, transitions, output_path=output) == report
    assert output.read_bytes() == first_bytes


def test_state_policy_rejects_duplicates_missing_fault_behavior_and_unknown_authority(tables) -> None:
    module, states, _ = tables

    duplicate = copy.deepcopy(states)
    duplicate[1]["state"] = duplicate[0]["state"]
    duplicate_report = module.validate_state_rows(duplicate)
    assert not duplicate_report["pass"]
    assert not duplicate_report["checks"]["state_names_are_unique"]

    missing_fault = copy.deepcopy(states)
    missing_fault[3]["fault_action"] = ""
    missing_fault_report = module.validate_state_rows(missing_fault)
    assert not missing_fault_report["pass"]
    assert not missing_fault_report["checks"]["every_state_has_explicit_fault_behavior"]

    unknown_authority = copy.deepcopy(states)
    unknown_authority[0]["reset_authority"] = "controller"
    authority_report = module.validate_state_rows(unknown_authority)
    assert not authority_report["pass"]
    assert not authority_report["checks"]["reset_authorities_are_controlled"]


def test_transition_parser_rejects_header_and_extra_field_drift(tables, tmp_path: Path) -> None:
    module, _, _ = tables
    malformed = tmp_path / "malformed.csv"
    malformed.write_text(
        "source_state,event,guard,target_state,contactor_action,unexpected\nOFF,wake,always,SELF_TEST,all_open,no\n",
        encoding="utf-8",
    )

    with pytest.raises(module.BmsTableError, match="expected header"):
        module.read_csv(malformed, module.TRANSITION_FIELDS)

    duplicate_header = tmp_path / "duplicate-header.csv"
    duplicate_header.write_text(
        "source_state,event,guard,target_state,contactor_action,event\nOFF,wake,always,SELF_TEST,all_open,wake\n",
        encoding="utf-8",
    )
    with pytest.raises(module.BmsTableError, match="duplicate header"):
        module.read_csv(duplicate_header, module.TRANSITION_FIELDS)

    missing_value = tmp_path / "missing-value.csv"
    missing_value.write_text(
        "source_state,event,guard,target_state,contactor_action,latch\nOFF,wake,,SELF_TEST,all_open,no\n",
        encoding="utf-8",
    )
    with pytest.raises(module.BmsTableError, match="guard must be non-empty"):
        module.read_csv(missing_value, module.TRANSITION_FIELDS)


def test_transition_rows_reject_duplicate_keys_unknown_states_actions_and_missing_guards(tables) -> None:
    module, states, transitions = tables

    mutations = []
    duplicate = copy.deepcopy(transitions)
    duplicate[1]["source_state"] = duplicate[0]["source_state"]
    duplicate[1]["event"] = duplicate[0]["event"]
    mutations.append((duplicate, "source_event_pairs_are_unique"))

    unknown_state = copy.deepcopy(transitions)
    unknown_state[0]["target_state"] = "ENERGIZED"
    mutations.append((unknown_state, "source_and_target_states_are_known"))

    unknown_action = copy.deepcopy(transitions)
    unknown_action[3]["contactor_action"] = "close_everything"
    mutations.append((unknown_action, "contactor_actions_are_controlled"))

    missing_guard = copy.deepcopy(transitions)
    missing_guard[0]["guard"] = ""
    mutations.append((missing_guard, "guards_are_present"))

    for mutated, check_name in mutations:
        report = module.validate_transition_rows(states, mutated)
        assert not report["pass"]
        assert not report["checks"][check_name]


def test_deleting_each_required_transition_fails_closed(tables) -> None:
    module, states, transitions = tables

    for index in range(len(transitions)):
        mutated = [row for row_index, row in enumerate(transitions) if row_index != index]
        report = module.validate_transition_rows(states, mutated)
        assert not report["pass"], index
        assert not report["checks"]["transition_set_is_complete"], index


def test_illegal_edges_and_automatic_fault_recovery_are_rejected(tables) -> None:
    module, states, transitions = tables

    illegal_edge = copy.deepcopy(transitions)
    illegal_edge[0]["target_state"] = "RUN"
    illegal_report = module.validate_transition_rows(states, illegal_edge)
    assert not illegal_report["pass"]
    assert not illegal_report["checks"]["legal_transition_graph_is_preserved"]
    assert not illegal_report["checks"]["transition_contract_matches_baseline"]

    automatic_recovery = copy.deepcopy(transitions)
    automatic_recovery[14]["event"] = "trigger_clear"
    automatic_recovery[14]["guard"] = "always"
    recovery_report = module.validate_transition_rows(states, automatic_recovery)
    assert not recovery_report["pass"]
    assert not recovery_report["checks"]["fault_latched_has_only_explicit_local_reset"]

    direct_run = copy.deepcopy(transitions)
    direct_run[14]["target_state"] = "RUN"
    direct_run_report = module.validate_transition_rows(states, direct_run)
    assert not direct_run_report["pass"]
    assert not direct_run_report["checks"]["run_entry_requires_precharge_or_derate_recovery"]


def test_transition_order_and_hash_are_stable_and_reordering_fails(tables) -> None:
    module, states, transitions = tables
    first = module.validate(states, transitions, write_report=False)
    second = module.validate(states, transitions, write_report=False)
    assert first["transition_table_sha256"] == second["transition_table_sha256"]
    assert first["state_machine_sha256"] == second["state_machine_sha256"]

    reordered = [transitions[1], transitions[0], *transitions[2:]]
    reordered_report = module.validate_transition_rows(states, reordered)
    assert not reordered_report["pass"]
    assert not reordered_report["checks"]["transition_order_is_deterministic"]
    assert module.transition_table_hash(reordered) != first["transition_table_sha256"]


def test_hash_algorithm_is_sha256_of_normalized_transition_csv(tables) -> None:
    module, _, transitions = tables
    canonical = module._canonical_csv(module.TRANSITION_FIELDS, transitions)
    assert module.transition_table_hash(transitions) == hashlib.sha256(canonical).hexdigest()
