from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module():
    path = ROOT / "hardware/pcb/tools/constrain_freerouting_dsn.py"
    spec = importlib.util.spec_from_file_location("constrain_freerouting_dsn", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_adds_layer_constraint_inside_each_class_circuit() -> None:
    module = load_module()
    classes = "\n".join(
        f"(class {name} net\n  (circuit\n    (use_via via)\n  )\n  (rule (width 1))\n)" for name in module.CLASS_LAYERS
    )

    constrained = module.constrain_text(f"(network\n{classes}\n)")

    for name, layers in module.CLASS_LAYERS.items():
        start = constrained.index(f"(class {name} ")
        end = module.block_end(constrained, start)
        block = constrained[start:end]
        assert f"(use_layer {' '.join(layers)})" in block


def test_scanner_ignores_parentheses_inside_strings() -> None:
    module = load_module()
    text = '(class X net (circuit (use_via "via(1)")) (rule (width 1))) trailing'
    assert text[: module.block_end(text, 0)].endswith("(rule (width 1)))")
