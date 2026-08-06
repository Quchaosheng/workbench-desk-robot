import hashlib
import json
import random
from pathlib import Path
from typing import Any

FROZEN_DISTRIBUTION = {
    "grasp_failure": 3,
    "moving_target": 3,
    "none": 3,
    "occlusion": 3,
}

P2_SCENE_VARIANTS = {"path_blocked", "low_light", "multi_object"}
P2_FAULT_TYPES = {
    "actuator_timeout",
    "camera_dropout",
    "grasp_failure",
    "moving_target",
    "occlusion",
    "stale_observation",
}


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def materialize_scenario(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the deterministic scene parameters owned by the scenario seed."""
    rng = random.Random(manifest["seed"])
    scene_variant = manifest.get("scene_variant", "baseline")
    object_count = 1 if scene_variant != "multi_object" else 3
    return {
        "scenario_id": manifest["scenario_id"],
        "seed": manifest["seed"],
        "fault_type": manifest["fault_type"],
        "scene_variant": scene_variant,
        "lighting_lux": 110 if scene_variant == "low_light" else 520,
        "path_obstacle": scene_variant == "path_blocked",
        "camera_noise": round(rng.uniform(0.005, 0.025), 6),
        "objects": [
            {
                "entity_id": "red_block" if index == 0 else f"red_block_{index + 1}",
                "x": round(rng.uniform(-0.18, 0.18), 6),
                "y": round(rng.uniform(-0.12, 0.12), 6),
                "yaw": round(rng.uniform(-3.141593, 3.141593), 6),
            }
            for index in range(object_count)
        ],
    }


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def reproducibility_hash(path: Path) -> str:
    return canonical_hash(materialize_scenario(load_manifest(path)))
