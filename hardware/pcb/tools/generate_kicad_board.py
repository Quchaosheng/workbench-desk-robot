from __future__ import annotations

import argparse
import heapq
import math
import sys
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

try:
    import pcbnew
except ImportError as exc:
    raise SystemExit("Run with KiCad's bundled Python interpreter (bin/python.exe)") from exc

from design_data import BLOCK_ORDER, COMPONENTS, Component
from deterministic_ids import normalize_kicad_board
from embed_stackup import embed_stackup

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "kicad" / "controller.kicad_pcb"
ROUTING_SESSION = ROOT / "kicad" / "controller.ses"
GLOBAL_FOOTPRINTS = Path.home() / "AppData/Local/Programs/KiCad/10.0/share/kicad/footprints"
CUSTOM_FOOTPRINTS = ROOT / "kicad" / "WB.pretty"
GRID_MM = 0.5
BOARD_WIDTH_MM = 160.0
BOARD_HEIGHT_MM = 130.0
COPPER_LAYER_COUNT = 8
COPPER_LAYER_NAMES = (
    "F.Cu",
    "In1.Cu",
    "In2.Cu",
    "In3.Cu",
    "In4.Cu",
    "In5.Cu",
    "In6.Cu",
    "B.Cu",
)
LAYERS = [
    pcbnew.F_Cu,
    pcbnew.In1_Cu,
    pcbnew.In2_Cu,
    pcbnew.In3_Cu,
    pcbnew.In4_Cu,
    pcbnew.In5_Cu,
    pcbnew.In6_Cu,
    pcbnew.B_Cu,
]
PLANE_NETS = {
    "VBAT_RAW",
    "VBAT_FUSED",
    "FET_COMMON",
    "INPUT_SENSE",
    "VBAT_PROTECTED",
    "GND_PWR",
    "12V_ISO",
    "JETSON_12V",
    "3V3_LOGIC",
    "GND",
    "GND_CAN_ISO",
}
MCU_LOCAL_NETS = {
    "SPI_SCLK_MCU",
    "SPI_MOSI_MCU",
    "SPI_MISO_MCU",
    "MOTOR_CS0_MCU",
    "MOTOR_CS1_MCU",
    "MOTOR_CS2_MCU",
    "MOTOR_CS3_MCU",
    "MOTOR_CS4_MCU",
    "MOTOR_CS5_MCU",
    "I2C_SCL_MCU",
    "I2C_SDA_MCU",
    "UART_TX_MCU",
    "UART_RX_MCU",
}
PREFERRED_LAYER_BY_NET = {
    "SPI_SCLK_MCU": 0,
    "SPI_MOSI_MCU": 0,
    "SPI_MISO_MCU": 0,
    "MOTOR_CS0_MCU": 0,
    "MOTOR_CS1_MCU": 0,
    "MOTOR_CS2_MCU": 0,
    "MOTOR_CS3_MCU": 0,
    "MOTOR_CS4_MCU": 0,
    "MOTOR_CS5_MCU": 0,
    "CAN_TX": 1,
    "CAN_RX": 2,
    "MCU_RESET": 3,
    "I2C_SDA_MCU": 0,
    "I2C_SCL_MCU": 0,
    "UART_RX_MCU": 0,
    "UART_TX_MCU": 0,
    "BOOT0": 3,
    "OSC_IN": 4,
    "OSC_OUT": 5,
    "ESTOP_SENSE": 1,
    "RELAY_A_NC": 2,
    "RELAY_B_NC": 3,
    "ESTOP_A_MON": 4,
    "ESTOP_B_MON": 5,
    "MOTOR_ENABLE_REQ": 4,
    "MOTOR_ENABLE_SAFE": 7,
}


BOARD_AREAS = {
    "INPUT PROTECTION": (7.0, 8.0, 44.0, 80.0),
    "JETSON EFUSE": (86.0, 6.0, 123.0, 44.0),
    "3V3 POWER": (86.0, 46.0, 123.0, 68.0),
    "POWER OUTPUTS": (86.0, 70.0, 123.0, 83.0),
    "MCU AND BACKPLANE": (78.0, 85.0, 136.0, 127.0),
    "ISOLATED CAN FD": (125.0, 6.0, 157.0, 82.0),
    "HARDWIRED ESTOP": (44.0, 85.0, 77.0, 127.0),
}


FIXED_POSITIONS = {
    "J1": (11.0, 14.5, 0.0),
    "F1": (22.0, 13.0, 0.0),
    "D1": (32.0, 10.5, 0.0),
    "Q1": (22.0, 21.0, 180.0),
    "Q2": (30.0, 21.0, 0.0),
    "RS1": (39.5, 21.0, 0.0),
    "U1": (34.5, 27.7, 0.0),
    "RG1": (22.0, 26.5, 0.0),
    "CG1": (25.5, 26.5, 0.0),
    "RUV1": (10.0, 26.5, 0.0),
    "RUV2": (14.0, 26.5, 0.0),
    "RUV3": (18.0, 30.5, 0.0),
    "RSH1": (36.0, 34.0, 0.0),
    "C1": (31.0, 36.0, 0.0),
    "U2": (66.0, 27.0, 0.0),
    "C2": (42.0, 31.5, 270.0),
    "C3": (93.0, 27.0, 90.0),
    "C6": (92.0, 43.5, 0.0),
    "C7": (87.5, 56.5, 0.0),
    "C8": (93.0, 56.5, 0.0),
    "K1": (29.0, 93.0, 0.0),
    "K2": (29.0, 114.0, 0.0),
    "D3": (20.0, 82.5, 0.0),
    "D4": (20.0, 103.5, 0.0),
    "U8": (53.0, 91.0, 0.0),
    "J10": (71.0, 91.0, 0.0),
    "J11": (53.0, 107.0, 0.0),
    "J12": (71.0, 107.0, 0.0),
    "U5": (106.0, 103.0, 0.0),
    "J4": (82.0, 97.0, 0.0),
    "J13": (134.0, 115.5, 0.0),
    "Y1": (92.0, 103.0, 0.0),
    "CY1": (88.5, 102.5, 90.0),
    "CY2": (92.0, 106.5, 0.0),
    "R54": (118.0, 111.0, 0.0),
    "C19": (122.0, 111.0, 0.0),
    "R43": (118.0, 115.0, 0.0),
    "R55": (124.0, 114.0, 0.0),
    "R56": (128.0, 114.0, 0.0),
    "R30": (100.0, 118.0, 0.0),
    "R31": (104.0, 118.0, 0.0),
    "R32": (108.0, 118.0, 0.0),
    "R33": (112.0, 118.0, 0.0),
    "R34": (116.0, 118.0, 0.0),
    "R35": (120.0, 118.0, 0.0),
    "R36": (124.0, 118.0, 0.0),
    "R37": (100.0, 123.0, 0.0),
    "R38": (104.0, 123.0, 0.0),
    "R39": (108.0, 123.0, 0.0),
    "R40": (112.0, 123.0, 0.0),
    "R41": (116.0, 123.0, 0.0),
    "R42": (120.0, 123.0, 0.0),
    "C9": (95.5, 99.3, 270.0),
    "C10": (95.5, 102.5, 270.0),
    "C11": (95.5, 105.7, 270.0),
    "C12": (95.5, 108.9, 270.0),
    "C13": (100.75, 113.0, 180.0),
    "C14": (111.75, 113.0, 180.0),
    "C15": (116.0, 97.25, 90.0),
    "C16": (100.25, 93.0, 0.0),
    "C17": (108.0, 91.5, 0.0),
    "U6": (135.0, 40.0, 0.0),
    "U7": (132.0, 24.0, 0.0),
    "C40": (127.75, 36.2, 90.0),
    "C41": (142.25, 36.2, 90.0),
    "C44": (142.25, 42.55, 90.0),
    "C42": (133.25, 18.0, 0.0),
    "C43": (144.7, 18.0, 0.0),
    "L1": (144.0, 48.0, 0.0),
    "D2": (150.0, 53.0, 0.0),
    "R58": (138.0, 79.5, 90.0),
    "JP1": (138.0, 85.0, 90.0),
    "J5": (149.5, 64.0, 0.0),
    "J6": (149.5, 76.0, 0.0),
    "J2": (118.0, 76.0, 0.0),
    "J3": (102.39, 10.775, 0.0),
    "U3": (111.825, 11.825, 0.0),
    "C4": (110.5, 6.5, 0.0),
    "C5": (119.0, 20.5, 0.0),
    "R48": (108.0, 18.0, 0.0),
    "C18": (112.0, 18.0, 0.0),
    "RPG1": (108.0, 22.0, 0.0),
    "RPG2": (112.0, 22.0, 0.0),
    "R59": (108.0, 26.0, 0.0),
    "R60": (112.0, 26.0, 0.0),
    "TP1": (8.0, 82.0, 0.0),
    "TP2": (62.0, 82.0, 0.0),
    "TP3": (72.0, 82.0, 0.0),
    "TP4": (88.0, 82.0, 0.0),
    "TP5": (94.0, 82.0, 0.0),
    "TP6": (147.0, 87.5, 0.0),
    "TP7": (152.0, 87.5, 0.0),
    "TP8": (104.0, 82.0, 0.0),
}


TRACK_WIDTHS = {
    "VBAT_RAW": 2.5,
    "VBAT_FUSED": 2.5,
    "FET_COMMON": 2.5,
    "INPUT_SENSE": 2.5,
    "VBAT_PROTECTED": 2.5,
    "GND_PWR": 2.5,
    "12V_ISO": 2.5,
    "JETSON_12V": 1.5,
    "3V3_LOGIC": 0.8,
    "GND": 0.8,
    "5V_CAN_ISO": 0.5,
    "GND_CAN_ISO": 0.5,
    "ESTOP_12V": 0.5,
    "ESTOP_CH_A_RETURN": 0.5,
    "ESTOP_CH_B_RETURN": 0.5,
    "RESET_CH_A_RETURN": 0.5,
    "RESET_CH_B_RETURN": 0.5,
    "MOTOR_ENABLE_SAFE": 0.5,
}


def point(x: float, y: float):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def mm(value: int) -> float:
    return pcbnew.ToMM(value)


def grid(value: float) -> int:
    return round(value / GRID_MM)


def grid_point(ix: int, iy: int):
    return point(ix * GRID_MM, iy * GRID_MM)


def layer_set(*layers: int):
    result = pcbnew.LSET()
    for layer in layers:
        result.AddLayer(layer)
    return result


def add_outline(board):
    corners = [(0, 0), (BOARD_WIDTH_MM, 0), (BOARD_WIDTH_MM, BOARD_HEIGHT_MM), (0, BOARD_HEIGHT_MM), (0, 0)]
    for start, end in pairwise(corners):
        edge = pcbnew.PCB_SHAPE(board)
        edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(point(*start))
        edge.SetEnd(point(*end))
        edge.SetLayer(pcbnew.Edge_Cuts)
        edge.SetWidth(pcbnew.FromMM(0.1))
        board.Add(edge)


def add_mounting_hole(board, reference: str, x: float, y: float):
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference(reference)
    footprint.SetValue("M3_NPTH")
    footprint.SetPosition(point(x, y))
    footprint.Reference().SetVisible(False)
    footprint.Value().SetVisible(False)
    pad = pcbnew.PAD(footprint)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(point(3.2, 3.2))
    pad.SetDrillSize(point(3.2, 3.2))
    pad.SetLayerSet(layer_set(pcbnew.F_Mask, pcbnew.B_Mask))
    pad.SetPosition(point(x, y))
    footprint.Add(pad)
    board.Add(footprint)


def add_mounting_keepout(board, x: float, y: float, diameter: float = 8.0):
    """Reserve washer/tool clearance from copper, routing, vias and pours."""
    keepout = pcbnew.ZONE(board)
    keepout.SetIsRuleArea(True)
    keepout.SetLayerSet(pcbnew.LSET.AllCuMask())
    keepout.SetDoNotAllowTracks(True)
    keepout.SetDoNotAllowVias(True)
    keepout.SetDoNotAllowZoneFills(True)
    outline = keepout.Outline()
    outline.NewOutline()
    radius = diameter / 2.0
    for index in range(32):
        angle = 2.0 * math.pi * index / 32
        outline.Append(point(x + radius * math.cos(angle), y + radius * math.sin(angle)))
    outline.Append(point(x + radius, y))
    board.Add(keepout)


def add_isolation_keepout(
    board,
    footprints: dict[str, object],
    reference: str,
    logic_pad_numbers: tuple[str, ...],
    field_pad_numbers: tuple[str, ...],
):
    logic_pads = [pad_by_number(footprints, reference, number) for number in logic_pad_numbers]
    field_pads = [pad_by_number(footprints, reference, number) for number in field_pad_numbers]
    logic_edge = max(mm(pad.GetPosition().x) + mm(pad.GetSize().x) / 2 for pad in logic_pads)
    field_edge = min(mm(pad.GetPosition().x) - mm(pad.GetSize().x) / 2 for pad in field_pads)
    top = min(mm(pad.GetPosition().y) - mm(pad.GetSize().y) / 2 for pad in (*logic_pads, *field_pads))
    bottom = max(mm(pad.GetPosition().y) + mm(pad.GetSize().y) / 2 for pad in (*logic_pads, *field_pads))
    keepout = pcbnew.ZONE(board)
    keepout.SetIsRuleArea(True)
    keepout.SetLayerSet(pcbnew.LSET.AllCuMask())
    keepout.SetDoNotAllowTracks(True)
    keepout.SetDoNotAllowVias(True)
    keepout.SetDoNotAllowZoneFills(True)
    outline = keepout.Outline()
    outline.NewOutline()
    for vertex in ((logic_edge, top), (field_edge, top), (field_edge, bottom), (logic_edge, bottom)):
        outline.Append(point(*vertex))
    outline.Append(point(logic_edge, top))
    board.Add(keepout)


def add_u6_isolation_keepout(board, footprints: dict[str, object]):
    add_isolation_keepout(
        board,
        footprints,
        "U6",
        tuple(str(number) for number in range(1, 9)),
        tuple(str(number) for number in range(9, 17)),
    )


def add_u7_isolation_keepout(board, footprints: dict[str, object]):
    add_isolation_keepout(board, footprints, "U7", ("1", "2"), ("5", "7"))


def add_silk_text(board, text: str, x: float, y: float, size: float = 1.0):
    item = pcbnew.PCB_TEXT(board)
    item.SetText(text)
    item.SetPosition(point(x, y))
    item.SetLayer(pcbnew.F_SilkS)
    item.SetTextSize(point(size, size))
    item.SetTextThickness(pcbnew.FromMM(0.15))
    board.Add(item)


def add_fab_text(board, text: str, x: float, y: float, size: float = 0.8):
    item = pcbnew.PCB_TEXT(board)
    item.SetText(text)
    item.SetPosition(point(x, y))
    item.SetLayer(pcbnew.F_Fab)
    item.SetTextSize(point(size, size))
    item.SetTextThickness(pcbnew.FromMM(0.12))
    board.Add(item)


def add_silk_line(board, start: tuple[float, float], end: tuple[float, float], width: float = 0.2):
    item = pcbnew.PCB_SHAPE(board)
    item.SetShape(pcbnew.SHAPE_T_SEGMENT)
    item.SetStart(point(*start))
    item.SetEnd(point(*end))
    item.SetLayer(pcbnew.F_SilkS)
    item.SetWidth(pcbnew.FromMM(width))
    board.Add(item)


def add_board_markings(board):
    title_block = board.GetTitleBlock()
    title_block.SetTitle("Workbench-1 Controller")
    title_block.SetRevision("EVT1")
    board.SetTitleBlock(title_block)
    add_silk_text(board, "WORKBENCH-1 CONTROLLER EVT1", 80, 3, 1.2)
    add_silk_text(board, "48V PRIMARY", 24, 78, 0.9)
    add_silk_text(board, "12V / LOGIC SECONDARY", 92, 78, 0.9)
    add_silk_text(board, "ISOLATED CAN FD", 148, 94, 0.8)
    add_silk_text(board, "U2 LAND PATTERN TBD", 66, 23.5, 0.8)
    add_silk_text(board, "DO NOT FIT", 66, 30.5, 0.8)
    add_silk_text(board, "DO NOT ORDER WITHOUT RELEASE APPROVAL", 80, 127, 0.8)
    add_fab_text(board, "FAB: U3 HDI 9x 0.45/0.15 FILL/CAP/PLANARIZE", 80, 63, 0.7)
    add_fab_text(board, "FAB: ENIG | THK 1.60 +/- 0.16 MM (MASK EXCL)", 80, 66, 0.7)
    # Keep the barrier warning vertical so its silk does not cross the copper gap.
    barrier = pcbnew.PCB_TEXT(board)
    barrier.SetText("PRIMARY | SECONDARY")
    barrier.SetPosition(point(51, 64))
    barrier.SetLayer(pcbnew.F_SilkS)
    barrier.SetTextSize(point(0.8, 0.8))
    barrier.SetTextThickness(pcbnew.FromMM(0.12))
    barrier.SetTextAngle(pcbnew.ANGLE_90)
    board.Add(barrier)


def configure_routing_classes(board):
    """Declare fabrication-current net classes before exporting a DSN.

    Freerouting otherwise falls back to its 0.20 mm default for every net,
    which can produce a DRC-clean but thermally undersized power route.
    """
    settings = board.GetDesignSettings()
    net_settings = settings.m_NetSettings

    def add_class(name: str, width: float, clearance: float, via: tuple[float, float]):
        netclass = pcbnew.NETCLASS(name)
        netclass.SetTrackWidth(pcbnew.FromMM(width))
        netclass.SetClearance(pcbnew.FromMM(clearance))
        netclass.SetViaDiameter(pcbnew.FromMM(via[0]))
        netclass.SetViaDrill(pcbnew.FromMM(via[1]))
        net_settings.SetNetclass(name, netclass)

    add_class("POWER_48V", 2.5, 0.15, (0.8, 0.4))
    add_class("PRIMARY_GROUND", 2.5, 0.15, (0.8, 0.4))
    add_class("POWER_12V", 2.5, 0.15, (0.8, 0.4))
    add_class("POWER_JETSON", 1.5, 0.15, (0.8, 0.4))
    add_class("POWER_3V3", 0.8, 0.15, (0.6, 0.3))
    add_class("POWER_CAN_ISO", 0.5, 0.15, (0.6, 0.3))
    add_class("CAN_FD", 0.25, 0.15, (0.6, 0.3))
    add_class("CLOCK_LOCAL", 0.25, 0.15, (0.6, 0.3))
    for net in ("VBAT_RAW", "VBAT_FUSED", "FET_COMMON", "INPUT_SENSE", "VBAT_PROTECTED"):
        net_settings.SetNetclassPatternAssignment(net, "POWER_48V")
    net_settings.SetNetclassPatternAssignment("GND_PWR", "PRIMARY_GROUND")
    net_settings.SetNetclassPatternAssignment("12V_ISO", "POWER_12V")
    net_settings.SetNetclassPatternAssignment("JETSON_12V", "POWER_JETSON")
    net_settings.SetNetclassPatternAssignment("3V3_LOGIC", "POWER_3V3")
    net_settings.SetNetclassPatternAssignment("5V_CAN_ISO", "POWER_CAN_ISO")
    for net in ("CANH", "CANL", "CANH_RAW", "CANL_RAW"):
        net_settings.SetNetclassPatternAssignment(net, "CAN_FD")
    for net in ("OSC_IN", "OSC_OUT"):
        net_settings.SetNetclassPatternAssignment(net, "CLOCK_LOCAL")
    net_settings.RecomputeEffectiveNetclasses()


def footprint_path(footprint_id: str) -> tuple[Path, str]:
    library, separator, name = footprint_id.partition(":")
    if not separator:
        raise ValueError(f"invalid footprint id: {footprint_id}")
    if library == "WB":
        return CUSTOM_FOOTPRINTS, name
    return GLOBAL_FOOTPRINTS / f"{library}.pretty", name


def load_footprint(component: Component):
    library, name = footprint_path(component.footprint)
    footprint = pcbnew.PCB_IO_KICAD_SEXPR().FootprintLoad(str(library), name, False)
    if footprint is None:
        raise ValueError(f"unable to load {component.footprint} for {component.reference}")
    footprint.SetReference(component.reference)
    footprint.SetValue(component.value)
    if component.dnp:
        footprint.SetDNP(True)
    footprint.Value().SetVisible(False)
    show_reference = component.reference.startswith(("U", "J", "K", "F", "Q", "L", "TP"))
    footprint.Reference().SetVisible(show_reference and component.reference not in {"U1", "J11", "JP1"})
    footprint.Reference().SetTextSize(point(0.8, 0.8))
    footprint.Reference().SetTextThickness(pcbnew.FromMM(0.12))
    return footprint


def footprint_size(footprint) -> tuple[float, float, float, float]:
    box = footprint.GetBoundingBox(False, False)
    return mm(box.GetX()), mm(box.GetY()), mm(box.GetWidth()), mm(box.GetHeight())


def place_at_bbox(footprint, left: float, top: float):
    box_x, box_y, _, _ = footprint_size(footprint)
    current = footprint.GetPosition()
    footprint.SetPosition(point(mm(current.x) + left - box_x, mm(current.y) + top - box_y))


def pack_area(
    items: list[tuple[Component, object]],
    area: tuple[float, float, float, float],
    obstacles: list[object],
):
    left, top, right, bottom = area
    gap = 0.8
    ordered = sorted(items, key=lambda item: footprint_size(item[1])[3], reverse=True)
    for component, footprint in ordered:
        _, _, width, height = footprint_size(footprint)
        placed = False
        y = top
        while y + height <= bottom and not placed:
            x = left
            while x + width <= right:
                proposed = (x - gap, y - gap, x + width + gap, y + height + gap)
                occupied = False
                for obstacle in obstacles:
                    box = obstacle.GetBoundingBox(False, False)
                    obstacle_rect = (mm(box.GetX()), mm(box.GetY()), mm(box.GetRight()), mm(box.GetBottom()))
                    if not (
                        proposed[2] <= obstacle_rect[0]
                        or proposed[0] >= obstacle_rect[2]
                        or proposed[3] <= obstacle_rect[1]
                        or proposed[1] >= obstacle_rect[3]
                    ):
                        occupied = True
                        break
                if not occupied:
                    place_at_bbox(footprint, x, y)
                    obstacles.append(footprint)
                    placed = True
                    break
                x += GRID_MM
            y += GRID_MM
        if not placed:
            raise ValueError(f"board area {component.block} is too small for {component.reference}")


def place_footprints(board) -> dict[str, object]:
    loaded = {component.reference: (component, load_footprint(component)) for component in COMPONENTS}
    for reference, (x, y, rotation) in FIXED_POSITIONS.items():
        footprint = loaded[reference][1]
        footprint.SetPosition(point(x, y))
        footprint.SetOrientationDegrees(rotation)
    for block in BLOCK_ORDER:
        if block in {"ISOLATED POWER", "TEST ACCESS"}:
            continue
        pack_area(
            [item for reference, item in loaded.items() if item[0].block == block and reference not in FIXED_POSITIONS],
            BOARD_AREAS[block],
            [item[1] for reference, item in loaded.items() if reference in FIXED_POSITIONS],
        )
    for _, footprint in loaded.values():
        board.Add(footprint)
    return {reference: footprint for reference, (_, footprint) in loaded.items()}


def make_nets(board) -> dict[str, object]:
    names = sorted({net for component in COMPONENTS for net in component.pins.values() if net is not None})
    result = {}
    for name in names:
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        result[name] = net
    return result


def assign_pad_nets(footprints: dict[str, object], nets: dict[str, object]) -> dict[str, list[object]]:
    components = {component.reference: component for component in COMPONENTS}
    net_pads: dict[str, list[object]] = defaultdict(list)
    for reference, footprint in footprints.items():
        component = components[reference]
        pads_by_number: dict[str, list[object]] = defaultdict(list)
        for pad in footprint.Pads():
            pads_by_number[pad.GetNumber()].append(pad)

        mapping = dict(component.pins)
        if reference in {"Q1", "Q2"}:
            mapping = {
                "1": component.pins["2"],
                "2": component.pins["2"],
                "3": component.pins["2"],
                "4": component.pins["1"],
                "5": component.pins["3"],
            }
        missing = [number for number, net in component.pins.items() if net is not None and number not in pads_by_number]
        if missing and reference not in {"Q1", "Q2"}:
            raise ValueError(f"{reference} is missing footprint pads {missing}")
        for number, pads in pads_by_number.items():
            net_name = mapping.get(number)
            if net_name is None:
                continue
            for pad in pads:
                pad.SetNet(nets[net_name])
                net_pads[net_name].append(pad)
    return net_pads


def add_track(board, net, start, end, layer: int, width: float):
    if start == end:
        return
    track = pcbnew.PCB_TRACK(board)
    track.SetNet(net)
    track.SetStart(start)
    track.SetEnd(end)
    track.SetLayer(layer)
    track.SetWidth(pcbnew.FromMM(width))
    board.Add(track)


def add_via(board, net, position, diameter: float = 0.8, drill: float = 0.4):
    via = pcbnew.PCB_VIA(board)
    via.SetNet(net)
    via.SetPosition(position)
    via.SetWidth(pcbnew.FromMM(diameter))
    via.SetDrill(pcbnew.FromMM(drill))
    board.Add(via)


def add_blind_via(board, net, position, top_layer: int, bottom_layer: int, diameter: float = 0.6, drill: float = 0.3):
    via = pcbnew.PCB_VIA(board)
    via.SetNet(net)
    via.SetPosition(position)
    via.SetWidth(pcbnew.FromMM(diameter))
    via.SetDrill(pcbnew.FromMM(drill))
    via.SetViaType(pcbnew.VIATYPE_BLIND)
    via.SetLayerPair(top_layer, bottom_layer)
    board.Add(via)


def pad_by_number(footprints: dict[str, object], reference: str, number: str):
    pads = [pad for pad in footprints[reference].Pads() if pad.GetNumber() == number]
    if not pads:
        raise ValueError(f"{reference} has no pad {number}")
    return pads[0]


def add_polyline(board, net, vertices: list[object], width: float, layer: int = pcbnew.F_Cu):
    for start, end in pairwise(vertices):
        add_track(board, net, start, end, layer, width)


def add_via_ring(board, net, center, pitch: float = 1.5):
    for dx in (-pitch, 0.0, pitch):
        for dy in (-pitch, 0.0, pitch):
            if dx == 0.0 and dy == 0.0:
                continue
            add_via(board, net, point(mm(center.x) + dx, mm(center.y) + dy), 0.8, 0.4)


def remove_net_tracks(board, net_names: set[str]):
    removed = []
    for item in list(board.GetTracks()):
        if item.GetNetname() in net_names:
            board.Remove(item)
            removed.append(item)
    return removed


def remove_segment(
    board,
    net_name: str,
    first: tuple[float, float],
    second: tuple[float, float],
):
    expected = {
        tuple(round(value, 4) for value in first),
        tuple(round(value, 4) for value in second),
    }
    for item in list(board.GetTracks()):
        if item.GetNetname() != net_name or item.Type() == pcbnew.PCB_VIA_T:
            continue
        actual = {
            (round(mm(item.GetStart().x), 4), round(mm(item.GetStart().y), 4)),
            (round(mm(item.GetEnd().x), 4), round(mm(item.GetEnd().y), 4)),
        }
        if actual == expected:
            board.Remove(item)
            return
    raise ValueError(f"expected routed segment is missing: {net_name} {first}->{second}")


def replace_local_oscillator_routing(board, nets: dict[str, object], footprints: dict[str, object]):
    """Keep the crystal loop on F.Cu while giving its load capacitors direct returns."""
    remove_net_tracks(board, {"OSC_IN", "OSC_OUT"})

    for net_name, first, second in (
        ("GND", (96.7755, 101.5), (98.325, 101.5)),
        ("GND", (96.7755, 101.5), (96.7755, 101.3505)),
        ("GND", (96.7755, 101.3505), (95.5, 100.075)),
        ("3V3_LOGIC", (95.5, 101.725), (94.4151, 100.6401)),
        ("3V3_LOGIC", (94.4151, 100.6401), (94.4151, 99.0739)),
        ("GND", (95.5, 103.275), (94.7474, 104.0276)),
        ("GND", (94.7474, 104.0276), (94.7474, 106.475)),
        ("GND", (94.7474, 106.475), (95.5, 106.475)),
        ("GND", (94.7474, 106.475), (94.7474, 106.5)),
    ):
        remove_segment(board, net_name, first, second)

    u5_ground = pad_by_number(footprints, "U5", "10").GetPosition()
    c9_ground = pad_by_number(footprints, "C9", "2").GetPosition()
    c10_power = pad_by_number(footprints, "C10", "1").GetPosition()
    c10_ground = pad_by_number(footprints, "C10", "2").GetPosition()
    c11_ground = pad_by_number(footprints, "C11", "2").GetPosition()
    add_track(board, nets["GND"], u5_ground, point(101.0, 101.5), pcbnew.F_Cu, 0.25)
    add_via(board, nets["GND"], point(101.0, 101.5), 0.6, 0.3)
    add_track(board, nets["GND"], c9_ground, point(94.5, 100.075), pcbnew.F_Cu, 0.25)
    add_via(board, nets["GND"], point(94.5, 100.075), 0.6, 0.3)
    add_track(board, nets["3V3_LOGIC"], c10_power, point(96.2, 101.725), pcbnew.F_Cu, 0.25)
    add_via(board, nets["3V3_LOGIC"], point(96.2, 101.725), 0.6, 0.3)
    add_track(board, nets["GND"], c10_ground, point(95.5, 102.8), pcbnew.F_Cu, 0.25)
    add_via(board, nets["GND"], point(95.5, 102.8), 0.6, 0.3)
    add_track(board, nets["GND"], c11_ground, point(95.5, 106.2), pcbnew.F_Cu, 0.25)
    add_via(board, nets["GND"], point(95.5, 106.2), 0.6, 0.3)

    cy1_ground = pad_by_number(footprints, "CY1", "2").GetPosition()
    cy1_ground_via = point(mm(cy1_ground.x), mm(cy1_ground.y) - 1.625)
    add_track(board, nets["GND"], cy1_ground, cy1_ground_via, pcbnew.F_Cu, 0.25)
    add_via(board, nets["GND"], cy1_ground_via, 0.6, 0.3)
    cy2_ground = pad_by_number(footprints, "CY2", "2").GetPosition()
    cy2_ground_via = point(mm(cy2_ground.x) - 0.575, mm(cy2_ground.y) + 0.7)
    add_track(board, nets["GND"], cy2_ground, cy2_ground_via, pcbnew.F_Cu, 0.25)
    add_via(board, nets["GND"], cy2_ground_via, 0.6, 0.3)

    osc_input = pad_by_number(footprints, "U5", "12").GetPosition()
    osc_output = pad_by_number(footprints, "U5", "13").GetPosition()
    crystal_input = pad_by_number(footprints, "Y1", "1").GetPosition()
    crystal_output = pad_by_number(footprints, "Y1", "2").GetPosition()
    input_cap = pad_by_number(footprints, "CY1", "1").GetPosition()
    output_cap = pad_by_number(footprints, "CY2", "1").GetPosition()
    add_polyline(
        board,
        nets["OSC_IN"],
        [
            osc_input,
            point(97.2, 102.5),
            point(97.2, 100.9),
            point(89.8, 100.9),
            point(89.8, 103.85),
            crystal_input,
            input_cap,
        ],
        0.2,
    )
    add_polyline(
        board,
        nets["OSC_OUT"],
        [
            osc_output,
            point(97.55, 102.9),
            point(96.45, 102.8),
            point(96.45, 104.1),
            point(93.1, 104.1),
            crystal_output,
            point(91.225, 105.725),
            output_cap,
        ],
        0.2,
    )


def replace_field_can_routing(board, nets: dict[str, object], footprints: dict[str, object]):
    """Rebuild the field bus as a zero-via, same-layer branched pair."""
    removed_tracks = remove_net_tracks(board, {"CANH", "CANL", "CAN_TERM"})
    for reference, x, y, rotation in (
        ("R58", 143.0, 84.0, 0.0),
        ("JP1", 148.0, 84.0, 0.0),
        ("TP6", 141.0, 88.0, 0.0),
        ("TP7", 152.0, 88.0, 0.0),
    ):
        footprint = footprints[reference]
        footprint.SetPosition(point(x, y))
        footprint.SetOrientationDegrees(rotation)

    choke_high = pad_by_number(footprints, "L1", "4").GetPosition()
    choke_low = pad_by_number(footprints, "L1", "3").GetPosition()
    tvs_high = pad_by_number(footprints, "D2", "1").GetPosition()
    tvs_low = pad_by_number(footprints, "D2", "2").GetPosition()
    connector_1_high = pad_by_number(footprints, "J5", "1").GetPosition()
    connector_1_low = pad_by_number(footprints, "J5", "2").GetPosition()
    connector_2_high = pad_by_number(footprints, "J6", "1").GetPosition()
    connector_2_low = pad_by_number(footprints, "J6", "2").GetPosition()
    termination_high = pad_by_number(footprints, "R58", "1").GetPosition()
    termination_midpoint = pad_by_number(footprints, "R58", "2").GetPosition()
    termination_low = pad_by_number(footprints, "JP1", "2").GetPosition()
    termination_switch = pad_by_number(footprints, "JP1", "1").GetPosition()
    high_testpoint = pad_by_number(footprints, "TP6", "1").GetPosition()
    low_testpoint = pad_by_number(footprints, "TP7", "1").GetPosition()

    high_tvs_junction = point(150.25, 48.0)
    add_polyline(
        board,
        nets["CANH"],
        [
            choke_high,
            point(150.25, mm(choke_high.y)),
            high_tvs_junction,
            point(143.5, 48.0),
            point(143.5, 60.0),
            point(145.5, 60.0),
            connector_1_high,
        ],
        0.25,
    )
    add_polyline(
        board,
        nets["CANH"],
        [high_tvs_junction, point(150.25, mm(tvs_high.y)), tvs_high],
        0.25,
    )
    add_polyline(
        board,
        nets["CANH"],
        [
            connector_1_high,
            point(146.0, 64.5),
            point(146.0, 67.0),
            point(148.0, 69.0),
            point(149.25, 69.0),
            point(149.25, 72.0),
            point(148.0, 73.25),
            connector_2_high,
            point(146.0, mm(connector_2_high.y)),
            point(146.0, 79.0),
            point(148.0, 81.0),
            point(144.0, 81.0),
            termination_high,
        ],
        0.25,
    )
    add_polyline(
        board,
        nets["CANH"],
        [termination_high, point(140.5, 85.0), high_testpoint],
        0.25,
    )

    low_tvs_junction = point(145.0, mm(tvs_low.y))
    add_polyline(
        board,
        nets["CANL"],
        [
            choke_low,
            point(145.0, mm(choke_low.y)),
            low_tvs_junction,
            point(145.0, 57.0),
            point(145.75, 58.5),
            point(146.5, 58.5),
            point(146.5, 55.5),
            point(147.25, 55.5),
            point(147.25, 59.5),
            point(148.0, 59.5),
            point(148.0, 56.0),
            point(149.75, 57.0),
            point(149.75, 60.0),
            point(151.0, 61.25),
            connector_1_low,
        ],
        0.25,
    )
    add_track(board, nets["CANL"], low_tvs_junction, tvs_low, pcbnew.F_Cu, 0.25)
    add_polyline(
        board,
        nets["CANL"],
        [
            connector_1_low,
            point(153.0, mm(connector_1_low.y)),
            point(153.0, 67.0),
            point(151.0, 69.0),
            point(149.75, 69.0),
            point(149.75, 72.0),
            point(151.0, 73.25),
            connector_2_low,
            point(153.0, mm(connector_2_low.y)),
            point(153.0, 79.0),
            point(151.0, 81.0),
            point(151.0, 83.0),
            point(149.5, 85.0),
            termination_low,
        ],
        0.25,
    )
    add_polyline(
        board,
        nets["CANL"],
        [termination_low, point(150.0, 87.0), low_testpoint],
        0.25,
    )
    add_track(board, nets["CAN_TERM"], termination_midpoint, termination_switch, pcbnew.F_Cu, 0.25)
    del removed_tracks


def add_post_route_supplements(board, nets: dict[str, object], footprints: dict[str, object]):
    """Complete fine-pitch power-controller escapes after SES import."""
    u1_fused = pad_by_number(footprints, "U1", "5").GetPosition()
    fused_escape = point(mm(u1_fused.x), 30.0)
    fused_anchor = point(32.8658, 30.5828)
    add_track(board, nets["VBAT_FUSED"], u1_fused, fused_escape, pcbnew.F_Cu, 0.2)
    add_via(board, nets["VBAT_FUSED"], fused_escape, 0.6, 0.3)
    add_track(board, nets["VBAT_FUSED"], fused_escape, fused_anchor, pcbnew.In6_Cu, 0.2)

    u1_sense = pad_by_number(footprints, "U1", "9").GetPosition()
    sense_escape = point(38.5, 24.5)
    sense_anchor = point(33.5, 23.5)
    rs1_sense = pad_by_number(footprints, "RS1", "1").GetPosition()
    add_polyline(board, nets["INPUT_SENSE"], [u1_sense, point(38.5, mm(u1_sense.y)), sense_escape], 0.2)
    add_via(board, nets["INPUT_SENSE"], sense_escape, 0.6, 0.3)
    add_track(board, nets["INPUT_SENSE"], sense_escape, sense_anchor, pcbnew.In6_Cu, 0.2)
    add_via(board, nets["INPUT_SENSE"], sense_anchor, 0.6, 0.3)
    add_track(board, nets["INPUT_SENSE"], sense_anchor, rs1_sense, pcbnew.F_Cu, 0.2)

    u1_protected = pad_by_number(footprints, "U1", "8").GetPosition()
    protected_escape = point(40.5, 29.5)
    protected_anchor = point(40.4984, 30.4516)
    add_polyline(board, nets["VBAT_PROTECTED"], [u1_protected, point(40.5, mm(u1_protected.y)), protected_escape], 0.2)
    add_via(board, nets["VBAT_PROTECTED"], protected_escape, 0.6, 0.3)
    add_track(board, nets["VBAT_PROTECTED"], protected_escape, protected_anchor, pcbnew.In6_Cu, 0.2)


def add_isolated_power_via_arrays(board, nets: dict[str, object], footprints: dict[str, object]):
    remove_segment(board, "JETSON_12V", (100.89, 9.275), (79.7662, 30.3988))
    remove_segment(board, "JETSON_12V", (79.7662, 30.3988), (79.7662, 82.0))
    add_polyline(
        board,
        nets["JETSON_12V"],
        [
            point(100.89, 9.275),
            point(97.5, 9.275),
            point(97.5, 37.0),
            point(77.5, 37.0),
            point(77.5, 82.0),
            point(79.7662, 82.0),
        ],
        1.5,
        pcbnew.In3_Cu,
    )
    add_via_ring(board, nets["12V_ISO"], pad_by_number(footprints, "U2", "4").GetPosition())
    add_via_ring(board, nets["GND"], pad_by_number(footprints, "U2", "5").GetPosition())


def replace_u3_output_transfer(board, nets: dict[str, object]):
    """Give the 5 A eFuse output a short fanout and four layer-transfer vias."""
    segment_specs = [
        ("JETSON_FAULT_N", pcbnew.In2_Cu, (115.327, 9.4636), (113.3314, 7.468)),
        ("JETSON_FAULT_N", pcbnew.In2_Cu, (113.3314, 7.468), (93.043, 7.468)),
        ("JETSON_FAULT_N", pcbnew.In2_Cu, (115.327, 9.6435), (115.327, 9.4636)),
        ("JETSON_12V", pcbnew.F_Cu, (113.2675, 8.3611), (113.6421, 8.3611)),
        ("JETSON_12V", pcbnew.F_Cu, (113.6421, 8.3611), (113.975, 8.694)),
        ("JETSON_12V", pcbnew.F_Cu, (113.975, 8.694), (113.975, 10.575)),
        ("JETSON_12V", pcbnew.In3_Cu, (110.4829, 11.1457), (113.2675, 8.3611)),
    ]
    matches: list[object] = []
    unmatched = set(range(len(segment_specs)))
    output_via = None
    for item in list(board.GetTracks()):
        if isinstance(item, pcbnew.PCB_VIA):
            position = (round(mm(item.GetPosition().x), 4), round(mm(item.GetPosition().y), 4))
            if item.GetNetname() == "JETSON_12V" and position == (113.2675, 8.3611):
                output_via = item
            continue
        endpoints = {
            (round(mm(item.GetStart().x), 4), round(mm(item.GetStart().y), 4)),
            (round(mm(item.GetEnd().x), 4), round(mm(item.GetEnd().y), 4)),
        }
        for index in list(unmatched):
            net_name, layer, first, second = segment_specs[index]
            if item.GetNetname() == net_name and item.GetLayer() == layer and endpoints == {first, second}:
                matches.append(item)
                unmatched.remove(index)
                break
    if unmatched or output_via is None:
        missing = [segment_specs[index] for index in sorted(unmatched)]
        raise ValueError(f"U3 output source routing changed; missing segments={missing}, via={output_via is not None}")
    for item in [*matches, output_via]:
        board.Remove(item)

    add_polyline(
        board,
        nets["JETSON_FAULT_N"],
        [point(115.327, 9.6435), point(116.8, 8.1705), point(116.8, 5.0), point(93.043, 5.0), point(93.043, 7.468)],
        0.25,
        pcbnew.In2_Cu,
    )
    add_track(board, nets["JETSON_12V"], point(113.975, 10.575), point(113.975, 8.8), pcbnew.F_Cu, 1.1)
    for x, y in ((113.5, 8.1), (114.5, 8.1), (113.5, 8.8), (114.5, 8.8)):
        add_via(board, nets["JETSON_12V"], point(x, y), 0.8, 0.4)


def add_u3_exposed_pad_thermal_vias(board, nets: dict[str, object], footprints: dict[str, object]):
    """Connect the TPS26633 exposed pad to its adjacent ground reference."""
    exposed_pad = pad_by_number(footprints, "U3", "25")
    center = exposed_pad.GetPosition()
    # Shift the array away from the existing In1.Cu PGTH route while keeping
    # all nine laser microvias inside the 2.5 mm exposed-pad land.
    for dx in (-0.65, -0.25, 0.15):
        for dy in (-0.4, 0.0, 0.4):
            via = pcbnew.PCB_VIA(board)
            via.SetNet(nets["GND"])
            via.SetPosition(point(mm(center.x) + dx, mm(center.y) + dy))
            via.SetWidth(pcbnew.FromMM(0.45))
            via.SetDrill(pcbnew.FromMM(0.15))
            via.SetViaType(pcbnew.VIATYPE_MICROVIA)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.In1_Cu)
            board.Add(via)


def add_copper_zone(
    board,
    net,
    layer: int,
    vertices: list[tuple[float, float]],
    priority: int = 0,
):
    zone = pcbnew.ZONE(board)
    zone.SetNet(net)
    zone.SetLayerSet(layer_set(layer))
    zone.SetAssignedPriority(priority)
    zone.SetLocalClearance(pcbnew.FromMM(0.2))
    zone.SetMinThickness(pcbnew.FromMM(0.2))
    zone.SetThermalReliefGap(pcbnew.FromMM(0.3))
    zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.3))
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    outline = zone.Outline()
    outline.NewOutline()
    for vertex in vertices:
        outline.Append(point(*vertex))
    outline.Append(point(*vertices[0]))
    board.Add(zone)


def remove_single_layer_signal_vias(board):
    """Drop autorouter escape vias that never actually change layers."""
    tracks = [item for item in board.GetTracks() if not isinstance(item, pcbnew.PCB_VIA)]
    for via in [item for item in board.GetTracks() if isinstance(item, pcbnew.PCB_VIA)]:
        if via.GetNetname() in PLANE_NETS:
            continue
        position = via.GetPosition()
        connected_layers = {
            track.GetLayer()
            for track in tracks
            if track.GetNetCode() == via.GetNetCode() and (position == track.GetStart() or position == track.GetEnd())
        }
        if len(connected_layers) < 2:
            board.Remove(via)


def relocate_via_and_connected_ends(
    board,
    net_name: str,
    old_position: tuple[float, float],
    new_position: tuple[float, float],
    minimum_connected_ends: int = 2,
):
    old_point = point(*old_position)
    new_point = point(*new_position)
    matching_vias = [
        item
        for item in board.GetTracks()
        if isinstance(item, pcbnew.PCB_VIA) and item.GetNetname() == net_name and item.GetPosition() == old_point
    ]
    if len(matching_vias) != 1:
        raise ValueError(f"expected one {net_name} via at {old_position}, found {len(matching_vias)}")
    matching_vias[0].SetPosition(new_point)
    connected_end_count = 0
    for item in board.GetTracks():
        if isinstance(item, pcbnew.PCB_VIA) or item.GetNetname() != net_name:
            continue
        if item.GetStart() == old_point:
            item.SetStart(new_point)
            connected_end_count += 1
        if item.GetEnd() == old_point:
            item.SetEnd(new_point)
            connected_end_count += 1
    if connected_end_count < minimum_connected_ends:
        raise ValueError(f"{net_name} via at {old_position} has only {connected_end_count} connected track ends")


def relocate_u6_logic_vias(board):
    for net_name, old_position, new_position in (
        ("GND", (129.0483, 37.5192), (128.6, 37.5192)),
        ("CAN_TX", (129.0478, 38.7892), (128.6, 38.7892)),
        ("CAN_RX", (129.0248, 39.9408), (128.6, 39.9408)),
    ):
        relocate_via_and_connected_ends(board, net_name, old_position, new_position)


def reroute_u6_isolation_domains(board, nets: dict[str, object], footprints: dict[str, object]):
    for net_name, segments in {
        "CANH_RAW": (
            ((142.1084, 39.365), (139.65, 39.365)),
            ((143.7339, 40.9905), (142.1084, 39.365)),
            ((143.7339, 45.2161), (143.7339, 40.9905)),
            ((142.0, 46.95), (143.7339, 45.2161)),
        ),
        "CANL_RAW": (
            ((141.8513, 49.05), (138.2546, 45.4533)),
            ((138.2546, 45.4533), (138.2546, 41.6215)),
            ((138.2546, 41.6215), (139.2411, 40.635)),
            ((139.2411, 40.635), (139.65, 40.635)),
            ((142.0, 49.05), (141.8513, 49.05)),
        ),
    }.items():
        for first, second in segments:
            remove_segment(board, net_name, first, second)

    for net_name, u6_pad_number, choke_pad_number in (
        ("CANH_RAW", "13", "1"),
        ("CANL_RAW", "12", "2"),
    ):
        source_pad = pad_by_number(footprints, "U6", u6_pad_number).GetPosition()
        destination_pad = pad_by_number(footprints, "L1", choke_pad_number).GetPosition()
        if net_name == "CANH_RAW":
            source_via = point(mm(source_pad.x) + 2.075, mm(source_pad.y))
            destination_via = point(mm(destination_pad.x) - 1.3, mm(destination_pad.y))
        else:
            source_via = point(mm(source_pad.x) + 1.125, mm(source_pad.y) - 0.635)
            destination_via = point(mm(destination_pad.x) - 2.3, mm(destination_pad.y))
        add_polyline(board, nets[net_name], [source_pad, source_via], 0.25)
        add_blind_via(board, nets[net_name], source_via, pcbnew.F_Cu, pcbnew.In3_Cu)
        if net_name == "CANH_RAW":
            add_polyline(
                board,
                nets[net_name],
                [source_via, point(mm(source_via.x), mm(destination_via.y)), destination_via],
                0.25,
                pcbnew.In3_Cu,
            )
        else:
            add_polyline(
                board,
                nets[net_name],
                [source_via, point(mm(destination_via.x), mm(source_via.y)), destination_via],
                0.25,
                pcbnew.In3_Cu,
            )
        add_blind_via(board, nets[net_name], destination_via, pcbnew.In3_Cu, pcbnew.F_Cu)
        add_track(board, nets[net_name], destination_via, destination_pad, pcbnew.F_Cu, 0.25)

    for first, second in (
        ((132.0, 24.0), (132.0, 33.905)),
        ((132.0, 33.905), (130.35, 35.555)),
        ((132.0, 24.0), (132.0, 25.4267)),
        ((132.0, 25.4267), (134.0, 27.4267)),
        ((134.0, 27.4267), (134.0, 115.5)),
    ):
        remove_segment(board, "3V3_LOGIC", first, second)
    u7_logic_power = pad_by_number(footprints, "U7", "1").GetPosition()
    u6_logic_power = pad_by_number(footprints, "U6", "1").GetPosition()
    add_polyline(
        board,
        nets["3V3_LOGIC"],
        [u7_logic_power, point(129.0, 27.0), point(129.0, mm(u6_logic_power.y)), u6_logic_power],
        0.8,
    )
    add_polyline(
        board,
        nets["3V3_LOGIC"],
        [u7_logic_power, point(130.0, 26.0), point(130.0, 48.0), point(134.0, 52.0), point(134.0, 115.5)],
        0.8,
        pcbnew.In5_Cu,
    )

    for first, second in (
        ((131.6515, 43.7508), (131.0442, 43.7508)),
        ((131.0442, 43.7508), (130.35, 44.445)),
        ((131.6515, 40.1224), (131.6515, 43.7508)),
        ((128.6, 37.5192), (131.6515, 40.1224)),
        ((134.54, 24.0), (134.54, 32.0275)),
        ((134.54, 32.0275), (128.6, 37.5192)),
    ):
        remove_segment(board, "GND", first, second)
    relocate_via_and_connected_ends(board, "GND", (131.6515, 43.7508), (127.2, 44.445), 1)
    u7_logic_ground = pad_by_number(footprints, "U7", "2").GetPosition()
    u6_logic_ground_bottom = pad_by_number(footprints, "U6", "8").GetPosition()
    add_track(board, nets["GND"], u6_logic_ground_bottom, point(127.2, 44.445), pcbnew.F_Cu, 0.25)
    add_polyline(
        board,
        nets["GND"],
        [point(128.6, 37.5192), point(127.2, 38.9192), point(127.2, 44.445)],
        0.25,
        pcbnew.In4_Cu,
    )
    add_polyline(
        board,
        nets["GND"],
        [u7_logic_ground, point(128.0, 30.54), point(128.0, 37.0), point(128.6, 37.5192)],
        0.25,
        pcbnew.In1_Cu,
    )

    for first, second in (
        ((138.3476, 36.1308), (138.9558, 36.1308)),
        ((138.9558, 36.1308), (139.65, 36.825)),
        ((138.8561, 45.2389), (139.65, 44.445)),
        ((139.65, 43.175), (139.65, 44.445)),
        ((138.8561, 45.2389), (138.3476, 44.7304)),
        ((138.3476, 44.7304), (138.3476, 36.1308)),
        ((142.9979, 34.6771), (139.8013, 34.6771)),
        ((139.8013, 34.6771), (138.3476, 36.1308)),
    ):
        remove_segment(board, "GND_CAN_ISO", first, second)
    for item in list(board.GetTracks()):
        if not isinstance(item, pcbnew.PCB_VIA) or item.GetNetname() != "GND_CAN_ISO":
            continue
        if item.GetPosition() == point(138.3476, 36.1308):
            board.Remove(item)
            break
    else:
        raise ValueError("expected GND_CAN_ISO via at (138.3476, 36.1308)")
    field_ground_bus_x = 141.4
    field_ground_top_escape = point(140.6, 36.825)
    relocate_via_and_connected_ends(
        board,
        "GND_CAN_ISO",
        (138.8561, 45.2389),
        (field_ground_bus_x, 44.445),
        1,
    )
    field_ground_bottom_via = next(
        item
        for item in board.GetTracks()
        if isinstance(item, pcbnew.PCB_VIA)
        and item.GetNetname() == "GND_CAN_ISO"
        and item.GetPosition() == point(field_ground_bus_x, 44.445)
    )
    field_ground_bottom_via.SetViaType(pcbnew.VIATYPE_BLIND)
    field_ground_bottom_via.SetLayerPair(pcbnew.F_Cu, pcbnew.In1_Cu)
    add_blind_via(board, nets["GND_CAN_ISO"], field_ground_top_escape, pcbnew.F_Cu, pcbnew.In2_Cu)
    u6_field_ground_top = pad_by_number(footprints, "U6", "15").GetPosition()
    u6_field_ground_middle = pad_by_number(footprints, "U6", "10").GetPosition()
    u6_field_ground_bottom = pad_by_number(footprints, "U6", "9").GetPosition()
    add_polyline(
        board,
        nets["GND_CAN_ISO"],
        [u6_field_ground_top, field_ground_top_escape],
        0.25,
    )
    add_polyline(
        board,
        nets["GND_CAN_ISO"],
        [u6_field_ground_middle, point(field_ground_bus_x, 43.175), point(field_ground_bus_x, 44.445)],
        0.25,
    )
    add_track(
        board,
        nets["GND_CAN_ISO"],
        u6_field_ground_bottom,
        point(field_ground_bus_x, 44.445),
        pcbnew.F_Cu,
        0.25,
    )
    add_polyline(
        board,
        nets["GND_CAN_ISO"],
        [field_ground_top_escape, point(141.8, 35.6), point(142.9979, 34.6771)],
        0.25,
        pcbnew.In2_Cu,
    )


def add_plane_zones(board, nets: dict[str, object]):
    raw_input = [
        (7.0, 8.0),
        (16.0, 8.0),
        (16.0, 15.0),
        (28.0, 15.0),
        (28.0, 23.0),
        (23.5, 23.0),
        (23.5, 18.0),
        (7.0, 18.0),
    ]
    fused_input = [
        (12.0, 17.0),
        (34.0, 17.0),
        (34.0, 24.0),
        (12.0, 24.0),
    ]
    common_source = [(23.0, 17.0), (29.0, 17.0), (29.0, 25.0), (23.0, 25.0)]
    sensed_input = [(29.0, 17.0), (37.0, 17.0), (37.0, 25.0), (29.0, 25.0)]
    protected_input = [
        (24.0, 8.0),
        (31.0, 8.0),
        (31.0, 18.0),
        (52.0, 18.0),
        (52.0, 24.0),
        (24.0, 24.0),
    ]
    primary_ground = [
        (1.5, 1.5),
        (46.0, 1.5),
        (46.0, 82.0),
        (1.5, 82.0),
    ]
    isolated_can_ground = [
        (140.0, 1.5),
        (158.5, 1.5),
        (158.5, 82.0),
        (140.0, 82.0),
    ]
    jetson_power = [
        (86.0, 1.5),
        (123.0, 1.5),
        (123.0, 44.0),
        (86.0, 44.0),
    ]
    logic_power_regions = [
        [(86.0, 44.0), (123.0, 44.0), (123.0, 68.0), (86.0, 68.0)],
        [(78.0, 84.0), (138.0, 84.0), (138.0, 128.5), (78.0, 128.5)],
        [(124.0, 1.5), (138.0, 1.5), (138.0, 44.0), (124.0, 44.0)],
    ]
    secondary_ground = [(56.0, 1.5), (138.0, 1.5), (138.0, 128.5), (56.0, 128.5)]
    isolated_12v = [(56.0, 1.5), (123.0, 1.5), (123.0, 83.0), (56.0, 83.0)]
    isolated_can_power = [(140.0, 1.5), (158.5, 1.5), (158.5, 45.0), (140.0, 45.0)]
    # Keep the generated pours on the two outer copper layers.  The six
    # internal layers remain available to the controlled router; moving a
    # filled zone onto a routed inner layer would make the SES-dependent
    # release non-deterministic because Specctra does not carry KiCad zones.
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        if layer == pcbnew.F_Cu:
            add_copper_zone(board, nets["VBAT_RAW"], layer, raw_input, priority=6)
            add_copper_zone(board, nets["VBAT_FUSED"], layer, fused_input, priority=5)
            add_copper_zone(board, nets["FET_COMMON"], layer, common_source, priority=7)
            add_copper_zone(board, nets["INPUT_SENSE"], layer, sensed_input, priority=8)
            add_copper_zone(board, nets["VBAT_PROTECTED"], layer, protected_input, priority=4)
        add_copper_zone(board, nets["GND_PWR"], layer, primary_ground)
        add_copper_zone(board, nets["JETSON_12V"], layer, jetson_power, priority=2)
        if layer == pcbnew.F_Cu:
            for region in logic_power_regions:
                add_copper_zone(board, nets["3V3_LOGIC"], layer, region, priority=3)
        add_copper_zone(board, nets["GND_CAN_ISO"], layer, isolated_can_ground)
    add_copper_zone(board, nets["GND_PWR"], pcbnew.In1_Cu, primary_ground)
    add_copper_zone(board, nets["GND"], pcbnew.In1_Cu, secondary_ground)
    # Give the isolated CAN F.Cu corridor an explicit adjacent In1.Cu return
    # plane.  This is a controlled reference declaration; field-solve and
    # continuity checks remain supplier/manual release gates.
    add_copper_zone(board, nets["GND_CAN_ISO"], pcbnew.In1_Cu, isolated_can_ground)
    add_copper_zone(board, nets["12V_ISO"], pcbnew.In2_Cu, isolated_12v)
    add_copper_zone(board, nets["JETSON_12V"], pcbnew.In3_Cu, jetson_power)
    add_copper_zone(board, nets["GND"], pcbnew.In4_Cu, secondary_ground)
    add_copper_zone(board, nets["GND_CAN_ISO"], pcbnew.In4_Cu, isolated_can_ground)
    for region in logic_power_regions:
        add_copper_zone(board, nets["3V3_LOGIC"], pcbnew.In5_Cu, region)
    add_copper_zone(board, nets["5V_CAN_ISO"], pcbnew.In5_Cu, isolated_can_power)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())


class Router:
    def __init__(self, board, nets: dict[str, object], net_pads: dict[str, list[object]]):
        self.board = board
        self.nets = nets
        self.net_pads = net_pads
        self.occupied: dict[tuple[int, int, int], str] = {}
        self.via_cells: dict[tuple[int, int], str] = {}
        self.track_cells: dict[str, set[tuple[int, int, int]]] = defaultdict(set)
        self._mark_pads()

    def _pad_layers(self, pad) -> list[int]:
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            return list(range(len(LAYERS)))
        return [0]

    def _terminal_state(self, pad) -> tuple[int, int, int]:
        position = pad.GetPosition()
        center_x = grid(mm(position.x))
        center_y = grid(mm(position.y))
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
            return center_x, center_y, 0

        footprint_position = pad.GetParentFootprint().GetPosition()
        pin_count = len(list(pad.GetParentFootprint().Pads()))
        try:
            stagger = (int(pad.GetNumber()) % 4) * 0.8 if pin_count >= 20 else 0.0
        except ValueError:
            stagger = 0.0
        delta_x = mm(position.x - footprint_position.x)
        delta_y = mm(position.y - footprint_position.y)
        pad_size = pad.GetSize()
        if abs(delta_x) >= abs(delta_y):
            direction = 1 if delta_x >= 0 else -1
            escape = mm(pad_size.x) / 2 + 0.75 + stagger
            return grid(mm(position.x) + direction * escape), center_y, 0
        direction = 1 if delta_y >= 0 else -1
        escape = mm(pad_size.y) / 2 + 0.75 + stagger
        return center_x, grid(mm(position.y) + direction * escape), 0

    def _route_terminal(self, pad, net_name: str) -> tuple[int, int, int]:
        preferred = self._terminal_state(pad)
        if self.occupied.get(preferred, net_name) == net_name:
            return preferred
        candidates = [
            (abs(dx) + abs(dy), (preferred[0] + dx, preferred[1] + dy, 0))
            for dx in range(-6, 7)
            for dy in range(-6, 7)
            if self.occupied.get((preferred[0] + dx, preferred[1] + dy, 0)) == net_name
        ]
        if candidates:
            return min(candidates)[1]
        position = pad.GetPosition()
        return grid(mm(position.x)), grid(mm(position.y)), 0

    def _mark_pads(self):
        pad_records = []
        for footprint in self.board.GetFootprints():
            for pad in footprint.Pads():
                net_name = pad.GetNetname() or f"__PAD_{footprint.GetReference()}_{pad.GetNumber()}"
                pad_records.append((pad, net_name))
                box = pad.GetBoundingBox()
                min_x = grid(mm(box.GetX()))
                max_x = grid(mm(box.GetRight()))
                min_y = grid(mm(box.GetY()))
                max_y = grid(mm(box.GetBottom()))
                for layer in self._pad_layers(pad):
                    for ix in range(min_x, max_x + 1):
                        for iy in range(min_y, max_y + 1):
                            key = (ix, iy, layer)
                            existing = self.occupied.get(key)
                            if existing is None or existing == net_name:
                                self.occupied[key] = net_name
        for pad, net_name in pad_records:
            start_x = grid(mm(pad.GetPosition().x))
            start_y = grid(mm(pad.GetPosition().y))
            end_x, end_y, layer = self._terminal_state(pad)
            if start_x == end_x:
                cells = ((start_x, item, layer) for item in range(min(start_y, end_y), max(start_y, end_y) + 1))
            else:
                cells = ((item, start_y, layer) for item in range(min(start_x, end_x), max(start_x, end_x) + 1))
            for key in cells:
                existing = self.occupied.get(key)
                if existing is None or existing == net_name:
                    self.occupied[key] = net_name

    def _is_open(self, state: tuple[int, int, int], net_name: str, via: bool = False) -> bool:
        ix, iy, layer = state
        if ix < grid(1.5) or iy < grid(1.5) or ix > grid(158.5) or iy > grid(128.5):
            return False
        if via:
            if any((ix + dx, iy + dy) in self.via_cells for dx in range(-1, 2) for dy in range(-1, 2)):
                return False
            radius = max(1, math.ceil((0.3 + 0.15) / GRID_MM))
            return all(
                self.occupied.get((ix + dx, iy + dy, item), net_name) == net_name
                for item in range(len(LAYERS))
                for dx in range(-radius, radius + 1)
                for dy in range(-radius, radius + 1)
            )
        if any(
            self.via_cells.get((ix + dx, iy + dy), net_name) != net_name for dx in range(-1, 2) for dy in range(-1, 2)
        ):
            return False
        return self.occupied.get((ix, iy, layer), net_name) == net_name

    def _search(
        self,
        start: tuple[int, int, int],
        goal: tuple[int, int, int],
        net_name: str,
        margin_mm: float,
    ) -> list[tuple[int, int, int]] | None:
        margin = grid(margin_mm)
        preferred_layer = PREFERRED_LAYER_BY_NET.get(
            net_name,
            1 + sum(net_name.encode("ascii")) % max(1, len(LAYERS) - 2),
        )
        min_x = max(grid(1.5), min(start[0], goal[0]) - margin)
        max_x = min(grid(158.5), max(start[0], goal[0]) + margin)
        min_y = max(grid(1.5), min(start[1], goal[1]) - margin)
        max_y = min(grid(128.5), max(start[1], goal[1]) + margin)

        def heuristic(state: tuple[int, int, int]) -> int:
            return abs(state[0] - goal[0]) + abs(state[1] - goal[1]) + (0 if state[2] == goal[2] else 8)

        queue: list[tuple[int, int, tuple[int, int, int]]] = []
        serial = 0
        heapq.heappush(queue, (heuristic(start), serial, start))
        costs = {start: 0}
        previous: dict[tuple[int, int, int], tuple[int, int, int]] = {}
        while queue:
            _, _, current = heapq.heappop(queue)
            if current == goal:
                path = [current]
                while current != start:
                    current = previous[current]
                    path.append(current)
                path.reverse()
                return path
            ix, iy, layer = current
            planar_cost = 1 if layer == preferred_layer else 3
            neighbors = [
                ((ix + 1, iy, layer), planar_cost, False),
                ((ix - 1, iy, layer), planar_cost, False),
                ((ix, iy + 1, layer), planar_cost, False),
                ((ix, iy - 1, layer), planar_cost, False),
            ]
            for next_layer in range(len(LAYERS)):
                if next_layer != layer:
                    layer_penalty = 0 if next_layer == preferred_layer else 2
                    neighbors.append(((ix, iy, next_layer), 2 + layer_penalty, True))
            for candidate, move_cost, is_via in neighbors:
                if not (min_x <= candidate[0] <= max_x and min_y <= candidate[1] <= max_y):
                    continue
                if not self._is_open(candidate, net_name, is_via):
                    continue
                new_cost = costs[current] + move_cost
                if new_cost >= costs.get(candidate, sys.maxsize):
                    continue
                costs[candidate] = new_cost
                previous[candidate] = current
                serial += 1
                heapq.heappush(queue, (new_cost + heuristic(candidate), serial, candidate))
        return None

    def _occupy(self, path: list[tuple[int, int, int]], net_name: str, width: float):
        radius = max(0, math.ceil((width / 2 + 0.15) / GRID_MM) - 1)
        for ix, iy, layer in path:
            self.track_cells[net_name].add((ix, iy, layer))
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    key = (ix + dx, iy + dy, layer)
                    if self.occupied.get(key) in {None, net_name}:
                        self.occupied[key] = net_name
        for previous_state, state in pairwise(path):
            if previous_state[2] == state[2]:
                continue
            ix, iy = state[0], state[1]
            self.via_cells[(ix, iy)] = net_name
            for layer in range(len(LAYERS)):
                key = (ix, iy, layer)
                if self.occupied.get(key) in {None, net_name}:
                    self.occupied[key] = net_name

    def _emit(self, path: list[tuple[int, int, int]], net_name: str, width: float, start_pad, end_pad):
        net = self.nets[net_name]
        add_track(
            self.board, net, start_pad.GetPosition(), grid_point(path[0][0], path[0][1]), LAYERS[path[0][2]], width
        )
        segment_start = path[0]
        vias: set[tuple[int, int]] = set()
        for previous_state, state in pairwise(path):
            if state[2] != previous_state[2]:
                if segment_start != previous_state:
                    add_track(
                        self.board,
                        net,
                        grid_point(segment_start[0], segment_start[1]),
                        grid_point(previous_state[0], previous_state[1]),
                        LAYERS[previous_state[2]],
                        width,
                    )
                location = (state[0], state[1])
                if location not in vias:
                    add_via(self.board, net, grid_point(*location))
                    vias.add(location)
                segment_start = state
                continue
            before = previous_state[0] - segment_start[0], previous_state[1] - segment_start[1]
            after = state[0] - previous_state[0], state[1] - previous_state[1]
            if segment_start != previous_state and before != (0, 0) and (before[0] == 0) != (after[0] == 0):
                add_track(
                    self.board,
                    net,
                    grid_point(segment_start[0], segment_start[1]),
                    grid_point(previous_state[0], previous_state[1]),
                    LAYERS[state[2]],
                    width,
                )
                segment_start = previous_state
        if segment_start != path[-1]:
            add_track(
                self.board,
                net,
                grid_point(segment_start[0], segment_start[1]),
                grid_point(path[-1][0], path[-1][1]),
                LAYERS[path[-1][2]],
                width,
            )
        add_track(
            self.board, net, grid_point(path[-1][0], path[-1][1]), end_pad.GetPosition(), LAYERS[path[-1][2]], width
        )

    def route_pair(self, net_name: str, start_pad, end_pad):
        start_position = start_pad.GetPosition()
        end_position = end_pad.GetPosition()
        start = self._route_terminal(start_pad, net_name)
        goal = self._route_terminal(end_pad, net_name)
        path = None
        for margin in (8.0, 20.0, 50.0, 160.0):
            path = self._search(start, goal, net_name, margin)
            if path is not None:
                break
        if path is None:
            start_mm = (mm(start_position.x), mm(start_position.y))
            end_mm = (mm(end_position.x), mm(end_position.y))
            raise RuntimeError(f"unable to route {net_name} between {start_mm} and {end_mm}")
        pad_neck = (
            min(
                mm(min(start_pad.GetSize().x, start_pad.GetSize().y)),
                mm(min(end_pad.GetSize().x, end_pad.GetSize().y)),
            )
            * 0.5
        )
        width = min(TRACK_WIDTHS.get(net_name, 0.25), max(0.15, pad_neck))
        self._emit(path, net_name, width, start_pad, end_pad)
        self._occupy(path, net_name, width)

    def route_all(self):
        power_first = {
            "VBAT_RAW",
            "VBAT_FUSED",
            "FET_COMMON",
            "VBAT_PROTECTED",
            "GND_PWR",
            "12V_ISO",
            "JETSON_12V",
        }
        primary_control = {"UV_SET", "OV_SET", "U1_GATE", "FET_GATE", "U1_SHDN", "INPUT_SENSE"}
        safety_first = {
            "RELAY_A_NC",
            "RELAY_B_NC",
            "MOTOR_ENABLE_REQ",
            "MOTOR_ENABLE_SAFE",
            "ESTOP_SENSE",
            "ESTOP_A_MON",
            "ESTOP_B_MON",
        }
        common_last = {"GND", "3V3_LOGIC", "5V_CAN_ISO", "GND_CAN_ISO"}

        def priority(name: str) -> int:
            if name in common_last:
                return 3
            if name in MCU_LOCAL_NETS:
                return -7
            if name in {"UART_RX_MCU", "UART_TX_MCU"}:
                return -6
            if name in {"I2C_SDA_MCU", "I2C_SCL_MCU"}:
                return -5
            if name in {"ESTOP_A_MON", "ESTOP_B_MON"}:
                return -3
            if name in {"RELAY_A_NC", "RELAY_B_NC"}:
                return -2
            if name in safety_first:
                return -1
            if any(pad.GetParentFootprint().GetReference() == "U5" for pad in self.net_pads[name]):
                return 0
            if name in primary_control:
                return 0
            if name in power_first:
                return 1
            return 2

        def net_span(name: str) -> float:
            return max(
                (
                    math.hypot(
                        mm(first.GetPosition().x - second.GetPosition().x),
                        mm(first.GetPosition().y - second.GetPosition().y),
                    )
                    for first in self.net_pads[name]
                    for second in self.net_pads[name]
                ),
                default=0.0,
            )

        ordered_nets = sorted(
            self.net_pads,
            key=lambda name: (
                priority(name),
                net_span(name)
                if name in MCU_LOCAL_NETS
                else (
                    -net_span(name)
                    if priority(name) <= 0
                    else (-len(self.net_pads[name]) if priority(name) == 1 else len(self.net_pads[name]))
                ),
                TRACK_WIDTHS.get(name, 0.25),
                name,
            ),
        )
        route_count = 0
        for net_name in ordered_nets:
            if net_name in PLANE_NETS:
                continue
            pads = []
            duplicate_groups = set()
            for pad in self.net_pads[net_name]:
                group = (pad.GetParentFootprint().GetReference(), pad.GetNumber())
                if group in duplicate_groups:
                    continue
                duplicate_groups.add(group)
                pads.append(pad)
            if len(pads) < 2:
                continue
            connected = [pads[0]]
            remaining = pads[1:]
            while remaining:
                distance, _, _, source, target = min(
                    (
                        math.hypot(
                            mm(first.GetPosition().x - second.GetPosition().x),
                            mm(first.GetPosition().y - second.GetPosition().y),
                        ),
                        (
                            first.GetParentFootprint().GetReference(),
                            first.GetNumber(),
                            first.GetPosition().x,
                            first.GetPosition().y,
                        ),
                        (
                            second.GetParentFootprint().GetReference(),
                            second.GetNumber(),
                            second.GetPosition().x,
                            second.GetPosition().y,
                        ),
                        first,
                        second,
                    )
                    for first in connected
                    for second in remaining
                )
                del distance
                self.route_pair(net_name, source, target)
                connected.append(target)
                remaining = [pad for pad in remaining if pad is not target]
                route_count += 1
        return route_count


def build_placement_board():
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(COPPER_LAYER_COUNT)
    settings = board.GetDesignSettings()
    settings.m_MinClearance = pcbnew.FromMM(0.15)
    settings.m_TrackMinWidth = pcbnew.FromMM(0.15)
    settings.m_MinThroughDrill = pcbnew.FromMM(0.30)
    settings.m_ViasMinAnnularWidth = pcbnew.FromMM(0.15)
    settings.m_HoleClearance = pcbnew.FromMM(0.25)
    settings.m_CopperEdgeClearance = pcbnew.FromMM(0.50)
    settings.m_NetSettings.GetDefaultNetclass().SetClearance(pcbnew.FromMM(0.15))
    settings.m_NetSettings.GetDefaultNetclass().SetTrackWidth(pcbnew.FromMM(0.25))
    add_outline(board)
    footprints = place_footprints(board)
    nets = make_nets(board)
    net_pads = assign_pad_nets(footprints, nets)
    configure_routing_classes(board)
    for index, (x, y) in enumerate([(4, 4), (156, 4), (156, 126), (4, 126)], start=1):
        add_mounting_hole(board, f"H{index}", x, y)
        add_mounting_keepout(board, x, y)
    return board, nets, net_pads


def build_board(session_path: Path = ROUTING_SESSION, output_path: Path = OUTPUT):
    board, nets, _ = build_placement_board()
    from import_freerouting_session import import_session, parse_session

    if not session_path.exists():
        raise FileNotFoundError(f"routing session is missing: {session_path}")
    session = parse_session(session_path.read_text(encoding="utf-8"))
    tracks, vias = import_session(board, session)
    route_count = tracks + vias
    remove_single_layer_signal_vias(board)
    relocate_u6_logic_vias(board)
    footprints = {footprint.GetReference(): footprint for footprint in board.GetFootprints()}
    reroute_u6_isolation_domains(board, nets, footprints)
    add_post_route_supplements(board, nets, footprints)
    replace_local_oscillator_routing(board, nets, footprints)
    replace_field_can_routing(board, nets, footprints)
    add_isolated_power_via_arrays(board, nets, footprints)
    replace_u3_output_transfer(board, nets)
    add_u3_exposed_pad_thermal_vias(board, nets, footprints)
    add_u6_isolation_keepout(board, footprints)
    add_u7_isolation_keepout(board, footprints)
    add_plane_zones(board, nets)
    add_board_markings(board)
    board.Save(str(output_path.resolve()))
    normalize_kicad_board(output_path.resolve(), "controller.kicad_pcb")
    embed_stackup(output_path.resolve())
    return board, route_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the controller KiCad board")
    parser.add_argument("--placement-only", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--dsn-output", type=Path)
    parser.add_argument("--session", type=Path, default=ROUTING_SESSION)
    args = parser.parse_args()
    if args.placement_only:
        board, _, _ = build_placement_board()
        board.Save(str(args.output.resolve()))
        normalize_kicad_board(args.output.resolve(), "controller-placement.kicad_pcb")
        embed_stackup(args.output.resolve())
        if args.dsn_output and not pcbnew.ExportSpecctraDSN(board, str(args.dsn_output.resolve())):
            raise SystemExit("failed to export Specctra DSN")
        if args.dsn_output:
            from constrain_freerouting_dsn import constrain

            constrain(args.dsn_output.resolve())
        print(f"saved placement {args.output}: {len(board.GetFootprints())} footprints")
        raise SystemExit(0)
    board, route_count = build_board(args.session, args.output)
    print(
        f"saved {args.output}: {len(board.GetFootprints())} footprints, "
        f"{len(board.GetTracks())} track/via items, {route_count} routed branches"
    )
