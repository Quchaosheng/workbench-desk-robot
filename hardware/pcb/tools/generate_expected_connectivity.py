from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from design_data import COMPONENTS

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "expected-connectivity.json"


def natural_key(value: str) -> tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value))


def build_expected_connectivity() -> dict[str, dict[str, str | None]]:
    connectivity: dict[str, dict[str, str | None]] = {}
    for component in sorted(COMPONENTS, key=lambda item: natural_key(item.reference)):
        if component.reference in connectivity:
            raise ValueError(f"duplicate component reference: {component.reference}")
        connectivity[component.reference] = {
            pin: component.pins[pin] for pin in sorted(component.pins, key=natural_key)
        }
    return connectivity


def write_expected_connectivity(output: Path = OUTPUT) -> None:
    content = json.dumps(build_expected_connectivity(), indent=2) + "\n"
    output.write_text(content, encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate expected PCB connectivity from the controlled design data")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    write_expected_connectivity(args.output)
    print(f"saved {args.output}")


if __name__ == "__main__":
    main()
