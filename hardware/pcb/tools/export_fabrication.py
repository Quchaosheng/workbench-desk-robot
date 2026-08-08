from __future__ import annotations

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
        "F.Cu,In1.Cu,In2.Cu,In3.Cu,In4.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts",
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
        "pcb",
        "export",
        "pdf",
        "-o",
        str(drawings / "assembly.pdf"),
        "-l",
        "F.Silkscreen,F.Cu,Edge.Cuts",
        "--mode-single",
        "--black-and-white",
        str(BOARD),
    )
    run("sch", "export", "pdf", "-o", str(drawings / "controller-schematic.pdf"), str(SCHEMATIC))
    run("pcb", "export", "stats", "-o", str(FAB / "board-stats.json"), "--format", "json", str(BOARD))
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
