from __future__ import annotations

import copy
import csv
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]


def load_generator():
    path = ROOT / "hardware/mechanical/tools/generate_artifacts.py"
    spec = importlib.util.spec_from_file_location("mechanical_issue_generator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_operations_validator():
    path = ROOT / "hardware/tools/validate_operations_readiness.py"
    spec = importlib.util.spec_from_file_location("mechanical_operations_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_directional_stability_publishes_all_edges_and_pose_ids() -> None:
    module = load_generator()
    report = module.analyse()
    assert report["stability"]["directions"] == ["+X", "-X", "+Y", "-Y"]
    assert set(report["stability"]["cases"]) == {
        "stowed",
        "raised",
        "payload",
        "shared_workspace",
        "emergency_stop",
        "stabilizer_deployed",
    }
    for case in report["stability"]["cases"].values():
        assert set(case["directions"]) == {"+X", "-X", "+Y", "-Y"}
        assert all(result["pose_identifier"] for result in case["directions"].values())
        assert all(result["limiting_support_edge"] for result in case["directions"].values())
    assert report["stability"]["gates"]["drive"]["limiting_direction"] == "-Y"
    assert report["stability"]["gates"]["stabilized"]["limiting_direction"] == "-Y"


def test_audited_tip_angles_fail_configured_thresholds() -> None:
    module = load_generator()
    polygon = {
        "edges": {
            "+X": {"name": "right", "axis": "x", "coordinate_mm": 100},
            "-X": {"name": "left", "axis": "x", "coordinate_mm": -100},
            "+Y": {"name": "rear", "axis": "y", "coordinate_mm": 100},
            "-Y": {"name": "front", "axis": "y", "coordinate_mm": -100},
        }
    }
    fixtures = json.loads((ROOT / "hardware/mechanical/fixtures/stability-regression.json").read_text(encoding="utf-8"))
    for fixture in fixtures:
        audited_angle = fixture["tip_angle_deg"]
        threshold = fixture["threshold_deg"]
        height = 100.0
        margin = height * module.math.tan(module.math.radians(audited_angle))
        result = module.calculate_directional_stability(
            [0, 0, height],
            {
                "edges": {
                    direction: {**edge, "coordinate_mm": margin if direction in {"+X", "+Y"} else -margin}
                    for direction, edge in polygon["edges"].items()
                }
            },
            "regression",
            threshold,
        )
        assert result["pass"] is False
        assert result["minimum_tip_angle_deg"] < threshold


def test_mass_model_rejects_duplicate_and_non_finite_components() -> None:
    module = load_generator()
    spec = json.loads((ROOT / "hardware/mechanical/design-spec.json").read_text(encoding="utf-8"))
    broken = copy.deepcopy(spec)
    broken["components"][1]["id"] = broken["components"][0]["id"]
    broken["components"][2]["mass_kg"] = float("nan")
    validation = module.validate_mass_model(broken)
    assert validation["pass"] is False
    assert validation["checks"]["component_ids_are_unique"] is False
    assert validation["checks"]["component_records_are_valid"] is False


def test_missing_direction_fails_closed_in_analysis() -> None:
    module = load_generator()
    broken = copy.deepcopy(module.SPEC)
    del broken["stability_analysis"]["support_polygons"]["drive"]["edges"]["+X"]
    original = module.SPEC
    module.SPEC = broken
    try:
        report = module.analyse()
    finally:
        module.SPEC = original
    assert report["checks"]["drive_tip_angle_at_least_25_deg"] is False
    assert report["checks"]["stabilized_tip_angle_at_least_35_deg"] is False


def test_analysis_schema_and_mass_hash_are_current() -> None:
    report = json.loads((ROOT / "hardware/mechanical/generated/analysis.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "hardware/mechanical/analysis.schema.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(report))
    assert errors == []
    assert report["mass_model"]["mass_kg"] == 77.5
    assert len(report["mass_model"]["mass_model_sha256"]) == 64
    assert report["status"] == "CONCEPT_PHYSICAL_VALIDATION_REQUIRED"


def test_stale_55kg_report_cannot_pass_readiness_validation() -> None:
    validator = load_operations_validator()
    spec = json.loads((ROOT / "hardware/mechanical/design-spec.json").read_text(encoding="utf-8"))
    report = json.loads((ROOT / "hardware/mechanical/generated/analysis.json").read_text(encoding="utf-8"))
    stale = copy.deepcopy(report)
    stale["mass_kg"] = 55.0
    stale["mass_model"]["mass_kg"] = 55.0
    with (ROOT / "hardware/mechanical/mass-ledger.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    validation = validator.validate_mechanical_mass_model(spec, stale, rows)
    assert validation["pass"] is False
    assert validation["checks"]["generated_mass_matches_source"] is False
