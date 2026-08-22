from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "hardware/pcb/tools/embed_stackup.py"
BOARD = ROOT / "hardware/pcb/kicad/controller.kicad_pcb"
STACKUP_CSV = ROOT / "hardware/pcb/fabrication/stackup.csv"


def load_module():
    spec = importlib.util.spec_from_file_location("embed_stackup", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def board_fixture(*, setup: str = "\t(setup\n\t\t(pad_to_mask_clearance 0)\n\t)", omit_layer: str = "") -> str:
    layers = ["F.Cu", *[f"In{index}.Cu" for index in range(1, 7)], "B.Cu"]
    layer_ids = [0, 4, 6, 8, 10, 12, 14, 2]
    declarations = [
        f'\t\t({layer_id} "{layer}" signal)'
        for layer_id, layer in zip(layer_ids, layers, strict=True)
        if layer != omit_layer
    ]
    return (
        "(kicad_pcb\n"
        "\t(version 20260206)\n"
        '\t(generator "pcbnew")\n'
        "\t(general\n"
        "\t\t(thickness 1.6)\n"
        "\t)\n"
        "\t(layers\n" + "\n".join(declarations) + "\n\t)\n" + setup + "\n)\n"
    )


class EmbeddedStackupTests(unittest.TestCase):
    def test_kicad_layers_electrical_spec_and_stackup_csv_agree(self) -> None:
        module = load_module()
        spec = module.load_stackup_spec()
        expected_layers = tuple(layer.name for layer in spec.copper_layers)
        self.assertEqual(module.read_declared_copper_layers(BOARD), expected_layers)
        with STACKUP_CSV.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(tuple(row["layer"] for row in rows), expected_layers)
        self.assertEqual(
            tuple((Decimal(row["copper_oz"]), Decimal(row["dielectric_to_next_mm"])) for row in rows),
            tuple((layer.copper_oz, layer.dielectric_to_next_mm) for layer in spec.copper_layers),
        )

    def test_embed_current_board_copy_is_exact_and_idempotent(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "controller.kicad_pcb"
            candidate.write_bytes(BOARD.read_bytes())
            spec = module.embed_stackup(candidate)
            first = candidate.read_bytes()
            embedded = module.validate_embedded_stackup(candidate, spec)
            module.embed_stackup(candidate)
            self.assertEqual(candidate.read_bytes(), first)

        copper = [layer for layer in embedded.layers if layer.layer_type == "copper"]
        dielectrics = [layer for layer in embedded.layers if layer.name.startswith("dielectric ")]
        self.assertEqual(
            [layer.thickness_mm for layer in copper],
            [
                Decimal("0.070"),
                Decimal("0.035"),
                Decimal("0.070"),
                Decimal("0.035"),
                Decimal("0.035"),
                Decimal("0.070"),
                Decimal("0.035"),
                Decimal("0.070"),
            ],
        )
        self.assertEqual(
            [layer.thickness_mm for layer in dielectrics],
            [
                Decimal("0.10"),
                Decimal("0.18"),
                Decimal("0.18"),
                Decimal("0.26"),
                Decimal("0.18"),
                Decimal("0.18"),
                Decimal("0.10"),
            ],
        )
        self.assertTrue(all(layer.material == "FR-4" for layer in dielectrics))
        physical_total = sum(
            (layer.thickness_mm for layer in (*copper, *dielectrics) if layer.thickness_mm is not None),
            start=Decimal(0),
        )
        self.assertEqual(physical_total, Decimal("1.60"))
        self.assertEqual(embedded.dielectric_constraints, "no")
        self.assertEqual(spec.copper_finish, "ENIG")
        self.assertEqual(embedded.copper_finish, "ENIG")

    def test_existing_stackup_is_replaced_without_duplication(self) -> None:
        module = load_module()
        setup = '\t(setup\n\t\t(stackup\n\t\t\t(layer "bogus" (type "core"))\n\t\t)\n\t)'
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "fixture.kicad_pcb"
            candidate.write_text(board_fixture(setup=setup), encoding="utf-8")
            module.embed_stackup(candidate)
            text = candidate.read_text(encoding="utf-8")
            self.assertEqual(text.count("(stackup"), 1)
            self.assertNotIn("bogus", text)
            module.validate_embedded_stackup(candidate)

    def test_layer_drift_fails_before_writing(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "fixture.kicad_pcb"
            candidate.write_text(board_fixture(omit_layer="In6.Cu"), encoding="utf-8")
            before = candidate.read_bytes()
            with self.assertRaisesRegex(ValueError, "board copper layers"):
                module.embed_stackup(candidate)
            self.assertEqual(candidate.read_bytes(), before)

    def test_missing_setup_fails_before_writing(self) -> None:
        module = load_module()
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "fixture.kicad_pcb"
            candidate.write_text(board_fixture(setup=""), encoding="utf-8")
            before = candidate.read_bytes()
            with self.assertRaisesRegex(ValueError, "no setup expression"):
                module.embed_stackup(candidate)
            self.assertEqual(candidate.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
