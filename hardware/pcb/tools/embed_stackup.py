from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOARD = ROOT / "kicad" / "controller.kicad_pcb"
DEFAULT_SPEC = ROOT / "electrical-spec.json"
EXPECTED_COPPER_LAYERS = ("F.Cu", *[f"In{index}.Cu" for index in range(1, 7)], "B.Cu")
DIELECTRIC_TYPES = ("prepreg", "core", "prepreg", "core", "prepreg", "core", "prepreg")


@dataclass(frozen=True)
class CopperLayerSpec:
    name: str
    copper_oz: Decimal
    copper_thickness_mm: Decimal
    dielectric_to_next_mm: Decimal


@dataclass(frozen=True)
class BoardStackupSpec:
    copper_layers: tuple[CopperLayerSpec, ...]
    board_thickness_mm: Decimal
    copper_finish: str


@dataclass(frozen=True)
class EmbeddedLayer:
    name: str
    layer_type: str
    thickness_mm: Decimal | None
    material: str | None


@dataclass(frozen=True)
class EmbeddedStackup:
    layers: tuple[EmbeddedLayer, ...]
    copper_finish: str | None
    dielectric_constraints: str | None


def _matching_paren(text: str, opening: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError(f"unbalanced S-expression at byte {opening}")


def _list_head(text: str, span: tuple[int, int]) -> str:
    position = span[0] + 1
    while position < span[1] and text[position].isspace():
        position += 1
    end = position
    while end < span[1] and not text[end].isspace() and text[end] not in "()":
        end += 1
    return text[position:end]


def _list_body_start(text: str, span: tuple[int, int]) -> int:
    position = span[0] + 1
    while position < span[1] and text[position].isspace():
        position += 1
    while position < span[1] and not text[position].isspace() and text[position] not in "()":
        position += 1
    return position


def _skip_atom(text: str, position: int, stop: int) -> int:
    if text[position] != '"':
        while position < stop and not text[position].isspace() and text[position] not in "()":
            position += 1
        return position
    position += 1
    escaped = False
    while position < stop:
        char = text[position]
        position += 1
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return position
    raise ValueError("unterminated string atom")


def _direct_child_spans(text: str, parent: tuple[int, int]):
    position = _list_body_start(text, parent)
    stop = parent[1] - 1
    while position < stop:
        while position < stop and text[position].isspace():
            position += 1
        if position >= stop:
            break
        if text[position] == "(":
            end = _matching_paren(text, position)
            if end > parent[1]:
                raise ValueError("child expression extends beyond its parent")
            yield position, end
            position = end
        else:
            position = _skip_atom(text, position, stop)


def _direct_child(text: str, parent: tuple[int, int], head: str) -> tuple[int, int] | None:
    matches = [span for span in _direct_child_spans(text, parent) if _list_head(text, span) == head]
    if len(matches) > 1:
        raise ValueError(f"multiple {head} expressions found in {_list_head(text, parent)}")
    return matches[0] if matches else None


def _root_span(text: str) -> tuple[int, int]:
    opening = len(text) - len(text.lstrip())
    if opening >= len(text) or text[opening] != "(":
        raise ValueError("board does not start with an S-expression")
    span = opening, _matching_paren(text, opening)
    if _list_head(text, span) != "kicad_pcb" or text[span[1] :].strip():
        raise ValueError("file is not one complete kicad_pcb expression")
    return span


def _required_child(text: str, parent: tuple[int, int], head: str) -> tuple[int, int]:
    child = _direct_child(text, parent, head)
    if child is None:
        raise ValueError(f"{_list_head(text, parent)} has no {head} expression")
    return child


def _first_value(text: str, span: tuple[int, int]) -> str:
    position = _list_body_start(text, span)
    stop = span[1] - 1
    while position < stop and text[position].isspace():
        position += 1
    end = _skip_atom(text, position, stop)
    token = text[position:end]
    if token.startswith('"'):
        value = json.loads(token)
        if not isinstance(value, str):
            raise ValueError(f"expected string value in {_list_head(text, span)}")
        return value
    return token


def load_stackup_spec(path: Path = DEFAULT_SPEC) -> BoardStackupSpec:
    data = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)
    raw_layers = data["stackup"]
    names = tuple(layer["kicad_layer"] for layer in raw_layers)
    if names != EXPECTED_COPPER_LAYERS:
        raise ValueError(f"electrical spec copper layers are {names}, expected {EXPECTED_COPPER_LAYERS}")
    if len(raw_layers) - 1 != len(DIELECTRIC_TYPES):
        raise ValueError("eight copper layers require seven dielectric layers")

    copper_per_oz = data["dfm"]["nominal_copper_thickness_per_oz_mm"]
    layers = tuple(
        CopperLayerSpec(
            name=layer["kicad_layer"],
            copper_oz=layer["copper_oz"],
            copper_thickness_mm=layer["copper_oz"] * copper_per_oz,
            dielectric_to_next_mm=layer["dielectric_to_next_mm"],
        )
        for layer in raw_layers
    )
    if layers[-1].dielectric_to_next_mm != 0:
        raise ValueError("bottom copper layer must not declare a following dielectric")
    board_thickness = data["dfm"]["board_thickness_mm"]
    nominal_thickness = sum(
        (layer.copper_thickness_mm + layer.dielectric_to_next_mm for layer in layers),
        start=Decimal(0),
    )
    tolerance = data["dfm"]["stackup_math_tolerance_mm"]
    if abs(nominal_thickness - board_thickness) > tolerance:
        raise ValueError(f"nominal stackup is {nominal_thickness} mm, outside {board_thickness} +/- {tolerance} mm")
    copper_finish = data["dfm"]["surface_finish"]
    if not copper_finish:
        raise ValueError("surface finish must be controlled")
    return BoardStackupSpec(
        copper_layers=layers,
        board_thickness_mm=board_thickness,
        copper_finish=copper_finish,
    )


def read_declared_copper_layers(path: Path) -> tuple[str, ...]:
    text = path.read_bytes().decode("utf-8")
    layers_span = _required_child(text, _root_span(text), "layers")
    copper_layers = []
    pattern = re.compile(r'^\(\s*\d+\s+"([^"]+\.Cu)"\s+(?:signal|power|mixed|jumper)(?:\s+"[^"]*")?\s*\)$', re.DOTALL)
    for child in _direct_child_spans(text, layers_span):
        match = pattern.fullmatch(text[child[0] : child[1]])
        if match:
            copper_layers.append(match.group(1))
    return tuple(copper_layers)


def _render_stackup(spec: BoardStackupSpec, newline: str) -> str:
    lines = [
        "\t\t(stackup",
        '\t\t\t(layer "F.SilkS"',
        '\t\t\t\t(type "Top Silk Screen")',
        "\t\t\t)",
        '\t\t\t(layer "F.Paste"',
        '\t\t\t\t(type "Top Solder Paste")',
        "\t\t\t)",
        '\t\t\t(layer "F.Mask"',
        '\t\t\t\t(type "Top Solder Mask")',
        "\t\t\t)",
    ]
    for index, layer in enumerate(spec.copper_layers):
        lines.extend(
            (
                f'\t\t\t(layer "{layer.name}"',
                '\t\t\t\t(type "copper")',
                f"\t\t\t\t(thickness {layer.copper_thickness_mm:.3f})",
                "\t\t\t)",
            )
        )
        if index < len(DIELECTRIC_TYPES):
            lines.extend(
                (
                    f'\t\t\t(layer "dielectric {index + 1}"',
                    f'\t\t\t\t(type "{DIELECTRIC_TYPES[index]}")',
                    '\t\t\t\t(color "FR4 natural")',
                    f"\t\t\t\t(thickness {layer.dielectric_to_next_mm:.2f})",
                    '\t\t\t\t(material "FR-4")',
                    "\t\t\t)",
                )
            )
    # KiCad includes explicit solder-mask thickness in the overall board
    # thickness. Leave it unset until the supplier closes the finished build.
    lines.extend(
        (
            '\t\t\t(layer "B.Mask"',
            '\t\t\t\t(type "Bottom Solder Mask")',
            "\t\t\t)",
            '\t\t\t(layer "B.Paste"',
            '\t\t\t\t(type "Bottom Solder Paste")',
            "\t\t\t)",
            '\t\t\t(layer "B.SilkS"',
            '\t\t\t\t(type "Bottom Silk Screen")',
            "\t\t\t)",
            f'\t\t\t(copper_finish "{spec.copper_finish}")',
            "\t\t\t(dielectric_constraints no)",
            "\t\t)",
        )
    )
    return newline.join(lines)


def read_embedded_stackup(path: Path) -> EmbeddedStackup:
    text = path.read_bytes().decode("utf-8")
    setup = _required_child(text, _root_span(text), "setup")
    stackup = _required_child(text, setup, "stackup")
    layers = []
    for layer_span in _direct_child_spans(text, stackup):
        if _list_head(text, layer_span) != "layer":
            continue
        layer_type_span = _required_child(text, layer_span, "type")
        thickness_span = _direct_child(text, layer_span, "thickness")
        material_span = _direct_child(text, layer_span, "material")
        layers.append(
            EmbeddedLayer(
                name=_first_value(text, layer_span),
                layer_type=_first_value(text, layer_type_span),
                thickness_mm=Decimal(_first_value(text, thickness_span)) if thickness_span else None,
                material=_first_value(text, material_span) if material_span else None,
            )
        )
    copper_finish_span = _direct_child(text, stackup, "copper_finish")
    constraints_span = _direct_child(text, stackup, "dielectric_constraints")
    return EmbeddedStackup(
        layers=tuple(layers),
        copper_finish=_first_value(text, copper_finish_span) if copper_finish_span else None,
        dielectric_constraints=_first_value(text, constraints_span) if constraints_span else None,
    )


def validate_embedded_stackup(path: Path, spec: BoardStackupSpec | None = None) -> EmbeddedStackup:
    spec = spec or load_stackup_spec()
    declared_layers = read_declared_copper_layers(path)
    expected_copper = tuple(layer.name for layer in spec.copper_layers)
    if declared_layers != expected_copper:
        raise ValueError(f"board copper layers are {declared_layers}, expected {expected_copper}")

    text = path.read_bytes().decode("utf-8")
    general = _required_child(text, _root_span(text), "general")
    board_thickness = Decimal(_first_value(text, _required_child(text, general, "thickness")))
    if board_thickness != spec.board_thickness_mm:
        raise ValueError(f"board thickness is {board_thickness} mm, expected {spec.board_thickness_mm} mm")

    embedded = read_embedded_stackup(path)
    expected_layers = [
        EmbeddedLayer("F.SilkS", "Top Silk Screen", None, None),
        EmbeddedLayer("F.Paste", "Top Solder Paste", None, None),
        EmbeddedLayer("F.Mask", "Top Solder Mask", None, None),
    ]
    for index, layer in enumerate(spec.copper_layers):
        expected_layers.append(EmbeddedLayer(layer.name, "copper", layer.copper_thickness_mm, None))
        if index < len(DIELECTRIC_TYPES):
            expected_layers.append(
                EmbeddedLayer(
                    f"dielectric {index + 1}",
                    DIELECTRIC_TYPES[index],
                    layer.dielectric_to_next_mm,
                    "FR-4",
                )
            )
    expected_layers.extend(
        (
            EmbeddedLayer("B.Mask", "Bottom Solder Mask", None, None),
            EmbeddedLayer("B.Paste", "Bottom Solder Paste", None, None),
            EmbeddedLayer("B.SilkS", "Bottom Silk Screen", None, None),
        )
    )
    if embedded.layers != tuple(expected_layers):
        raise ValueError("embedded physical stackup does not match the controlled electrical specification")
    if embedded.copper_finish != spec.copper_finish:
        raise ValueError(f"embedded copper finish is {embedded.copper_finish}, expected {spec.copper_finish}")
    if embedded.dielectric_constraints != "no":
        raise ValueError("nominal stackup must remain open for supplier dielectric closure")
    return embedded


def embed_stackup(path: Path = DEFAULT_BOARD, spec_path: Path = DEFAULT_SPEC) -> BoardStackupSpec:
    spec = load_stackup_spec(spec_path)
    declared_layers = read_declared_copper_layers(path)
    expected_layers = tuple(layer.name for layer in spec.copper_layers)
    if declared_layers != expected_layers:
        raise ValueError(f"board copper layers are {declared_layers}, expected {expected_layers}")

    text = path.read_bytes().decode("utf-8")
    root = _root_span(text)
    general = _required_child(text, root, "general")
    board_thickness = Decimal(_first_value(text, _required_child(text, general, "thickness")))
    if board_thickness != spec.board_thickness_mm:
        raise ValueError(f"board thickness is {board_thickness} mm, expected {spec.board_thickness_mm} mm")
    setup = _required_child(text, root, "setup")
    existing = _direct_child(text, setup, "stackup")
    newline = "\r\n" if "\r\n" in text else "\n"
    rendered = _render_stackup(spec, newline)
    if existing:
        start, end = existing
        line_start = text.rfind("\n", 0, start) + 1
        if text[line_start:start].strip():
            raise ValueError("stackup expression does not start on its own line")
        text = text[:line_start] + rendered + text[end:]
    else:
        setup_line_end = text.find("\n", setup[0], setup[1])
        if setup_line_end < 0:
            raise ValueError("setup expression has no stackup insertion line")
        text = text[: setup_line_end + 1] + rendered + newline + text[setup_line_end + 1 :]
    encoded = text.encode("utf-8")
    if encoded != path.read_bytes():
        path.write_bytes(encoded)
    validate_embedded_stackup(path, spec)
    return spec


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed the controlled nominal stackup in a KiCad board")
    parser.add_argument("board", nargs="?", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    args = parser.parse_args()
    spec = embed_stackup(args.board, args.spec)
    print(
        f"embedded {len(spec.copper_layers)} copper layers and "
        f"{len(spec.copper_layers) - 1} dielectrics in {args.board} ({spec.board_thickness_mm} mm nominal)"
    )


if __name__ == "__main__":
    main()
