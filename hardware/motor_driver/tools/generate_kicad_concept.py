from __future__ import annotations

import csv
import json
import re
from itertools import pairwise
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

try:
    import pcbnew
except ImportError as exc:
    raise SystemExit("Run with KiCad's bundled Python interpreter (bin/python.exe)") from exc

PACKAGE = Path(__file__).resolve().parents[1]
OUTPUT = PACKAGE / "kicad" / "traction-childboard-concept.kicad_pcb"
UUID_PATTERN = re.compile(r'\(uuid "[0-9a-f-]+"\)')


def point(x_mm: float, y_mm: float):
    return pcbnew.VECTOR2I(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm))


def add_line(board, start: tuple[float, float], end: tuple[float, float], layer: int, width_mm: float) -> None:
    line = pcbnew.PCB_SHAPE(board)
    line.SetShape(pcbnew.SHAPE_T_SEGMENT)
    line.SetStart(point(*start))
    line.SetEnd(point(*end))
    line.SetLayer(layer)
    line.SetWidth(pcbnew.FromMM(width_mm))
    board.Add(line)


def add_text(board, value: str, x_mm: float, y_mm: float, layer: int, size_mm: float) -> None:
    item = pcbnew.PCB_TEXT(board)
    item.SetText(value)
    item.SetPosition(point(x_mm, y_mm))
    item.SetLayer(layer)
    item.SetTextSize(point(size_mm, size_mm))
    item.SetTextThickness(pcbnew.FromMM(0.15))
    board.Add(item)


def add_mounting_hole(board, reference: str, x_mm: float, y_mm: float, diameter_mm: float) -> None:
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetReference(reference)
    footprint.SetValue(f"NPTH_{diameter_mm:.1f}mm")
    footprint.SetPosition(point(x_mm, y_mm))
    footprint.Reference().SetVisible(False)
    footprint.Value().SetVisible(False)
    pad = pcbnew.PAD(footprint)
    pad.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
    pad.SetSize(point(diameter_mm, diameter_mm))
    pad.SetDrillSize(point(diameter_mm, diameter_mm))
    layers = pcbnew.LSET()
    layers.AddLayer(pcbnew.F_Mask)
    layers.AddLayer(pcbnew.B_Mask)
    pad.SetLayerSet(layers)
    pad.SetPosition(point(x_mm, y_mm))
    footprint.Add(pad)
    board.Add(footprint)


def add_block(board, row: dict[str, str]) -> None:
    x = float(row["x_mm"])
    y = float(row["y_mm"])
    half_width = float(row["width_mm"]) / 2
    half_height = float(row["height_mm"]) / 2
    corners = [
        (x - half_width, y - half_height),
        (x + half_width, y - half_height),
        (x + half_width, y + half_height),
        (x - half_width, y + half_height),
        (x - half_width, y - half_height),
    ]
    for start, end in pairwise(corners):
        add_line(board, start, end, pcbnew.F_Fab, 0.2)
    add_text(board, row["block_id"], x, y, pcbnew.F_Fab, 1.2)


def canonicalize_items(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    children: list[str] = []
    index = 1
    while index < len(lines) - 1:
        start = index
        depth = lines[index].count("(") - lines[index].count(")")
        index += 1
        while depth > 0 and index < len(lines) - 1:
            depth += lines[index].count("(") - lines[index].count(")")
            index += 1
        children.append("".join(lines[start:index]))
    dynamic_prefixes = ("\t(footprint", "\t(gr_line", "\t(gr_text")
    static = [child for child in children if not child.startswith(dynamic_prefixes)]
    dynamic = [child for child in children if child.startswith(dynamic_prefixes)]
    dynamic.sort(key=lambda child: UUID_PATTERN.sub("", child))
    path.write_text(lines[0] + "".join(static + dynamic) + lines[-1], encoding="utf-8")


def normalize_uuids(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    counter = 0

    def replacement(_match: re.Match[str]) -> str:
        nonlocal counter
        value = uuid5(NAMESPACE_URL, f"workbench-traction-childboard-concept-{counter}")
        counter += 1
        return f'(uuid "{value}")'

    path.write_text(UUID_PATTERN.sub(replacement, text), encoding="utf-8")


def build() -> None:
    spec = json.loads((PACKAGE / "electrical-spec.json").read_text(encoding="utf-8"))
    layout = spec["layout_concept"]
    width = float(layout["board_width_mm"])
    height = float(layout["board_height_mm"])
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    title = board.GetTitleBlock()
    title.SetTitle("Workbench-1 Dual-Axis Traction Childboard Mechanical Concept")
    title.SetRevision(spec["revision"])
    board.SetTitleBlock(title)
    outline = [(0.0, 0.0), (width, 0.0), (width, height), (0.0, height), (0.0, 0.0)]
    for start, end in pairwise(outline):
        add_line(board, start, end, pcbnew.Edge_Cuts, 0.1)
    for index, center in enumerate(layout["mounting_hole_centers_mm"], start=1):
        add_mounting_hole(board, f"H{index}", float(center[0]), float(center[1]), 3.2)
    with (PACKAGE / "placement-plan.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            add_block(board, row)
    add_text(board, "CONCEPT ONLY - NO ELECTRICAL FOOTPRINTS - DO NOT ORDER", width / 2, 79, pcbnew.F_SilkS, 1.4)
    add_text(board, "118x82 / MOUNT 108x72 / 4x DIA 3.2 / HEIGHT 20 MAX", width / 2, 3, pcbnew.F_SilkS, 1.0)
    pcbnew.SaveBoard(str(OUTPUT), board)
    canonicalize_items(OUTPUT)
    normalize_uuids(OUTPUT)


if __name__ == "__main__":
    build()
    print(OUTPUT)
