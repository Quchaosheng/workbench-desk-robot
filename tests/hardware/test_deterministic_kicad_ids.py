from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "hardware/pcb/tools/deterministic_ids.py"


def load_module():
    spec = importlib.util.spec_from_file_location("deterministic_ids", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uuid_factory_replays_the_same_sequence_after_reset() -> None:
    module = load_module()
    factory = module.DeterministicUuidFactory("fixture")
    first = [factory.next() for _ in range(4)]
    factory.reset()
    assert [factory.next() for _ in range(4)] == first


def test_board_uuid_normalization_ignores_random_source_ids_and_preserves_references() -> None:
    module = load_module()
    first = (
        '(kicad_pcb (uuid "11111111-1111-4111-8111-111111111111") '
        '(uuid "22222222-2222-4222-8222-222222222222") '
        '(uuid "11111111-1111-4111-8111-111111111111"))'
    )
    second = (
        '(kicad_pcb (uuid "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa") '
        '(uuid "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb") '
        '(uuid "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))'
    )
    normalized_first, first_count = module.normalize_kicad_uuid_text(first, "controller")
    normalized_second, second_count = module.normalize_kicad_uuid_text(second, "controller")
    assert normalized_first == normalized_second
    assert first_count == second_count == 2
    uuids = module.UUID_PATTERN.findall(normalized_first)
    assert uuids[0][1] == uuids[2][1]


def test_board_canonicalization_sorts_repeated_top_level_objects_before_uuid_normalization() -> None:
    module = load_module()
    first = """(kicad_pcb
\t(version 20260206)
\t(footprint "R" (uuid "11111111-1111-4111-8111-111111111111") (property "Reference" "R2"))
\t(footprint "R" (uuid "22222222-2222-4222-8222-222222222222") (property "Reference" "R1"))
)
"""
    second = """(kicad_pcb
\t(version 20260206)
\t(footprint "R" (uuid "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa") (property "Reference" "R1"))
\t(footprint "R" (uuid "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb") (property "Reference" "R2"))
)
"""
    canonical_first = module.canonicalize_kicad_board_text(first)
    canonical_second = module.canonicalize_kicad_board_text(second)
    normalized_first, _ = module.normalize_kicad_uuid_text(canonical_first, "controller")
    normalized_second, _ = module.normalize_kicad_uuid_text(canonical_second, "controller")
    assert normalized_first == normalized_second
    assert "\r\n" not in module.canonicalize_kicad_board_text(first.replace("\n", "\r\n"))


def test_generators_use_deterministic_ids_without_memory_address_tiebreakers() -> None:
    schematic = (ROOT / "hardware/pcb/tools/generate_kicad_schematic.py").read_text(encoding="utf-8")
    board = (ROOT / "hardware/pcb/tools/generate_kicad_board.py").read_text(encoding="utf-8")
    assert "uuid4" not in schematic
    assert "UUID_FACTORY.reset()" in schematic
    assert "normalize_kicad_board" in board
    assert "id(first)" not in board
    assert "id(second)" not in board


def test_schematic_generator_repeats_identical_output_in_one_process() -> None:
    tools = ROOT / "hardware/pcb/tools"
    sys.path.insert(0, str(tools))
    try:
        spec = importlib.util.spec_from_file_location(
            "generate_kicad_schematic_determinism", tools / "generate_kicad_schematic.py"
        )
        assert spec and spec.loader
        generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(generator)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            generator.SYMBOL_LIBRARY = root / "controller.kicad_sym"
            generator.SYMBOL_TABLE = root / "sym-lib-table"
            first_path = root / "first.kicad_sch"
            second_path = root / "second.kicad_sch"
            generator.build_schematic().to_file(str(first_path), encoding="utf-8")
            generator.build_schematic().to_file(str(second_path), encoding="utf-8")
            assert first_path.read_bytes() == second_path.read_bytes()
    finally:
        sys.path.remove(str(tools))
