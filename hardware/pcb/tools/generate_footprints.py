from __future__ import annotations

from pathlib import Path

try:
    import pcbnew
except ImportError as exc:
    raise SystemExit("Run with KiCad's bundled Python interpreter (bin/python.exe)") from exc


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "kicad" / "WB.pretty"
TABLE = ROOT / "kicad" / "fp-lib-table"


def point(x: float, y: float):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def layers(*items: int):
    result = pcbnew.LSET()
    for item in items:
        result.AddLayer(item)
    return result


def add_pad(
    footprint,
    number: int,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    drill: float | None = None,
):
    pad = pcbnew.PAD(footprint)
    pad.SetNumber(str(number))
    pad.SetPosition(point(x, y))
    pad.SetSize(point(width, height))
    if drill is None:
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT)
        pad.SetRoundRectRadiusRatio(0.2)
        pad.SetLayerSet(layers(pcbnew.F_Cu, pcbnew.F_Paste, pcbnew.F_Mask))
    else:
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE if width == height else pcbnew.PAD_SHAPE_OVAL)
        pad.SetDrillSize(point(drill, drill))
        pad_layers = pcbnew.LSET.AllCuMask()
        pad_layers.AddLayer(pcbnew.F_Mask)
        pad_layers.AddLayer(pcbnew.B_Mask)
        pad.SetLayerSet(pad_layers)
    footprint.Add(pad)


def add_rect(footprint, width: float, height: float, layer: int, line_width: float = 0.2):
    shape = pcbnew.PCB_SHAPE(footprint)
    shape.SetShape(pcbnew.SHAPE_T_RECT)
    shape.SetStart(point(-width / 2, -height / 2))
    shape.SetEnd(point(width / 2, height / 2))
    shape.SetLayer(layer)
    shape.SetWidth(pcbnew.FromMM(line_width))
    footprint.Add(shape)


def add_line(
    footprint,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    layer: int = pcbnew.F_SilkS,
    line_width: float = 0.2,
):
    shape = pcbnew.PCB_SHAPE(footprint)
    shape.SetShape(pcbnew.SHAPE_T_SEGMENT)
    shape.SetStart(point(x1, y1))
    shape.SetEnd(point(x2, y2))
    shape.SetLayer(layer)
    shape.SetWidth(pcbnew.FromMM(line_width))
    footprint.Add(shape)


def subtract_intervals(start: float, end: float, blocked: list[tuple[float, float]]):
    cursor = start
    for lower, upper in sorted(blocked):
        lower = max(start, lower)
        upper = min(end, upper)
        if upper <= cursor:
            continue
        if lower - cursor >= 0.25:
            yield cursor, lower
        cursor = max(cursor, upper)
    if end - cursor >= 0.25:
        yield cursor, end


def pad_bounds(footprint) -> list[tuple[float, float, float, float]]:
    result = []
    for pad in footprint.Pads():
        position = pad.GetPosition()
        size = pad.GetSize()
        x = pcbnew.ToMM(position.x)
        y = pcbnew.ToMM(position.y)
        half_width = pcbnew.ToMM(size.x) / 2
        half_height = pcbnew.ToMM(size.y) / 2
        result.append((x - half_width, y - half_height, x + half_width, y + half_height))
    return result


def add_silk_body_outline(footprint, width: float, height: float, clearance: float = 0.25):
    """Draw the component body, clipping each edge around solder-mask openings."""
    left, right = -width / 2, width / 2
    top, bottom = -height / 2, height / 2
    bounds = pad_bounds(footprint)

    for y in (top, bottom):
        blocked = [
            (x1 - clearance, x2 + clearance) for x1, y1, x2, y2 in bounds if y1 - clearance <= y <= y2 + clearance
        ]
        for x1, x2 in subtract_intervals(left, right, blocked):
            add_line(footprint, x1, y, x2, y)

    for x in (left, right):
        blocked = [
            (y1 - clearance, y2 + clearance) for x1, y1, x2, y2 in bounds if x1 - clearance <= x <= x2 + clearance
        ]
        for y1, y2 in subtract_intervals(top, bottom, blocked):
            add_line(footprint, x, y1, x, y2)


def add_pin1_marker(footprint, width: float, height: float):
    x = -width / 2 - 0.55
    y = -height / 2 - 0.55
    add_line(footprint, x, y, x + 0.45, y)
    add_line(footprint, x, y, x, y + 0.45)


def add_polarity_marker(footprint, height: float):
    y = -height / 2 + 0.65
    add_line(footprint, -0.3, y, 0.3, y)
    add_line(footprint, 0, y - 0.3, 0, y + 0.3)


def add_connector_key_marker(footprint, height: float):
    top = -height / 2
    add_line(footprint, -0.7, top, 0, top + 0.6)
    add_line(footprint, 0, top + 0.6, 0.7, top)


def finish_footprint(
    footprint,
    width: float,
    height: float,
    *,
    polarized: bool = False,
    keyed: bool = False,
):
    add_silk_body_outline(footprint, width, height)
    add_pin1_marker(footprint, width, height)
    if polarized:
        add_polarity_marker(footprint, height)
    if keyed:
        add_connector_key_marker(footprint, height)

    bounds = pad_bounds(footprint)
    half_width = max([width / 2 + 0.55, *(max(abs(x1), abs(x2)) for x1, _, x2, _ in bounds)]) + 0.25
    half_height = max([height / 2 + 0.55, *(max(abs(y1), abs(y2)) for _, y1, _, y2 in bounds)]) + 0.25
    add_rect(footprint, half_width * 2, half_height * 2, pcbnew.F_CrtYd, 0.05)
    return footprint


def new_footprint(name: str, width: float, height: float, *, attribute: int):
    footprint = pcbnew.FOOTPRINT(pcbnew.BOARD())
    footprint.SetFPID(pcbnew.LIB_ID("WB", name))
    footprint.SetAttributes(attribute)
    footprint.SetReference("REF**")
    footprint.SetValue(name)
    footprint.Reference().SetPosition(point(0, -height / 2 - 1.5))
    footprint.Value().SetVisible(False)
    add_rect(footprint, width, height, pcbnew.F_Fab, 0.1)
    return footprint


def microfit():
    footprint = new_footprint("MicroFit_2x2", 9.0, 9.0, attribute=pcbnew.FP_THROUGH_HOLE)
    for number, x, y in [(1, -1.5, -1.5), (2, 1.5, -1.5), (3, -1.5, 1.5), (4, 1.5, 1.5)]:
        add_pad(footprint, number, x, y, 2.4, 2.4, drill=1.1)
    return finish_footprint(footprint, 9.0, 9.0, keyed=True)


def fuse_4510():
    footprint = new_footprint("Fuse_4510", 6.5, 3.2, attribute=pcbnew.FP_SMD)
    add_pad(footprint, 1, -2.8, 0, 2.4, 3.0)
    add_pad(footprint, 2, 2.8, 0, 2.4, 3.0)
    return finish_footprint(footprint, 6.5, 3.2)


def sense_3637():
    footprint = new_footprint("Sense_3637", 9.5, 7.0, attribute=pcbnew.FP_SMD)
    add_pad(footprint, 1, -4.0, 0, 3.0, 5.0)
    add_pad(footprint, 2, 4.0, 0, 3.0, 5.0)
    return finish_footprint(footprint, 9.5, 7.0)


def isolated_power_tbd():
    """Nine-pin THT placeholder; not for production until an exact MPN is approved."""
    footprint = new_footprint("Isolated_48V_12V_240W_TBD", 38.0, 25.0, attribute=pcbnew.FP_THROUGH_HOLE)
    footprint.SetLibDescription(
        "PLACEHOLDER - NOT FOR PRODUCTION. Replace with the approved 36-60 V input, "
        "regulated 12 V isolated-power module land pattern."
    )
    for number, x, y in [(1, -15, -6), (2, -15, 6), (3, -15, 0), (4, 15, -6), (5, 15, 6), (6, 15, 0)]:
        add_pad(footprint, number, x, y, 4.0, 4.0, drill=1.1)
    for number, x, y in [(7, 0, -9), (8, 0, 0), (9, 0, 9)]:
        add_pad(footprint, number, x, y, 3.0, 3.0, drill=1.0)
    return finish_footprint(footprint, 38.0, 25.0, polarized=True)


def rpl_5():
    footprint = new_footprint("RPL-5.0_QFN24", 4.0, 6.0, attribute=pcbnew.FP_SMD)
    for index in range(8):
        add_pad(footprint, index + 1, -2.05, -2.45 + index * 0.7, 0.75, 0.30)
    for index in range(4):
        add_pad(footprint, index + 9, -1.05 + index * 0.7, 3.05, 0.30, 0.75)
    for index in range(8):
        add_pad(footprint, index + 13, 2.05, 2.45 - index * 0.7, 0.75, 0.30)
    for index in range(4):
        add_pad(footprint, index + 21, 1.05 - index * 0.7, -3.05, 0.30, 0.75)
    return finish_footprint(footprint, 4.0, 6.0)


def tps26633():
    footprint = new_footprint("TPS26633_RGE24", 4.0, 4.0, attribute=pcbnew.FP_SMD)
    for index in range(6):
        add_pad(footprint, index + 1, -2.15, -1.25 + index * 0.5, 0.8, 0.25)
        add_pad(footprint, index + 7, -1.25 + index * 0.5, 2.15, 0.25, 0.8)
        add_pad(footprint, index + 13, 2.15, 1.25 - index * 0.5, 0.8, 0.25)
        add_pad(footprint, index + 19, 1.25 - index * 0.5, -2.15, 0.25, 0.8)
    add_pad(footprint, 25, 0, 0, 2.5, 2.5)
    return finish_footprint(footprint, 4.0, 4.0)


def iso1042_dw16_hv():
    """TI DW-16 HV/isolation land pattern with 8.1 mm copper clearance."""
    footprint = new_footprint("ISO1042_DW16_HV", 7.5, 10.3, attribute=pcbnew.FP_SMD)
    for index in range(8):
        y = -4.445 + index * 1.27
        add_pad(footprint, index + 1, -4.875, y, 1.65, 0.60)
        add_pad(footprint, 16 - index, 4.875, y, 1.65, 0.60)
    return finish_footprint(footprint, 7.5, 10.3)


def act45b():
    footprint = new_footprint("ACT45B", 4.5, 3.2, attribute=pcbnew.FP_SMD)
    for number, x, y in [(1, -2.0, -1.05), (2, -2.0, 1.05), (3, 2.0, 1.05), (4, 2.0, -1.05)]:
        add_pad(footprint, number, x, y, 1.2, 1.1)
    return finish_footprint(footprint, 4.5, 3.2)


def can_tvs():
    footprint = new_footprint("CAN_TVS", 3.0, 3.0, attribute=pcbnew.FP_SMD)
    for number, x, y in [(1, -1.2, -0.8), (2, -1.2, 0.8), (3, 1.2, 0.8), (4, 1.2, -0.8)]:
        add_pad(footprint, number, x, y, 1.0, 0.7)
    return finish_footprint(footprint, 3.0, 3.0, polarized=True)


def sfm4():
    footprint = new_footprint("Panasonic_SFM4", 32.0, 16.0, attribute=pcbnew.FP_THROUGH_HOLE)
    for index in range(5):
        add_pad(footprint, index + 1, -12.0 + index * 6.0, -6.0, 2.0, 2.0, drill=1.0)
        add_pad(footprint, index + 6, 12.0 - index * 6.0, 6.0, 2.0, 2.0, drill=1.0)
    return finish_footprint(footprint, 32.0, 16.0)


def main() -> None:
    LIBRARY.mkdir(parents=True, exist_ok=True)
    io = pcbnew.PCB_IO_KICAD_SEXPR()
    if not LIBRARY.exists():
        io.FootprintLibCreate(str(LIBRARY))
    for footprint in [
        microfit(),
        fuse_4510(),
        sense_3637(),
        isolated_power_tbd(),
        rpl_5(),
        tps26633(),
        iso1042_dw16_hv(),
        act45b(),
        can_tvs(),
        sfm4(),
    ]:
        io.FootprintSave(str(LIBRARY), footprint)
    TABLE.write_text(
        '(fp_lib_table\n  (lib (name "WB")(type "KiCad")(uri "${KIPRJMOD}/WB.pretty")(options "")(descr ""))\n)\n',
        encoding="utf-8",
    )
    print(f"saved {len(list(LIBRARY.glob('*.kicad_mod')))} footprints to {LIBRARY}")


if __name__ == "__main__":
    main()
