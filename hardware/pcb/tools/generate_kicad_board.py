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


def add_footprint(
    board,
    ref: str,
    value: str,
    x: float,
    y: float,
    nets: list,
    pth: bool = False,
    pitch: float | None = None,
    reference_position: tuple[float, float] | None = None,
):
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference(ref)
    footprint.SetValue(value)
    footprint.SetPosition(point(x, y))
    ref_x, ref_y = reference_position or (x, y - 4)
    footprint.Reference().SetPosition(point(ref_x, ref_y))
    footprint.Reference().SetTextSize(point(1.2, 1.2))
    footprint.Reference().SetTextThickness(pcbnew.FromMM(0.2))
    footprint.Value().SetVisible(False)
    pitch = pitch if pitch is not None else (3.0 if pth else 2.0)
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
        for index, (x, net) in enumerate(zip([79, 82, 94, 97], nets, strict=True))
    ]
    board.Add(footprint)
    return pads


def add_isolation_bridge(board, ref: str, value: str, x: float, y: float, nets: list):
    """Place four pads on each side of an 8 mm no-copper isolation band."""
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference(ref)
    footprint.SetValue(value)
    footprint.SetPosition(point(x, y))
    footprint.Reference().SetPosition(point(x - 7, y))
    footprint.Reference().SetTextSize(point(1.2, 1.2))
    footprint.Reference().SetTextThickness(pcbnew.FromMM(0.2))
    footprint.Value().SetVisible(False)
    offsets = [-4.5, -1.5, 1.5, 4.5]
    pads = [add_pad(footprint, index + 1, x + dx, y - 10, nets[index], True) for index, dx in enumerate(offsets)]
    pads.extend(
        add_pad(footprint, index + 5, x + dx, y + 10, nets[index + 4], True) for index, dx in enumerate(offsets)
    )
    board.Add(footprint)
    return pads


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


def add_via(board, net, position):
    via = pcbnew.PCB_VIA(board)
    via.SetNet(net)
    via.SetPosition(position)
    via.SetWidth(pcbnew.FromMM(0.8))
    via.SetDrill(pcbnew.FromMM(0.4))
    board.Add(via)
    return via


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
    corners = [(20, 20), (180, 20), (180, 150), (20, 150), (20, 20)]
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
    signal_names = [
        "SPI_SCLK",
        "SPI_MOSI",
        "SPI_MISO",
        "MOTOR_ENABLE_REQ",
        "MOTOR_CS0",
        "MOTOR_CS1",
        "MOTOR_CS2",
        "MOTOR_CS3",
        "MOTOR_CS4",
        "MOTOR_CS5",
        "I2C_SDA",
        "I2C_SCL",
        "ESTOP_SENSE",
        "UART_TX",
        "UART_RX",
        "MCU_RESET",
    ]
    nets = {}
    for name in [
        "VBAT_RAW",
        "VBAT_FUSED",
        "VBAT_PROTECTED",
        "GND_PWR",
        "12V_ISO",
        "JETSON_12V",
        "3V3_LOGIC",
        "GND",
        "CANH",
        "CANL",
        "CAN_TX",
        "CAN_RX",
        "5V_CAN_ISO",
        "GND_CAN_ISO",
        "MOTOR_ENABLE_SAFE",
        "ESTOP_CH_A_OUT",
        "ESTOP_CH_A_RETURN",
        "ESTOP_CH_B_OUT",
        "ESTOP_CH_B_RETURN",
        *signal_names,
    ]:
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net

    netpads = {name: [] for name in nets}

    def fp(ref, value, x, y, names, pth=True, pitch=None, reference_position=None):
        pads = add_footprint(
            board,
            ref,
            value,
            x,
            y,
            [nets.get(name) for name in names],
            pth,
            pitch,
            reference_position,
        )
        for name, pad in zip(names, pads, strict=True):
            if name in netpads:
                netpads[name].append(pad)
        return pads

    fp("J1", "48V_INPUT_10A", 30, 35, ["VBAT_RAW", "VBAT_RAW", "GND_PWR", "GND_PWR"])
    fp("F1", "FUSE_10A", 48, 35, ["VBAT_RAW", "VBAT_FUSED"])
    fp("U1", "LM5069_HOTSWAP", 68, 35, ["VBAT_FUSED", "GND_PWR", "VBAT_PROTECTED", "GND_PWR"])
    u2pads = add_isolated_module(
        board,
        "U2",
        "DCM3623_48V_12V_240W",
        35,
        [nets["VBAT_PROTECTED"], nets["GND_PWR"], nets["12V_ISO"], nets["GND"]],
    )
    for name, pad in zip(["VBAT_PROTECTED", "GND_PWR", "12V_ISO", "GND"], u2pads, strict=True):
        netpads[name].append(pad)
    j2pads = fp("J2", "12V_OUTPUT_16A", 106, 82, ["12V_ISO", "12V_ISO", "GND", "GND"])
    fp("U3", "JETSON_12V_EFUSE_5A", 112, 42, ["12V_ISO", "GND", "JETSON_12V", "GND"])
    fp("J3", "JETSON_DEVKIT_12V_5A", 125, 42, ["JETSON_12V", "JETSON_12V", "GND", "GND"])
    fp("U4", "BUCK_12V_3V3_5A", 112, 64, ["12V_ISO", "GND", "3V3_LOGIC", "GND"])
    backplane_pinout = ["3V3_LOGIC", "GND", "3V3_LOGIC", "GND", *signal_names]
    mcu_pinout = [*backplane_pinout, "CAN_TX", "CAN_RX"]
    u5pads = fp("U5", "CH32V307_CARRIER", 145, 110, mcu_pinout, pitch=2.75)
    j4pads = fp("J4", "JETSON_MCU_BACKPLANE", 145, 140, backplane_pinout, pitch=2.75)
    for index, name in enumerate(backplane_pinout[:4]):
        netpads[name].remove(u5pads[index])
        netpads[name].remove(j4pads[index])
    u6pads = add_isolation_bridge(
        board,
        "U6",
        "ISO1042DW",
        145,
        77,
        [nets[name] for name in ["5V_CAN_ISO", "GND_CAN_ISO", "CANH", "CANL", "3V3_LOGIC", "GND", "CAN_TX", "CAN_RX"]],
    )
    u7pads = add_isolation_bridge(
        board,
        "U7",
        "3V3_5V_ISOLATED_DC_DC",
        165,
        77,
        [nets.get(name) for name in ["5V_CAN_ISO", "GND_CAN_ISO", None, None, "3V3_LOGIC", "GND", None, None]],
    )
    for name, pad in zip(
        ["5V_CAN_ISO", "GND_CAN_ISO", "CANH", "CANL", "3V3_LOGIC", "GND", "CAN_TX", "CAN_RX"],
        u6pads,
        strict=True,
    ):
        netpads[name].append(pad)
    for name, pad in zip(
        ["5V_CAN_ISO", "GND_CAN_ISO", None, None, "3V3_LOGIC", "GND", None, None], u7pads, strict=True
    ):
        if name is not None:
            netpads[name].append(pad)
    fp("J5", "CAN_A", 145, 55, ["CANH", "CANL", "GND_CAN_ISO", None])
    fp("J6", "CAN_B", 165, 55, ["CANH", "CANL", "GND_CAN_ISO", None])
    u8pads = fp(
        "U8",
        "DUAL_CHANNEL_SAFETY_GATE_CARRIER",
        110,
        125,
        [
            "12V_ISO",
            "GND",
            "MOTOR_ENABLE_REQ",
            "MOTOR_ENABLE_SAFE",
            "ESTOP_SENSE",
            "ESTOP_CH_A_OUT",
            "ESTOP_CH_A_RETURN",
            "ESTOP_CH_B_OUT",
            "ESTOP_CH_B_RETURN",
            "GND",
            "3V3_LOGIC",
            None,
        ],
        pth=False,
        pitch=2.0,
        reference_position=(110, 121),
    )
    j10pads = fp(
        "J10",
        "ESTOP_RED_KEYED_DUAL_CHANNEL",
        108,
        140,
        ["ESTOP_CH_A_OUT", "ESTOP_CH_A_RETURN", "ESTOP_CH_B_OUT", "ESTOP_CH_B_RETURN"],
    )
    j11pads = fp(
        "J11",
        "SAFETY_GATE_OUTPUT",
        135,
        92,
        ["MOTOR_ENABLE_SAFE", "ESTOP_SENSE", "GND", None],
        pth=False,
        pitch=2.0,
    )
    for index, name in [(0, "12V_ISO"), (1, "GND"), (9, "GND"), (10, "3V3_LOGIC")]:
        netpads[name].remove(u8pads[index])
    netpads["GND"].remove(j11pads[2])
    u8vias = {
        index: add_via(board, nets[name], u8pads[index].GetPosition())
        for index, name in [
            (0, "12V_ISO"),
            (1, "GND"),
            (2, "MOTOR_ENABLE_REQ"),
            (4, "ESTOP_SENSE"),
            (10, "3V3_LOGIC"),
        ]
    }
    u8_gnd_aux_via = add_via(board, nets["GND"], point(121, 130))
    add_track(board, nets["GND"], u8pads[9].GetPosition(), u8_gnd_aux_via.GetPosition(), pcbnew.F_Cu, 0.5)
    j11vias = {
        index: add_via(board, nets[name], j11pads[index].GetPosition())
        for index, name in [(1, "ESTOP_SENSE"), (2, "GND")]
    }

    routing = {
        "VBAT_RAW": (pcbnew.F_Cu, 2.0, 27),
        "VBAT_FUSED": (pcbnew.F_Cu, 2.0, 29),
        "VBAT_PROTECTED": (pcbnew.F_Cu, 2.0, 31),
        "GND_PWR": (pcbnew.In1_Cu, 2.0, 31),
        "12V_ISO": (pcbnew.In2_Cu, 2.0, 76),
        "JETSON_12V": (pcbnew.In3_Cu, 2.0, 37),
        "3V3_LOGIC": (pcbnew.In4_Cu, 1.0, 94),
        "GND": (pcbnew.B_Cu, 1.5, 100),
        "CANH": (pcbnew.F_Cu, 0.3, 61),
        "CANL": (pcbnew.In1_Cu, 0.3, 64),
        "CAN_TX": (pcbnew.F_Cu, 0.25, 94),
        "CAN_RX": (pcbnew.In1_Cu, 0.25, 97),
        "5V_CAN_ISO": (pcbnew.In3_Cu, 0.5, 64),
        "GND_CAN_ISO": (pcbnew.In4_Cu, 0.5, 61),
    }
    for name, (layer, width, lane) in routing.items():
        route_chain(board, nets[name], netpads[name], layer, width, lane)

    for index, name in enumerate(backplane_pinout[:4]):
        layer = pcbnew.In4_Cu if name == "3V3_LOGIC" else pcbnew.B_Cu
        lane_y = routing[name][2]
        add_track(board, nets[name], u5pads[index].GetPosition(), j4pads[index].GetPosition(), layer, 0.5)
        u5_position = u5pads[index].GetPosition()
        add_track(
            board,
            nets[name],
            u5_position,
            point(pcbnew.ToMM(u5_position.x), lane_y),
            layer,
            0.5,
        )

    for index, name in enumerate(signal_names, start=4):
        add_track(board, nets[name], u5pads[index].GetPosition(), j4pads[index].GetPosition(), pcbnew.F_Cu, 0.25)

    safety_links = [
        (u8vias[2], u5pads[7], "MOTOR_ENABLE_REQ", pcbnew.In1_Cu, 102),
        (u8vias[4], u5pads[16], "ESTOP_SENSE", pcbnew.In2_Cu, 104),
        (u8pads[3], j11pads[0], "MOTOR_ENABLE_SAFE", pcbnew.F_Cu, 98),
        (u8vias[4], j11vias[1], "ESTOP_SENSE", pcbnew.In2_Cu, 96),
    ]
    for start_pad, end_pad, name, layer, lane_y in safety_links:
        start, end = start_pad.GetPosition(), end_pad.GetPosition()
        start_lane = point(pcbnew.ToMM(start.x), lane_y)
        end_lane = point(pcbnew.ToMM(end.x), lane_y)
        add_track(board, nets[name], start, start_lane, layer, 0.25)
        add_track(board, nets[name], start_lane, end_lane, layer, 0.25)
        add_track(board, nets[name], end_lane, end, layer, 0.25)

    for u8_index, j10_index, name in [
        (5, 0, "ESTOP_CH_A_OUT"),
        (6, 1, "ESTOP_CH_A_RETURN"),
        (7, 2, "ESTOP_CH_B_OUT"),
        (8, 3, "ESTOP_CH_B_RETURN"),
    ]:
        add_track(board, nets[name], u8pads[u8_index].GetPosition(), j10pads[j10_index].GetPosition(), pcbnew.F_Cu, 0.3)

    power_links = [
        (u8vias[0], j2pads[0], "12V_ISO", pcbnew.In2_Cu, 88),
        (u8_gnd_aux_via, u5pads[1], "GND", pcbnew.B_Cu, 116),
        (u8vias[10], u5pads[2], "3V3_LOGIC", pcbnew.In4_Cu, 118),
        (j11vias[2], u5pads[1], "GND", pcbnew.B_Cu, 106),
    ]
    start = u8vias[1].GetPosition()
    end = u8_gnd_aux_via.GetPosition()
    add_track(board, nets["GND"], start, point(pcbnew.ToMM(start.x), 132), pcbnew.B_Cu, 0.5)
    add_track(board, nets["GND"], point(pcbnew.ToMM(start.x), 132), point(pcbnew.ToMM(end.x), 132), pcbnew.B_Cu, 0.5)
    add_track(board, nets["GND"], point(pcbnew.ToMM(end.x), 132), end, pcbnew.B_Cu, 0.5)
    for start_pad, end_pad, name, layer, lane_y in power_links:
        start, end = start_pad.GetPosition(), end_pad.GetPosition()
        start_lane = point(pcbnew.ToMM(start.x), lane_y)
        end_lane = point(pcbnew.ToMM(end.x), lane_y)
        add_track(board, nets[name], start, start_lane, layer, 0.5)
        add_track(board, nets[name], start_lane, end_lane, layer, 0.5)
        add_track(board, nets[name], end_lane, end, layer, 0.5)

    for index, (x, y) in enumerate([(24, 24), (176, 24), (176, 146), (24, 146)], start=1):
        add_mounting_hole(board, f"H{index}", x, y)

    add_label(board, "WORKBENCH-1 CONTROLLER REV A", 100, 23, 1.5)
    add_label(board, "POWER DOMAIN", 58, 146)
    add_silk_line(board, (85, 28), (85, 142))
    add_silk_line(board, (93, 28), (93, 32))
    add_silk_line(board, (93, 38), (93, 142))
    add_label(board, "8 mm ISOLATION BARRIER", 70, 70)
    add_silk_line(board, (130, 73), (176, 73))
    add_silk_line(board, (130, 81), (176, 81))
    add_label(board, "CAN ISOLATION", 112, 70, 1.0)
    add_label(board, "LOGIC / INTERFACES", 142, 146)
    board.Save(str(OUTPUT))
    return board


if __name__ == "__main__":
    board = build_board()
    print(f"saved {OUTPUT}: {len(board.GetFootprints())} footprints, {len(board.GetTracks())} tracks")
    sys.exit(0)
