"""Validate the reviewable BMS state machine without claiming physical evidence.

The CSV files in ``hardware/power`` are a controlled design baseline. This
validator intentionally checks the complete baseline rather than accepting any
graph that happens to be internally connected: a deleted protection edge or an
unexpected recovery edge must fail closed and be visible in the report.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "hardware" / "power"
STATE_MACHINE_PATH = PACKAGE / "bms-state-machine.csv"
TRANSITIONS_PATH = PACKAGE / "bms-transitions.csv"
OUTPUT_PATH = PACKAGE / "generated" / "bms_state_machine_report.json"

STATE_FIELDS = (
    "state",
    "entry_condition",
    "allowed_contactors",
    "exit_condition",
    "fault_action",
    "reset_authority",
)
TRANSITION_FIELDS = (
    "source_state",
    "event",
    "guard",
    "target_state",
    "contactor_action",
    "latch",
)

STATE_ORDER = (
    "OFF",
    "SELF_TEST",
    "STANDBY",
    "PRECHARGE",
    "RUN",
    "CHARGE",
    "DERATE",
    "FAULT_LATCHED",
    "SERVICE",
)

STATE_CONTRACT: dict[str, dict[str, str]] = {
    "OFF": {
        "entry_condition": "service_disconnect_open",
        "allowed_contactors": "none",
        "exit_condition": "valid_pack_and_wake",
        "fault_action": "remain_deenergized",
        "reset_authority": "operator",
    },
    "SELF_TEST": {
        "entry_condition": "wake_request",
        "allowed_contactors": "none",
        "exit_condition": "all_sensors_and_config_valid",
        "fault_action": "latch_fault",
        "reset_authority": "service_owner",
    },
    "STANDBY": {
        "entry_condition": "self_test_passed",
        "allowed_contactors": "none",
        "exit_condition": "authorized_charge_or_run_request",
        "fault_action": "latch_fault",
        "reset_authority": "operator",
    },
    "PRECHARGE": {
        "entry_condition": "run_request_and_safety_chain_ok",
        "allowed_contactors": "precharge_only",
        "exit_condition": "bus_ratio_and_timeout_pass",
        "fault_action": "open_all_contactors",
        "reset_authority": "service_owner",
    },
    "RUN": {
        "entry_condition": "precharge_passed",
        "allowed_contactors": "precharge_and_main",
        "exit_condition": "stop_request_or_trip",
        "fault_action": "open_all_contactors",
        "reset_authority": "operator_plus_service",
    },
    "CHARGE": {
        "entry_condition": "approved_charger_and_temperature_ok",
        "allowed_contactors": "charge_only",
        "exit_condition": "full_unplug_or_trip",
        "fault_action": "open_all_contactors",
        "reset_authority": "operator",
    },
    "DERATE": {
        "entry_condition": "warning_threshold_crossed",
        "allowed_contactors": "active_path_with_reduced_limit",
        "exit_condition": "hysteresis_recovery_or_trip",
        "fault_action": "reduce_limit_or_latch",
        "reset_authority": "BMS",
    },
    "FAULT_LATCHED": {
        "entry_condition": "protection_trip_or_invalid_state",
        "allowed_contactors": "none",
        "exit_condition": "trigger_cleared_and_local_reset",
        "fault_action": "remain_deenergized",
        "reset_authority": "service_owner",
    },
    "SERVICE": {
        "entry_condition": "authenticated_maintenance_request",
        "allowed_contactors": "none",
        "exit_condition": "service_exit_and_self_test",
        "fault_action": "remain_deenergized",
        "reset_authority": "service_owner",
    },
}

# The order is part of the reviewable baseline. It makes generated evidence
# and its hash stable, while also making a missing row fail the completeness
# check instead of silently changing the meaning of a default path.
TRANSITION_CONTRACT: tuple[dict[str, str], ...] = (
    {
        "source_state": "OFF",
        "event": "wake",
        "guard": "pack_present_and_service_disconnect_closed",
        "target_state": "SELF_TEST",
        "contactor_action": "all_open",
        "latch": "no",
    },
    {
        "source_state": "SELF_TEST",
        "event": "self_test_pass",
        "guard": "config_and_sensors_valid",
        "target_state": "STANDBY",
        "contactor_action": "all_open",
        "latch": "no",
    },
    {
        "source_state": "SELF_TEST",
        "event": "self_test_fail",
        "guard": "always",
        "target_state": "FAULT_LATCHED",
        "contactor_action": "all_open",
        "latch": "yes",
    },
    {
        "source_state": "STANDBY",
        "event": "run_request",
        "guard": "safety_chain_ok",
        "target_state": "PRECHARGE",
        "contactor_action": "precharge_close",
        "latch": "no",
    },
    {
        "source_state": "STANDBY",
        "event": "charge_request",
        "guard": "approved_charger_and_temperature_ok",
        "target_state": "CHARGE",
        "contactor_action": "charge_close",
        "latch": "no",
    },
    {
        "source_state": "PRECHARGE",
        "event": "precharge_pass",
        "guard": "bus_ratio_and_timeout_ok",
        "target_state": "RUN",
        "contactor_action": "main_close_then_precharge_open",
        "latch": "no",
    },
    {
        "source_state": "PRECHARGE",
        "event": "precharge_fail",
        "guard": "timeout_or_ratio_invalid",
        "target_state": "FAULT_LATCHED",
        "contactor_action": "all_open",
        "latch": "yes",
    },
    {
        "source_state": "RUN",
        "event": "warning",
        "guard": "within_derate_envelope",
        "target_state": "DERATE",
        "contactor_action": "current_limit_reduce",
        "latch": "no",
    },
    {
        "source_state": "RUN",
        "event": "stop_request",
        "guard": "always",
        "target_state": "STANDBY",
        "contactor_action": "all_open",
        "latch": "no",
    },
    {
        "source_state": "RUN",
        "event": "protection_trip",
        "guard": "always",
        "target_state": "FAULT_LATCHED",
        "contactor_action": "all_open",
        "latch": "yes",
    },
    {
        "source_state": "CHARGE",
        "event": "charge_complete_or_unplug",
        "guard": "always",
        "target_state": "STANDBY",
        "contactor_action": "all_open",
        "latch": "no",
    },
    {
        "source_state": "CHARGE",
        "event": "protection_trip",
        "guard": "always",
        "target_state": "FAULT_LATCHED",
        "contactor_action": "all_open",
        "latch": "yes",
    },
    {
        "source_state": "DERATE",
        "event": "recovered",
        "guard": "hysteresis_clear",
        "target_state": "RUN",
        "contactor_action": "current_limit_restore",
        "latch": "no",
    },
    {
        "source_state": "DERATE",
        "event": "protection_trip",
        "guard": "always",
        "target_state": "FAULT_LATCHED",
        "contactor_action": "all_open",
        "latch": "yes",
    },
    {
        "source_state": "FAULT_LATCHED",
        "event": "local_reset",
        "guard": "trigger_clear_and_service_authorized",
        "target_state": "SELF_TEST",
        "contactor_action": "all_open",
        "latch": "no",
    },
    {
        "source_state": "SERVICE",
        "event": "service_exit",
        "guard": "always",
        "target_state": "SELF_TEST",
        "contactor_action": "all_open",
        "latch": "no",
    },
)

ALLOWED_CONTACTORS = frozenset(
    {
        "none",
        "precharge_only",
        "precharge_and_main",
        "charge_only",
        "active_path_with_reduced_limit",
    }
)
ALLOWED_FAULT_ACTIONS = frozenset({"remain_deenergized", "latch_fault", "open_all_contactors", "reduce_limit_or_latch"})
ALLOWED_RESET_AUTHORITIES = frozenset({"operator", "service_owner", "operator_plus_service", "BMS"})
ALLOWED_CONTACTOR_ACTIONS = frozenset(
    {
        "all_open",
        "precharge_close",
        "main_close_then_precharge_open",
        "charge_close",
        "current_limit_reduce",
        "current_limit_restore",
    }
)
ALLOWED_LATCH_VALUES = frozenset({"yes", "no"})


class BmsTableError(ValueError):
    """Raised when a BMS CSV cannot be parsed as its declared table."""


def _normalise_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalise_rows(
    rows: Sequence[Mapping[str, object]], fields: tuple[str, ...]
) -> tuple[list[dict[str, str]], list[str]]:
    normalised: list[dict[str, str]] = []
    errors: list[str] = []
    field_set = set(fields)
    for row_number, raw in enumerate(rows, start=2):
        if not isinstance(raw, Mapping):
            errors.append(f"row {row_number}: expected an object")
            continue
        keys = set(raw)
        missing = sorted(field_set - keys)
        extra = sorted(str(key) for key in keys - field_set)
        if missing:
            errors.append(f"row {row_number}: missing fields {', '.join(missing)}")
        if extra:
            errors.append(f"row {row_number}: unknown fields {', '.join(extra)}")
        normalised_row = {field: _normalise_value(raw.get(field)) for field in fields}
        normalised.append(normalised_row)
        for field, value in normalised_row.items():
            if not value:
                errors.append(f"row {row_number}: {field} must be non-empty")
            elif not isinstance(raw.get(field), str):
                errors.append(f"row {row_number}: {field} must be text")
    return normalised, errors


def read_csv(path: str | Path, fields: tuple[str, ...]) -> list[dict[str, str]]:
    """Read one controlled CSV and reject header/shape drift."""

    resolved = Path(path)
    try:
        with resolved.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise BmsTableError(f"{resolved}: missing header")
            if len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise BmsTableError(f"{resolved}: duplicate header field")
            if tuple(reader.fieldnames) != fields:
                raise BmsTableError(
                    f"{resolved}: expected header {','.join(fields)}, got {','.join(reader.fieldnames)}"
                )
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise BmsTableError(f"{resolved}: cannot read CSV: {exc}") from exc

    normalised, errors = _normalise_rows(rows, fields)
    if errors:
        raise BmsTableError(f"{resolved}: " + "; ".join(errors))
    return normalised


def _check_map(checks: dict[str, bool], errors: list[str], name: str, condition: bool, message: str) -> None:
    checks[name] = condition
    if not condition:
        errors.append(message)


def _canonical_csv(fields: tuple[str, ...], rows: Sequence[Mapping[str, str]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(fields)
    for row in rows:
        writer.writerow([_normalise_value(row.get(field, "")) for field in fields])
    return buffer.getvalue().encode("utf-8")


def transition_table_hash(rows: Sequence[Mapping[str, str]]) -> str:
    """Return the SHA-256 of the normalized, ordered transition CSV."""

    return hashlib.sha256(_canonical_csv(TRANSITION_FIELDS, rows)).hexdigest()


def state_table_hash(rows: Sequence[Mapping[str, str]]) -> str:
    """Return the SHA-256 of the normalized, ordered state CSV."""

    return hashlib.sha256(_canonical_csv(STATE_FIELDS, rows)).hexdigest()


def validate_state_rows(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Validate state declarations and their fail/default behavior."""

    normalised, parse_errors = _normalise_rows(rows, STATE_FIELDS)
    checks: dict[str, bool] = {}
    errors = list(parse_errors)
    names = [row["state"] for row in normalised]

    _check_map(
        checks,
        errors,
        "state_rows_are_nonempty",
        bool(normalised),
        "state table must contain at least one row",
    )
    _check_map(
        checks,
        errors,
        "state_names_are_unique",
        len(names) == len(set(names)),
        "state names must be unique",
    )
    _check_map(
        checks,
        errors,
        "state_order_is_deterministic",
        names == list(STATE_ORDER),
        "state rows must follow the controlled baseline order",
    )
    _check_map(
        checks,
        errors,
        "state_set_is_complete",
        set(names) == set(STATE_ORDER),
        "state table must contain exactly the controlled BMS states",
    )
    _check_map(
        checks,
        errors,
        "allowed_contactor_values_are_controlled",
        all(row["allowed_contactors"] in ALLOWED_CONTACTORS for row in normalised),
        "state table contains an unknown allowed contactor value",
    )
    _check_map(
        checks,
        errors,
        "fault_actions_are_controlled",
        all(row["fault_action"] in ALLOWED_FAULT_ACTIONS for row in normalised),
        "state table contains an unknown fault/default action",
    )
    _check_map(
        checks,
        errors,
        "reset_authorities_are_controlled",
        all(row["reset_authority"] in ALLOWED_RESET_AUTHORITIES for row in normalised),
        "state table contains an unknown reset authority",
    )
    _check_map(
        checks,
        errors,
        "every_state_has_explicit_fault_behavior",
        all(row["fault_action"] for row in normalised) and len(normalised) == len(STATE_ORDER),
        "every state must declare a non-empty fault/default behavior",
    )
    _check_map(
        checks,
        errors,
        "state_contract_matches_baseline",
        all(
            row["state"] in STATE_CONTRACT
            and all(row[field] == expected for field, expected in STATE_CONTRACT[row["state"]].items())
            for row in normalised
        ),
        "state contactor, fault, or reset policy differs from the controlled baseline",
    )
    return {
        "rows": normalised,
        "checks": checks,
        "errors": errors,
        "pass": all(checks.values()) and not errors,
    }


def validate_transition_rows(
    state_rows: Sequence[Mapping[str, object]], transitions: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Validate the complete guarded transition graph against the baseline."""

    normalised_states, state_parse_errors = _normalise_rows(state_rows, STATE_FIELDS)
    normalised, parse_errors = _normalise_rows(transitions, TRANSITION_FIELDS)
    checks: dict[str, bool] = {}
    errors = [*state_parse_errors, *parse_errors]
    known_states = {row["state"] for row in normalised_states}
    keys = [(row["source_state"], row["event"]) for row in normalised]
    expected_keys = [(row["source_state"], row["event"]) for row in TRANSITION_CONTRACT]
    actual_edges = {(row["source_state"], row["event"], row["target_state"]) for row in normalised}
    expected_edges = {(row["source_state"], row["event"], row["target_state"]) for row in TRANSITION_CONTRACT}

    _check_map(
        checks,
        errors,
        "transition_rows_are_nonempty",
        bool(normalised),
        "transition table must contain at least one row",
    )
    _check_map(
        checks,
        errors,
        "source_event_pairs_are_unique",
        len(keys) == len(set(keys)),
        "each source state/event pair must occur exactly once",
    )
    _check_map(
        checks,
        errors,
        "event_names_are_unique_per_source_state",
        len(keys) == len(set(keys)),
        "event names must be unique within each source state",
    )
    _check_map(
        checks,
        errors,
        "source_and_target_states_are_known",
        all(row["source_state"] in known_states and row["target_state"] in known_states for row in normalised),
        "transition references an undeclared state",
    )
    _check_map(
        checks,
        errors,
        "contactor_actions_are_controlled",
        all(row["contactor_action"] in ALLOWED_CONTACTOR_ACTIONS for row in normalised),
        "transition contains an unknown contactor action",
    )
    _check_map(
        checks,
        errors,
        "latch_values_are_controlled",
        all(row["latch"] in ALLOWED_LATCH_VALUES for row in normalised),
        "transition latch must be yes or no",
    )
    _check_map(
        checks,
        errors,
        "guards_are_present",
        all(bool(row["guard"]) for row in normalised),
        "every transition must have a non-empty guard",
    )
    _check_map(
        checks,
        errors,
        "transition_order_is_deterministic",
        keys == expected_keys,
        "transition rows must follow the controlled baseline order",
    )
    _check_map(
        checks,
        errors,
        "transition_set_is_complete",
        len(normalised) == len(TRANSITION_CONTRACT) and set(keys) == set(expected_keys),
        "transition table is missing or adding a controlled source state/event path",
    )
    _check_map(
        checks,
        errors,
        "legal_transition_graph_is_preserved",
        actual_edges == expected_edges and len(normalised) == len(TRANSITION_CONTRACT),
        "transition graph contains an illegal or missing edge",
    )
    _check_map(
        checks,
        errors,
        "transition_contract_matches_baseline",
        normalised == [dict(row) for row in TRANSITION_CONTRACT],
        "guard, target, contactor action, or latch differs from the controlled baseline",
    )

    fault_sources = [row for row in normalised if row["source_state"] == "FAULT_LATCHED"]
    fault_targets = [row for row in normalised if row["target_state"] == "FAULT_LATCHED"]
    _check_map(
        checks,
        errors,
        "fault_latched_has_only_explicit_local_reset",
        len(fault_sources) == 1
        and fault_sources[0]["event"] == "local_reset"
        and fault_sources[0]["target_state"] == "SELF_TEST"
        and fault_sources[0]["latch"] == "no",
        "FAULT_LATCHED may recover only through the explicit local_reset path",
    )
    _check_map(
        checks,
        errors,
        "fault_transitions_open_and_latch",
        bool(fault_targets)
        and all(row["contactor_action"] == "all_open" and row["latch"] == "yes" for row in fault_targets),
        "every protection transition into FAULT_LATCHED must open all contactors and latch",
    )
    _check_map(
        checks,
        errors,
        "run_entry_requires_precharge_or_derate_recovery",
        all(row["source_state"] in {"PRECHARGE", "DERATE"} for row in normalised if row["target_state"] == "RUN"),
        "RUN may only be entered from PRECHARGE or DERATE recovery",
    )
    return {
        "rows": normalised,
        "checks": checks,
        "errors": errors,
        "pass": all(checks.values()) and not errors,
    }


def _load_or_error(path: Path, fields: tuple[str, ...]) -> tuple[list[dict[str, str]], list[str]]:
    try:
        return read_csv(path, fields), []
    except BmsTableError as exc:
        return [], [str(exc)]


def validate(
    state_rows: Sequence[Mapping[str, object]] | None = None,
    transition_rows: Sequence[Mapping[str, object]] | None = None,
    *,
    write_report: bool = True,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    """Return a structural report and optionally write its deterministic JSON artifact."""

    load_errors: list[str] = []
    if state_rows is None:
        loaded_states, errors = _load_or_error(STATE_MACHINE_PATH, STATE_FIELDS)
        state_rows = loaded_states
        load_errors.extend(errors)
    if transition_rows is None:
        loaded_transitions, errors = _load_or_error(TRANSITIONS_PATH, TRANSITION_FIELDS)
        transition_rows = loaded_transitions
        load_errors.extend(errors)

    state_report = validate_state_rows(state_rows)
    transition_report = validate_transition_rows(state_rows, transition_rows)
    states = state_report["rows"]
    transitions = transition_report["rows"]
    status = "DESIGN_BASELINE_ONLY"
    verification_status = "NOT_EXECUTED"
    physical_validation = "NOT_EXECUTED"
    physical_results = "NOT_EXECUTED"
    release_ready = False
    order_release_ready = False
    checks = {
        "state_table_valid": bool(state_report["pass"]),
        "transition_table_valid": bool(transition_report["pass"]),
        "design_status_is_preserved": status == "DESIGN_BASELINE_ONLY",
        "physical_validation_is_not_executed": physical_validation == "NOT_EXECUTED"
        and physical_results == "NOT_EXECUTED"
        and verification_status == "NOT_EXECUTED"
        and release_ready is False
        and order_release_ready is False,
    }
    errors = [*load_errors, *state_report["errors"], *transition_report["errors"]]
    structural_pass = all(checks.values()) and not errors
    transition_hash = transition_table_hash(transitions)
    state_hash = state_table_hash(states)
    combined_hash = hashlib.sha256(
        _canonical_csv(STATE_FIELDS, states) + _canonical_csv(TRANSITION_FIELDS, transitions)
    ).hexdigest()
    report: dict[str, Any] = {
        "package": "bms-state-machine",
        "pass": structural_pass,
        "engineering_package_pass": structural_pass,
        "release_ready": release_ready,
        "order_release_ready": order_release_ready,
        "status": status,
        "verification_status": verification_status,
        "physical_validation": physical_validation,
        "physical_results": physical_results,
        "checks": {
            **state_report["checks"],
            **transition_report["checks"],
            **checks,
        },
        "errors": errors,
        "state_count": len(states),
        "transition_count": len(transitions),
        "event_count": len({row["event"] for row in transitions}),
        "states": [row["state"] for row in states],
        "events": sorted({row["event"] for row in transitions}),
        "state_table_sha256": state_hash,
        "transition_table_sha256": transition_hash,
        "state_machine_sha256": combined_hash,
        "release_blockers": [
            "supplier pack and BMS configuration evidence",
            "electrical and safety owner approval",
            "physical fault-injection and thermal/precharge measurements",
        ],
        "note": (
            "A structural pass confirms the reviewable CSV baseline only. It is not a battery safety certification, "
            "physical HIL result, or production release decision."
        ),
    }
    if write_report:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="JSON report path")
    args = parser.parse_args(argv)
    report = validate(output_path=args.output)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
