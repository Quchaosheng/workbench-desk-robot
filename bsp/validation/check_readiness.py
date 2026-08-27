"""Check that BSP readiness remains evidence-bound and fail closed."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_GATE_IDS = {
    "BSP-GATE-ARCH",
    "BSP-GATE-SELECTION",
    "BSP-GATE-CARRIER",
    "BSP-GATE-MCU",
    "BSP-GATE-SAFETY",
    "BSP-GATE-IMAGE",
    "BSP-GATE-CAN",
    "BSP-GATE-VALIDATION",
    "BSP-GATE-CAMERA",
}
BLOCKED_STATUS = "REPOSITORY_BASELINE_READY_PHYSICAL_BRINGUP_BLOCKED"
READY_STATUS = "PHYSICAL_BRINGUP_EVIDENCE_COMPLETE"


def validate_readiness(readiness: object, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    if not isinstance(readiness, dict):
        return ["BSP readiness must be a mapping"]
    gates = readiness.get("gates", [])
    allowed = set(readiness.get("allowed_statuses", []))
    if not isinstance(gates, list) or any(not isinstance(gate, dict) for gate in gates):
        return ["BSP readiness gates must be a list of mappings"]
    gate_ids = [gate.get("id") for gate in gates]
    if len(gates) != len(EXPECTED_GATE_IDS) or set(gate_ids) != EXPECTED_GATE_IDS:
        errors.append("BSP readiness must contain the exact nine controlled gates")
    if any(gate.get("status") not in allowed for gate in gates):
        errors.append("BSP readiness contains an uncontrolled status")
    if any(not gate.get("owner") or not gate.get("requirement") for gate in gates):
        errors.append("every BSP gate requires an owner and requirement")
    for gate in gates:
        evidence = gate.get("evidence")
        if gate.get("status") == "PASS":
            path = _repository_evidence_path(root, evidence)
            if path is None:
                errors.append(f"{gate.get('id')} claims PASS without repository evidence")
        elif evidence == "NOT_ATTACHED" and gate.get("status") not in {"BLOCKED", "NOT_EXECUTED"}:
            errors.append(f"{gate.get('id')} lacks evidence but is not blocked")
    all_pass = bool(gates) and all(gate.get("status") == "PASS" for gate in gates)
    release_ready = readiness.get("physical_release_ready")
    expected_status = READY_STATUS if all_pass else BLOCKED_STATUS
    if release_ready is not all_pass:
        errors.append("physical_release_ready must equal the all-gates-PASS result")
    if readiness.get("status") != expected_status:
        errors.append(f"BSP package status must be {expected_status}")
    return errors


def _repository_evidence_path(root: Path, evidence: object) -> Path | None:
    if not isinstance(evidence, str) or not evidence or evidence == "NOT_ATTACHED":
        return None
    relative = Path(evidence)
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        return None
    root = root.resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def check() -> list[str]:
    readiness = yaml.safe_load((ROOT / "bsp/readiness.yaml").read_text(encoding="utf-8"))
    return validate_readiness(readiness)


if __name__ == "__main__":
    failures = check()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        raise SystemExit(1)
    print("BSP readiness validation passed")
