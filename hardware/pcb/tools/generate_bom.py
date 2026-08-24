from __future__ import annotations

import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

from design_data import COMPONENTS

ROOT = Path(__file__).resolve().parents[1]
BOM = ROOT / "fabrication" / "bom.csv"
APPROVALS = ROOT / "component-approval-register.csv"
SIGNATURES = ROOT / "component-approval-signatures.csv"
APPROVAL_DATA_FIELDS = ("decision", "approved_mpn", "datasheet_revision", "approved_by", "approved_at", "evidence_ref")


def natural_key(reference: str) -> tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", reference))


def approval_owner(references: list[str], block: str) -> str:
    if block == "HARDWIRED ESTOP":
        return "Safety + Electrical + Procurement Owners"
    if block == "MCU AND BACKPLANE":
        return "Firmware + Electrical + Procurement Owners"
    if "U7" in references:
        return "Electrical + Safety + Procurement Owners"
    if "J1" in references or "J3" in references:
        return "System + Electrical + Procurement Owners"
    return "Electrical + Procurement Owners"


def build_rows() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    grouped: dict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
    for component in COMPONENTS:
        gate = "APPROVED" if component.reference.startswith("TP") else "OWNER_APPROVAL_REQUIRED"
        key = (component.block, component.value, component.footprint, component.mpn, gate)
        grouped[key].append(component.reference)

    bom_rows = []
    approval_rows = []
    for (block, value, footprint, mpn, gate), references in grouped.items():
        references.sort(key=natural_key)
        reference_text = " ".join(references)
        candidate = mpn or f"{value}; {footprint}"
        bom_rows.append(
            {
                "reference": reference_text,
                "quantity": str(len(references)),
                "function": block.lower().replace(" ", "_"),
                "design_candidate": candidate,
                "package_or_module": footprint,
                "procurement_gate": gate,
            }
        )
        if gate != "APPROVED":
            approval_rows.append(
                {
                    "reference": reference_text,
                    "candidate": candidate,
                    "required_approver": approval_owner(references, block),
                    "decision": "PENDING",
                    "approved_mpn": "",
                    "datasheet_revision": "",
                    "approved_by": "",
                    "approved_at": "",
                    "evidence_ref": "",
                }
            )

    bom_rows.append(
        {
            "reference": "H1 H2 H3 H4",
            "quantity": "4",
            "function": "mounting",
            "design_candidate": "M3 insulated standoff",
            "package_or_module": "3.2mm NPTH",
            "procurement_gate": "APPROVED",
        }
    )
    bom_rows.sort(key=lambda row: natural_key(row["reference"].split()[0]))
    approval_rows.sort(key=lambda row: natural_key(row["reference"].split()[0]))
    return bom_rows, approval_rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _has_recorded_approval_data(rows: list[dict[str, str]]) -> bool:
    """Return true when a register contains a decision or any signed evidence."""
    return any(
        row.get("decision", "PENDING") != "PENDING"
        or any(row.get(field, "").strip() for field in APPROVAL_DATA_FIELDS[1:])
        for row in rows
    )


def initialize_approval_register(
    rows: list[dict[str, str]], approval_path: Path = APPROVALS, signature_path: Path = SIGNATURES
) -> bool:
    """Create a pristine register without ever replacing human-owned decisions."""
    if approval_path.exists():
        with approval_path.open(newline="", encoding="utf-8") as handle:
            existing = list(csv.DictReader(handle))
        if _has_recorded_approval_data(existing):
            raise RuntimeError(
                f"refusing to overwrite recorded approvals in {approval_path}; use an explicit ECO migration"
            )
        if existing != rows:
            raise RuntimeError(
                f"refusing to replace a manually changed pending register at {approval_path}; use an explicit ECO"
            )
        if signature_path.exists():
            with signature_path.open(newline="", encoding="utf-8") as handle:
                signatures = list(csv.DictReader(handle))
            if _has_recorded_approval_data(signatures) or any(
                row.get("signed_by", "").strip()
                or row.get("signed_at", "").strip()
                or row.get("evidence_ref", "").strip()
                for row in signatures
            ):
                raise RuntimeError(
                    f"refusing to reinitialize {approval_path}; signed role evidence exists in {signature_path}"
                )
        return False
    write_csv(approval_path, rows)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the controlled EVT BOM")
    parser.add_argument(
        "--initialize-approval-register",
        action="store_true",
        help="overwrite the approval register with PENDING rows; never use after owner decisions are recorded",
    )
    args = parser.parse_args()
    bom_rows, approval_rows = build_rows()
    initialized = None
    if args.initialize_approval_register:
        initialized = initialize_approval_register(approval_rows)
    write_csv(BOM, bom_rows)
    print(f"saved {BOM}: {len(bom_rows)} grouped lines")
    if args.initialize_approval_register:
        action = "initialized" if initialized else "left unchanged"
        print(f"{action} {APPROVALS}: {len(approval_rows)} pending lines")


if __name__ == "__main__":
    main()
