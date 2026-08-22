from __future__ import annotations

import argparse
from pathlib import Path

CLASS_LAYERS = {
    "POWER_48V": ("F.Cu", "In2.Cu", "B.Cu"),
    "PRIMARY_GROUND": ("F.Cu", "In1.Cu", "B.Cu"),
    "POWER_12V": ("F.Cu", "In2.Cu", "B.Cu"),
    "POWER_JETSON": ("F.Cu", "In3.Cu", "B.Cu"),
    "POWER_3V3": ("F.Cu", "In5.Cu", "B.Cu"),
    "POWER_CAN_ISO": ("F.Cu", "In5.Cu", "B.Cu"),
    "CAN_FD": ("F.Cu",),
    "CLOCK_LOCAL": ("F.Cu",),
}


def block_end(text: str, start: int) -> int:
    if text[start] != "(":
        raise ValueError("S-expression block must begin with '('")
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError(f"unterminated S-expression at byte {start}")


def constrain_text(text: str, constraints: dict[str, tuple[str, ...]] = CLASS_LAYERS) -> str:
    for class_name, layers in constraints.items():
        marker = f"(class {class_name} "
        start = text.find(marker)
        if start < 0 or text.find(marker, start + 1) >= 0:
            raise ValueError(f"expected exactly one DSN class {class_name!r}")
        end = block_end(text, start)
        class_block = text[start:end]
        circuit_start = class_block.find("(circuit")
        if circuit_start < 0:
            raise ValueError(f"DSN class {class_name!r} has no circuit block")
        circuit_end = block_end(class_block, circuit_start)
        circuit_block = class_block[circuit_start:circuit_end]
        if "(use_layer " in circuit_block:
            raise ValueError(f"DSN class {class_name!r} already has a use_layer constraint")
        closing_line = class_block.rfind("\n", circuit_start, circuit_end - 1) + 1
        indent = class_block[closing_line : circuit_end - 1]
        if indent.strip():
            raise ValueError(f"unexpected DSN circuit formatting for {class_name!r}")
        layer_rule = f'{indent}  (use_layer {" ".join(layers)})\n'
        class_block = class_block[:closing_line] + layer_rule + class_block[closing_line:]
        text = text[:start] + class_block + text[end:]
    return text


def constrain(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(constrain_text(text), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply controlled layer constraints to a KiCad Specctra DSN")
    parser.add_argument("dsn", type=Path)
    args = parser.parse_args()
    constrain(args.dsn)
    print(f"constrained {args.dsn}: {len(CLASS_LAYERS)} net classes")


if __name__ == "__main__":
    main()
