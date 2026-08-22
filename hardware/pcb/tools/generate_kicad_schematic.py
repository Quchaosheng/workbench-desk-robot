from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from design_data import BLOCK_ORDER, COMPONENTS, CUSTOM_SYMBOLS, Component, Pin
from deterministic_ids import DeterministicUuidFactory, normalize_line_endings
from kiutils.items.common import Effects, Fill, Font, Justify, Position, Property, Stroke, TitleBlock
from kiutils.items.schitems import (
    Connection,
    HierarchicalSheetInstance,
    LocalLabel,
    NoConnect,
    SymbolProjectInstance,
    SymbolProjectPath,
    Text,
)
from kiutils.items.syitems import SyRect
from kiutils.schematic import Schematic
from kiutils.symbol import Symbol, SymbolLib, SymbolPin

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "kicad" / "controller.kicad_sch"
SYMBOL_LIBRARY = ROOT / "kicad" / "controller.kicad_sym"
SYMBOL_TABLE = ROOT / "kicad" / "sym-lib-table"
KICAD_DEMO_CANDIDATES = (
    ROOT / "kicad" / "controller.kicad_sch",
    Path.home() / "AppData/Local/Programs/KiCad/10.0/share/kicad/demos/ecc83/ecc83-pp.kicad_sch",
)
KICAD_DEMO = next((path for path in KICAD_DEMO_CANDIDATES if path.is_file()), KICAD_DEMO_CANDIDATES[0])


BLOCK_AREAS = {
    "INPUT PROTECTION": (15.0, 18.0, 205.0, 175.0),
    "ISOLATED POWER": (225.0, 18.0, 395.0, 105.0),
    "JETSON EFUSE": (405.0, 18.0, 600.0, 150.0),
    "3V3 POWER": (610.0, 18.0, 826.0, 150.0),
    "POWER OUTPUTS": (225.0, 115.0, 395.0, 180.0),
    "MCU AND BACKPLANE": (15.0, 190.0, 400.0, 570.0),
    "ISOLATED CAN FD": (410.0, 170.0, 605.0, 405.0),
    "HARDWIRED ESTOP": (615.0, 170.0, 826.0, 500.0),
    "TEST ACCESS": (410.0, 425.0, 605.0, 570.0),
}
GRID = 1.27
UUID_FACTORY = DeterministicUuidFactory("controller.kicad_sch")


def uid() -> str:
    return UUID_FACTORY.next()


def snap(value: float) -> float:
    return round(value / GRID) * GRID


def effects(size: float = 1.27, *, hide: bool = False) -> Effects:
    return Effects(
        font=Font(height=size, width=size),
        justify=Justify(horizontally="left", vertically="bottom"),
        hide=hide,
    )


def property_(key: str, value: str, x: float, y: float, *, hide: bool = False) -> Property:
    return Property(key=key, value=value, position=Position(x, y, 0), effects=effects(hide=hide))


def symbol_geometry(pins: list[Pin]) -> tuple[float, float, dict[str, Position]]:
    left = [pin for pin in pins if pin.side == "left"]
    right = [pin for pin in pins if pin.side == "right"]
    row_count = max(len(left), len(right), 1)
    pitch = 2.54
    body_width = 38.10 if len(pins) >= 50 else 22.86
    body_height = max(7.62, (row_count - 1) * pitch + 5.08)
    endpoints: dict[str, Position] = {}
    for side_pins, side, angle in [(left, "left", 0), (right, "right", 180)]:
        top_y = (len(side_pins) - 1) * pitch / 2
        x = -(body_width / 2 + 2.54) if side == "left" else body_width / 2 + 2.54
        for index, pin in enumerate(side_pins):
            endpoints[pin.number] = Position(x, top_y - index * pitch, angle)
    return body_width, body_height, endpoints


def make_symbol(name: str, reference_prefix: str, pins: list[Pin]) -> Symbol:
    width, height, endpoints = symbol_geometry(pins)
    label_effects = Effects(font=Font(height=1.0, width=1.0))
    body = Symbol(
        entryName=name,
        unitId=0,
        styleId=1,
        graphicItems=[
            SyRect(
                start=Position(-width / 2, -height / 2),
                end=Position(width / 2, height / 2),
                stroke=Stroke(width=0.254, type="default"),
                fill=Fill(type="background"),
            )
        ],
    )
    pin_unit = Symbol(entryName=name, unitId=1, styleId=1)
    for pin in pins:
        position = endpoints[pin.number]
        pin_unit.pins.append(
            SymbolPin(
                electricalType="passive",
                graphicalStyle="line",
                position=position,
                length=2.54,
                name=pin.name,
                nameEffects=label_effects,
                number=pin.number,
                numberEffects=label_effects,
            )
        )
    return Symbol(
        libraryNickname="controller",
        entryName=name,
        pinNames=True,
        pinNamesOffset=1.016,
        inBom=True,
        onBoard=True,
        properties=[
            property_("Reference", reference_prefix, width / 2 + 3.0, -height / 2),
            property_("Value", name, width / 2 + 3.0, -height / 2 + 2.54),
            property_("Footprint", "", 0, 0, hide=True),
            property_("Datasheet", "", 0, 0, hide=True),
            property_("Description", "Workbench-1 controlled symbol", 0, 0, hide=True),
        ],
        units=[body, pin_unit],
    )


def build_symbol_library() -> dict[str, tuple[Symbol, dict[str, Position], float, float]]:
    result: dict[str, tuple[Symbol, dict[str, Position], float, float]] = {}
    library = SymbolLib(version="20231120", generator="kicad_symbol_editor")
    for name, (reference_prefix, pins) in CUSTOM_SYMBOLS.items():
        symbol = make_symbol(name, reference_prefix, pins)
        width, height, endpoints = symbol_geometry(pins)
        result[name] = (symbol, endpoints, width + 8.0, height + 4.0)
        library.symbols.append(deepcopy(symbol))
    library.to_file(str(SYMBOL_LIBRARY), encoding="utf-8")
    SYMBOL_TABLE.write_text(
        '(sym_lib_table\n  (lib (name "controller")(type "KiCad")'
        '(uri "${KIPRJMOD}/controller.kicad_sym")(options "")(descr ""))\n)\n',
        encoding="utf-8",
    )
    return result


def component_positions(
    geometries: dict[str, tuple[Symbol, dict[str, Position], float, float]],
) -> dict[str, tuple[float, float]]:
    positions: dict[str, tuple[float, float]] = {}
    for block in BLOCK_ORDER:
        left, top, right, bottom = BLOCK_AREAS[block]
        x = left + 7.0
        y = top + 14.0
        row_height = 0.0
        for component in [item for item in COMPONENTS if item.block == block]:
            _, _, width, height = geometries[component.symbol]
            if x + width > right - 5.0:
                x = left + 7.0
                y += row_height + 7.0
                row_height = 0.0
            if y + height > bottom - 5.0:
                raise ValueError(f"schematic block {block} is too small for {component.reference}")
            positions[component.reference] = (snap(x + width / 2), snap(y + height / 2))
            x += width + 7.0
            row_height = max(row_height, height)
    return positions


def base_schematic() -> Schematic:
    schematic = Schematic.from_file(str(KICAD_DEMO), encoding="utf-8")
    schematic.libSymbols.clear()
    schematic.schematicSymbols.clear()
    schematic.junctions.clear()
    schematic.noConnects.clear()
    schematic.busEntries.clear()
    schematic.busAliases.clear()
    schematic.graphicalItems.clear()
    schematic.shapes.clear()
    schematic.images.clear()
    schematic.texts.clear()
    schematic.textBoxes.clear()
    schematic.labels.clear()
    schematic.globalLabels.clear()
    schematic.hierarchicalLabels.clear()
    schematic.netclassFlags.clear()
    schematic.sheets.clear()
    schematic.symbolInstances.clear()
    schematic.uuid = uid()
    schematic.sheetInstances = [HierarchicalSheetInstance(instancePath="/", page="1")]
    schematic.paper.paperSize = "A1"
    schematic.titleBlock = TitleBlock(
        title="Workbench-1 controller EVT detailed schematic",
        date="2026-08-21",
        revision="EVT1-DESIGN-REVIEW",
        company="Workbench-1",
        comments={
            1: "Component-level design candidate; do not order before signed AVL and safety review",
            2: "Physical bring-up, thermal, EMC, DFM and safety validation remain external gates",
        },
    )
    return schematic


def pin_outward_endpoint(origin: Position, relative: Position, distance: float = 2.54) -> Position:
    vectors = {0: (-1, 0), 90: (0, -1), 180: (1, 0), 270: (0, 1)}
    dx, dy = vectors[int(relative.angle or 0)]
    return Position(origin.X + relative.X + dx * distance, origin.Y - relative.Y + dy * distance)


def placed_pin_position(origin: Position, relative: Position) -> Position:
    return Position(origin.X + relative.X, origin.Y - relative.Y)


def add_labelled_wire(schematic: Schematic, start: Position, end: Position, net: str) -> None:
    schematic.graphicalItems.append(
        Connection(type="wire", points=[start, end], stroke=Stroke(width=0, type="solid"), uuid=uid())
    )
    schematic.labels.append(LocalLabel(text=net, position=Position(end.X, end.Y, 0), effects=effects(1.0), uuid=uid()))


def add_component(
    schematic: Schematic,
    component: Component,
    x: float,
    y: float,
    endpoints: dict[str, Position],
) -> None:
    symbol_pins = set(endpoints)
    component_pins = set(component.pins)
    if symbol_pins != component_pins:
        missing = sorted(symbol_pins - component_pins)
        unexpected = sorted(component_pins - symbol_pins)
        raise ValueError(
            f"{component.reference} pin declaration does not match {component.symbol}: "
            f"missing={missing}, unexpected={unexpected}"
        )
    source = Schematic.from_file(str(KICAD_DEMO), encoding="utf-8")
    template = next(
        (item for item in source.schematicSymbols if item.entryName in {"R", "RESISTOR"}),
        None,
    )
    if template is None:
        raise ValueError(f"schematic template {KICAD_DEMO} has no resistor symbol")
    symbol = deepcopy(template)
    symbol.libraryNickname = "controller"
    symbol.entryName = component.symbol
    symbol.position = Position(x, y, 0)
    symbol.unit = 1
    symbol.inBom = True
    symbol.onBoard = True
    symbol.dnp = component.dnp
    symbol.uuid = uid()
    symbol.properties = [
        property_("Reference", component.reference, x + 3.0, y - 3.0),
        property_("Value", component.value, x + 3.0, y - 0.5),
        property_("Footprint", component.footprint, x, y, hide=True),
        property_("Datasheet", component.datasheet, x, y, hide=True),
        property_("Description", component.note, x, y, hide=True),
        property_("MPN", component.mpn, x, y, hide=True),
    ]
    symbol.pins = {number: uid() for number in endpoints}
    symbol.instances = [
        SymbolProjectInstance(
            name="controller",
            paths=[SymbolProjectPath(sheetInstancePath=f"/{schematic.uuid}", reference=component.reference, unit=1)],
        )
    ]
    schematic.schematicSymbols.append(symbol)

    origin = Position(x, y)
    for number, relative in endpoints.items():
        start = placed_pin_position(origin, relative)
        net = component.pins.get(number)
        if net is None:
            schematic.noConnects.append(NoConnect(position=start, uuid=uid()))
            continue
        add_labelled_wire(schematic, start, pin_outward_endpoint(origin, relative), net)


def add_block_titles(schematic: Schematic) -> None:
    for block, (left, top, _, _) in BLOCK_AREAS.items():
        schematic.texts.append(
            Text(
                text=block,
                position=Position(left + 2.0, top + 5.0, 0),
                effects=effects(1.8),
                uuid=uid(),
            )
        )


def build_schematic() -> Schematic:
    UUID_FACTORY.reset()
    geometries = build_symbol_library()
    positions = component_positions(geometries)
    schematic = base_schematic()
    schematic.libSymbols.extend(deepcopy(item[0]) for item in geometries.values())
    add_block_titles(schematic)
    for component in COMPONENTS:
        x, y = positions[component.reference]
        add_component(schematic, component, x, y, geometries[component.symbol][1])
    return schematic


def main() -> None:
    schematic = build_schematic()
    schematic.to_file(str(OUTPUT), encoding="utf-8")
    normalize_line_endings(OUTPUT)
    print(f"saved {OUTPUT}: {len(schematic.schematicSymbols)} symbols")


if __name__ == "__main__":
    main()
