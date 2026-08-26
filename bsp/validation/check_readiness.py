"""Check that BSP readiness remains evidence-bound and fail closed."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def check() -> list[str]:
    readiness = yaml.safe_load((ROOT / "bsp/readiness.yaml").read_text(encoding="utf-8"))
    errors: list[str] = []
    gates = readiness.get("gates", [])
    allowed = set(readiness.get("allowed_statuses", []))
    if len(gates) != 9 or len({gate.get("id") for gate in gates}) != 9:
        errors.append("BSP readiness must contain nine unique gates")
    if any(gate.get("status") not in allowed for gate in gates):
        errors.append("BSP readiness contains an uncontrolled status")
    if any(not gate.get("owner") or not gate.get("requirement") for gate in gates):
        errors.append("every BSP gate requires an owner and requirement")
    for gate in gates:
        evidence = gate.get("evidence")
        if gate.get("status") == "PASS":
            path = ROOT / evidence if evidence and evidence != "NOT_ATTACHED" else None
            if path is None or not path.is_file():
                errors.append(f"{gate.get('id')} claims PASS without repository evidence")
        elif evidence == "NOT_ATTACHED" and gate.get("status") not in {"BLOCKED", "NOT_EXECUTED"}:
            errors.append(f"{gate.get('id')} lacks evidence but is not blocked")
    if readiness.get("physical_release_ready") is not False:
        errors.append("physical release must remain false before bring-up")
    return errors


if __name__ == "__main__":
    failures = check()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        raise SystemExit(1)
    print("BSP readiness validation passed")
