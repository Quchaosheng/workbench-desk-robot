from __future__ import annotations

import csv
import html
import json
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
OUTPUT = PACKAGE / "generated" / "placement-review.svg"
SCALE = 8
MARGIN = 48

COLORS = {
    "power": "#d95d39",
    "power_stage": "#a63d40",
    "motor": "#3578a8",
    "field_bus": "#3d7a80",
    "logic": "#4f7f52",
    "safety": "#bd8b13",
}
DISPLAY_LABELS = {
    "J_PWR": "12 V INPUT",
    "F1": "FUSE",
    "Q1": "REVERSE BLOCK",
    "C_BULK": "BULK",
    "CLAMP": "REGEN SINK",
    "U1": "DRV8962",
    "CAN": "CAN FD",
    "CTRL": "LOCAL MCU",
    "SAFE_GATE": "SAFETY A/B",
    "J_ENC_L": "LEFT ENCODER",
    "J_ENC_R": "RIGHT ENCODER",
    "J_ML": "LEFT MOTOR",
    "J_MR": "RIGHT MOTOR",
}


def read_rows() -> list[dict[str, str]]:
    with (PACKAGE / "placement-plan.csv").open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def render_svg() -> str:
    spec = json.loads((PACKAGE / "electrical-spec.json").read_text(encoding="utf-8"))
    layout = spec["layout_concept"]
    board_width = float(layout["board_width_mm"])
    board_height = float(layout["board_height_mm"])
    canvas_width = int(board_width * SCALE + 2 * MARGIN)
    canvas_height = int(board_height * SCALE + 2 * MARGIN + 52)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" '
            f'height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}">'
        ),
        '<rect width="100%" height="100%" fill="#f4f6f7"/>',
        (
            f'<rect x="{MARGIN}" y="{MARGIN}" width="{board_width * SCALE:.1f}" '
            f'height="{board_height * SCALE:.1f}" fill="#dce9df" stroke="#1e3325" stroke-width="3"/>'
        ),
    ]
    for x_mm, y_mm in layout["mounting_hole_centers_mm"]:
        lines.append(
            f'<circle cx="{MARGIN + x_mm * SCALE:.1f}" cy="{MARGIN + y_mm * SCALE:.1f}" '
            f'r="{layout["mounting_hole_diameter_mm"] * SCALE / 2:.1f}" fill="#f4f6f7" '
            'stroke="#1e3325" stroke-width="2"/>'
        )
    for row in read_rows():
        x = MARGIN + (float(row["x_mm"]) - float(row["width_mm"]) / 2) * SCALE
        y = MARGIN + (float(row["y_mm"]) - float(row["height_mm"]) / 2) * SCALE
        width = float(row["width_mm"]) * SCALE
        height = float(row["height_mm"]) * SCALE
        color = COLORS[row["domain"]]
        block_id = html.escape(row["block_id"])
        display_label = html.escape(DISPLAY_LABELS[row["block_id"]])
        lines.extend(
            [
                (
                    f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" '
                    f'fill="{color}" fill-opacity="0.82" stroke="#172026" stroke-width="1.5"/>'
                ),
                (
                    f'<text x="{x + width / 2:.1f}" y="{y + height / 2 - 3:.1f}" '
                    'text-anchor="middle" font-family="Arial, sans-serif" font-size="12" '
                    f'font-weight="700" fill="#ffffff">{block_id}</text>'
                ),
                (
                    f'<text x="{x + width / 2:.1f}" y="{y + height / 2 + 12:.1f}" '
                    'text-anchor="middle" font-family="Arial, sans-serif" font-size="9" '
                    f'fill="#ffffff">{display_label}</text>'
                ),
            ]
        )
    title_y = MARGIN + board_height * SCALE + 30
    lines.extend(
        [
            (
                f'<text x="{canvas_width / 2:.1f}" y="26" text-anchor="middle" '
                'font-family="Arial, sans-serif" font-size="18" font-weight="700" fill="#172026">'
                "DUAL-AXIS TRACTION CHILDBOARD - CONCEPT-A</text>"
            ),
            (
                f'<text x="{canvas_width / 2:.1f}" y="{title_y:.1f}" text-anchor="middle" '
                'font-family="Arial, sans-serif" font-size="16" font-weight="700" fill="#a3262a">'
                "CONCEPT ONLY - DO NOT ORDER</text>"
            ),
            (
                f'<text x="{canvas_width / 2:.1f}" y="{title_y + 20:.1f}" text-anchor="middle" '
                'font-family="Arial, sans-serif" font-size="12" fill="#172026">'
                "118 x 82 mm | 108 x 72 mm mount pattern | 4 x 3.2 mm holes | 20 mm max assembly envelope</text>"
            ),
            "</svg>",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_svg(), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
