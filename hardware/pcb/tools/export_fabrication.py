from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "kicad" / "controller.kicad_pcb"
SCHEMATIC = ROOT / "kicad" / "controller.kicad_sch"
FAB = ROOT / "fabrication"
GENERATED = ROOT / "generated"


def find_cli() -> str:
    found = shutil.which("kicad-cli")
    if found:
        return found
    candidate = Path.home() / "AppData/Local/Programs/KiCad/10.0/bin/kicad-cli.exe"
    if candidate.exists():
        return str(candidate)
    raise SystemExit("KiCad 10 kicad-cli was not found")


def run(*args: str) -> None:
    subprocess.run([find_cli(), *args], check=True, cwd=ROOT.parents[1])


def _sanitize_empty_json_keys(value):
    if isinstance(value, dict):
        return {(key or "unlabeled"): _sanitize_empty_json_keys(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_empty_json_keys(item) for item in value]
    return value


def board_design_counts(board_text: str) -> dict[str, object]:
    def count(expression: str) -> int:
        return len(re.findall(rf"(?m)^\s*\({re.escape(expression)}(?:\s|$)", board_text))

    copper_layers = re.findall(
        r'^\s*\(\d+ "((?:F|B|In\d+)\.Cu)" signal\)$',
        board_text,
        flags=re.MULTILINE,
    )
    return {
        "footprints": count("footprint"),
        "track_segments": count("segment"),
        "vias": count("via"),
        "zones": count("zone"),
        "copper_layers": copper_layers,
    }


def normalize_board_stats(stats_path: Path, board_path: Path = BOARD) -> None:
    stats = _sanitize_empty_json_keys(json.loads(stats_path.read_text(encoding="utf-8")))
    raw_via_summary = stats.get("vias", {})
    design_counts = board_design_counts(board_path.read_text(encoding="utf-8"))
    stats["kicad_raw_via_summary"] = raw_via_summary
    stats["vias"] = {"total": design_counts["vias"]}
    stats["design_counts"] = design_counts
    stats_path.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    gerbers = FAB / "gerbers"
    drawings = FAB / "drawings"
    gerbers.mkdir(parents=True, exist_ok=True)
    drawings.mkdir(parents=True, exist_ok=True)
    run("pcb", "drc", "--exit-code-violations", str(BOARD), "-o", str(GENERATED / "drc.rpt"))
    run("sch", "erc", "--exit-code-violations", str(SCHEMATIC), "-o", str(GENERATED / "erc.rpt"))
    run(
        "pcb",
        "export",
        "gerbers",
        "-o",
        str(gerbers),
        "-l",
        "F.Cu,In1.Cu,In2.Cu,In3.Cu,In4.Cu,In5.Cu,In6.Cu,B.Cu,F.Paste,B.Paste,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts",
        str(BOARD),
    )
    run(
        "pcb",
        "export",
        "drill",
        "-o",
        str(gerbers),
        "--excellon-separate-th",
        "--generate-map",
        "--map-format",
        "pdf",
        "--generate-report",
        "--report-path",
        str(FAB / "drill-report.txt"),
        str(BOARD),
    )
    run("pcb", "export", "pos", "-o", str(FAB / "positions.csv"), "--format", "csv", "--units", "mm", str(BOARD))
    run("pcb", "export", "ipcd356", "-o", str(FAB / "controller.d356"), str(BOARD))
    run(
        "sch",
        "export",
        "netlist",
        "-o",
        str(GENERATED / "controller.net"),
        "--format",
        "kicadxml",
        str(SCHEMATIC),
    )
    run(
        "pcb",
        "export",
        "pdf",
        "-o",
        str(drawings / "assembly.pdf"),
        "-l",
        "F.Fab,F.Silkscreen,Edge.Cuts",
        "--mode-single",
        "--black-and-white",
        "--sketch-pads-on-fab-layers",
        "--scale",
        "0",
        str(BOARD),
    )
    run(
        "pcb",
        "export",
        "pdf",
        "-o",
        str(drawings / "routing-review.pdf"),
        "-l",
        "F.Cu,F.Silkscreen,Edge.Cuts",
        "--mode-single",
        "--black-and-white",
        "--scale",
        "0",
        str(BOARD),
    )
    run("sch", "export", "pdf", "-o", str(drawings / "controller-schematic.pdf"), str(SCHEMATIC))
    stats_path = FAB / "board-stats.json"
    run("pcb", "export", "stats", "-o", str(stats_path), "--format", "json", str(BOARD))
    normalize_board_stats(stats_path)
    run(
        "pcb",
        "render",
        "-o",
        str(FAB / "board-preview.png"),
        "--width",
        "1400",
        "--height",
        "900",
        "--side",
        "top",
        "--background",
        "opaque",
        str(BOARD),
    )
    (ROOT / "kicad/controller.kicad_prl").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
