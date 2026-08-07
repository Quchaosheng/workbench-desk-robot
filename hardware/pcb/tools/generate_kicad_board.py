from __future__ import annotations

import sys
from itertools import pairwise
from pathlib import Path

try:
    import pcbnew
except ImportError as exc:
    raise SystemExit("Run with KiCad's bundled Python interpreter (bin/python.exe)") from exc

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "kicad" / "controller.kicad_pcb"


def point(x: float, y: float):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def layer_set(*layers: int):
    result = pcbnew.LSET()
    for layer in layers:
        result.AddLayer(layer)
    return result


def add_pad(footprint, number: int, dx: float, dy: float, net, pth: bool = False):
    pad = pcbnew.PAD(footprint)
    pad.SetNumber(str(number))
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE if pth else pcbnew.PAD_SHAPE_ROUNDRECT)
    pad.SetSize(point(2.4 if pth else 1.5, 2.4 if pth else 1.0))
    if pth:
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetDrillSize(point(1.1, 1.1))
        layers = pcbnew.LSET.AllCuMask()
        layers.AddLayer(pcbnew.F_Mask)
        layers.AddLayer(pcbnew.B_Mask)
        pad.SetLayerSet(layers)
    else:
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetLayerSet(layer_set(pcbnew.F_Cu, pcbnew.F_Paste, pcbnew.F_Mask))
        pad.SetRoundRectRadiusRatio(0.2)
    pad.SetPosition(point(dx, dy))
    if net is not None:
        pad.SetNet(net)
    footprint.Add(pad)
    return pad


def add_footprint(board, ref: str, value: str, x: float, y: float, nets: list, pth: bool = False):
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference(ref)
    footprint.SetValue(value)
    footprint.SetPosition(point(x, y))
    footprint.Reference().SetPosition(point(x, y - 4))
    footprint.Reference().SetTextSize(point(1.2, 1.2))
    footprint.Reference().SetTextThickness(pcbnew.FromMM(0.2))
    footprint.Value().SetVisible(False)
    pitch = 3.0 if pth else 2.0
    start = -(len(nets) - 1) * pitch / 2
    pads = [add_pad(footprint, index + 1, x + start + index * pitch, y, net, pth) for index, net in enumerate(nets)]
    board.Add(footprint)
    return pads


def add_isolated_module(board, ref: str, value: str, y: float, nets: list):
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference(ref)
    footprint.SetValue(value)
    footprint.SetPosition(point(88, y))
    footprint.Reference().SetPosition(point(88, y - 4))
    footprint.Reference().SetTextSize(point(1.2, 1.2))
    footprint.Reference().SetTextThickness(pcbnew.FromMM(0.2))
    footprint.Value().SetVisible(False)
    pads = [
        add_pad(footprint, index + 1, x, y, net, True)
        for index, (x, net) in enumerate(zip([80, 83, 93, 96], nets, strict=True))
    ]
    board.Add(footprint)
    return pads


def add_track(board, net, start, end, layer: int, width: float):
    track = pcbnew.PCB_TRACK(board)
    track.SetNet(net)
    track.SetStart(start)
    track.SetEnd(end)
    track.SetLayer(layer)
    track.SetWidth(pcbnew.FromMM(width))
    board.Add(track)


def add_mounting_hole(board, ref: str, x: float, y: float):
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference(ref)
    footprint.SetValue("M3_NPTH")
    footprint.SetPosition(point(x, y))
    footprint.Reference().SetVisible(False)
    footprint.Value().SetVisible(False)
    pad = pcbnew.PAD(footprint)
    pad.SetNumber("")
    pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(point(3.2, 3.2))
    pad.SetDrillSize(point(3.2, 3.2))
    pad.SetLayerSet(layer_set(pcbnew.F_Mask, pcbnew.B_Mask))
    pad.SetPosition(point(x, y))
    footprint.Add(pad)
    board.Add(footprint)


def route_chain(board, net, pads, layer: int, width: float, lane_y: float):
    ordered = sorted(pads, key=lambda pad: pad.GetPosition().x)
    for first, second in pairwise(ordered):
        a, b = first.GetPosition(), second.GetPosition()
        lane_a, lane_b = point(pcbnew.ToMM(a.x), lane_y), point(pcbnew.ToMM(b.x), lane_y)
        if a != lane_a:
            add_track(board, net, a, lane_a, layer, width)
        if lane_a != lane_b:
            add_track(board, net, lane_a, lane_b, layer, width)
        if lane_b != b:
            add_track(board, net, lane_b, b, layer, width)


def add_outline(board):
    corners = [(20, 20), (180, 20), (180, 120), (20, 120), (20, 20)]
    for start, end in pairwise(corners):
        edge = pcbnew.PCB_SHAPE(board)
        edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(point(*start))
        edge.SetEnd(point(*end))
        edge.SetLayer(pcbnew.Edge_Cuts)
        edge.SetWidth(pcbnew.FromMM(0.1))
        board.Add(edge)


def add_label(board, text: str, x: float, y: float, size: float = 1.2):
    label = pcbnew.PCB_TEXT(board)
    label.SetText(text)
    label.SetPosition(point(x, y))
    label.SetLayer(pcbnew.F_SilkS)
    label.SetTextSize(point(size, size))
    label.SetTextThickness(pcbnew.FromMM(0.2))
    board.Add(label)


def add_silk_line(board, start, end):
    line = pcbnew.PCB_SHAPE(board)
    line.SetShape(pcbnew.SHAPE_T_SEGMENT)
    line.SetStart(point(*start))
    line.SetEnd(point(*end))
    line.SetLayer(pcbnew.F_SilkS)
    line.SetWidth(pcbnew.FromMM(0.25))
    board.Add(line)


def build_board():
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(6)
    settings = board.GetDesignSettings()
    settings.m_MinClearance = pcbnew.FromMM(0.15)
    settings.m_TrackMinWidth = pcbnew.FromMM(0.15)
    settings.m_MinThroughDrill = pcbnew.FromMM(0.30)
    settings.m_ViasMinAnnularWidth = pcbnew.FromMM(0.15)
    settings.m_HoleClearance = pcbnew.FromMM(0.25)
    settings.m_CopperEdgeClearance = pcbnew.FromMM(0.50)
    add_outline(board)
    nets = {}
    for name in ["VBAT_FUSED", "GND_PWR", "12V_ISO", "5V_JETSON", "3V3_LOGIC", "GND", "CANH", "CANL"]:
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net

    netpads = {name: [] for name in nets}

    def fp(ref, value, x, y, names, pth=True):
        pads = add_footprint(board, ref, value, x, y, [nets.get(name) for name in names], pth)
        for name, pad in zip(names, pads, strict=True):
            if name in netpads:
                netpads[name].append(pad)

    fp("J1", "48V_INPUT_10A", 30, 35, ["VBAT_FUSED", "VBAT_FUSED", "GND_PWR", "GND_PWR"])
    fp("F1", "FUSE_10A", 48, 35, ["VBAT_FUSED", "VBAT_FUSED"])
    fp("U1", "LM5069_HOTSWAP", 68, 35, ["VBAT_FUSED", "GND_PWR", "VBAT_FUSED", "GND_PWR"])
    u2pads = add_isolated_module(
        board, "U2", "DCM3623_48V_12V_240W", 35, [nets["VBAT_FUSED"], nets["GND_PWR"], nets["12V_ISO"], nets["GND"]]
    )
    for name, pad in zip(["VBAT_FUSED", "GND_PWR", "12V_ISO", "GND"], u2pads, strict=True):
        netpads[name].append(pad)
    fp("J2", "12V_OUTPUT_16A", 72, 82, ["12V_ISO", "12V_ISO", "GND", "GND"])
    fp("U3", "BUCK_12V_5V_10A", 112, 42, ["12V_ISO", "GND", "5V_JETSON", "GND"])
    fp("J3", "JETSON_5V_12A", 148, 42, ["5V_JETSON", "5V_JETSON", "GND", "GND"])
    fp("U4", "BUCK_12V_3V3_5A", 112, 64, ["12V_ISO", "GND", "3V3_LOGIC", "GND"])
    fp(
        "U5",
        "CH32V307_CARRIER",
        145,
        64,
        ["3V3_LOGIC", "3V3_LOGIC", "3V3_LOGIC", "3V3_LOGIC", "GND", "GND", "GND", "GND"],
    )
    fp("U6", "ISO1042DW", 112, 96, ["3V3_LOGIC", "GND", None, None, "CANH", "CANL", "GND", "3V3_LOGIC"])
    fp("J5", "CAN_A", 150, 96, ["CANH", "CANL", "GND", None])
    fp("J6", "CAN_B", 168, 96, ["CANH", "CANL", "GND", None])
    fp("J10", "ESTOP_RED_KEYED", 150, 110, [None, None, None, None])

    routing = {
        "VBAT_FUSED": (pcbnew.F_Cu, 2.0, 27),
        "GND_PWR": (pcbnew.In1_Cu, 2.0, 31),
        "12V_ISO": (pcbnew.In2_Cu, 2.0, 76),
        "5V_JETSON": (pcbnew.In3_Cu, 2.0, 37),
        "3V3_LOGIC": (pcbnew.In4_Cu, 1.0, 58),
        "GND": (pcbnew.B_Cu, 1.5, 72),
        "CANH": (pcbnew.F_Cu, 0.3, 91),
        "CANL": (pcbnew.In1_Cu, 0.3, 101),
    }
    for name, (layer, width, lane) in routing.items():
        route_chain(board, nets[name], netpads[name], layer, width, lane)

    for index, (x, y) in enumerate([(24, 24), (176, 24), (176, 116), (24, 116)], start=1):
        add_mounting_hole(board, f"H{index}", x, y)

    add_label(board, "WORKBENCH-1 CONTROLLER REV A", 100, 23, 1.5)
    add_label(board, "POWER DOMAIN", 58, 115)
    add_silk_line(board, (85, 28), (85, 112))
    add_silk_line(board, (93, 28), (93, 32))
    add_silk_line(board, (93, 38), (93, 112))
    add_label(board, "8 mm ISOLATION BARRIER", 70, 70)
    add_label(board, "LOGIC / INTERFACES", 142, 115)
    board.Save(str(OUTPUT))
    return board


if __name__ == "__main__":
    board = build_board()
    print(f"saved {OUTPUT}: {len(board.GetFootprints())} footprints, {len(board.GetTracks())} tracks")
    sys.exit(0)
