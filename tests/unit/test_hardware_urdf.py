import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_NAME = "workbench_hardware_urdf_parser"
MODULE_PATH = ROOT / "libs/hardware/workbench/hardware/urdf_parser.py"
MODULE_SPEC = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError(f"could not load HW1 parser from {MODULE_PATH}")
URDF_PARSER = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_NAME] = URDF_PARSER
MODULE_SPEC.loader.exec_module(URDF_PARSER)

UrdfMotorConfigError = URDF_PARSER.UrdfMotorConfigError
dump_motor_config_yaml = URDF_PARSER.dump_motor_config_yaml
load_urdf_motor_config = URDF_PARSER.load_urdf_motor_config
parse_urdf_motor_config = URDF_PARSER.parse_urdf_motor_config

ARM_JOINTS = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)

UR5E_SHAPE_URDF = """<?xml version="1.0"?>
<robot name="ur5e">
  <joint name="world_joint" type="fixed"/>
  <joint name="shoulder_pan_joint" type="revolute">
    <limit effort="150.0" lower="-6.283185307179586" upper="6.283185307179586" velocity="3.141592653589793"/>
  </joint>
  <joint name="shoulder_lift_joint" type="revolute">
    <limit effort="150.0" lower="-6.283185307179586" upper="6.283185307179586" velocity="3.141592653589793"/>
  </joint>
  <joint name="elbow_joint" type="revolute">
    <limit effort="150.0" lower="-3.141592653589793" upper="3.141592653589793" velocity="3.141592653589793"/>
  </joint>
  <joint name="wrist_1_joint" type="revolute">
    <limit effort="28.0" lower="-6.283185307179586" upper="6.283185307179586" velocity="3.141592653589793"/>
  </joint>
  <joint name="wrist_2_joint" type="revolute">
    <limit effort="28.0" lower="-6.283185307179586" upper="6.283185307179586" velocity="3.141592653589793"/>
  </joint>
  <joint name="wrist_3_joint" type="revolute">
    <limit effort="28.0" lower="-6.283185307179586" upper="6.283185307179586" velocity="3.141592653589793"/>
  </joint>
  <transmission name="shoulder_pan_trans">
    <joint name="shoulder_pan_joint"/>
    <actuator name="shoulder_pan_motor"><mechanicalReduction>1</mechanicalReduction></actuator>
  </transmission>
</robot>
"""


class HardwareUrdfTests(unittest.TestCase):
    def test_extracts_requested_ur5e_motor_limits_in_order(self) -> None:
        configs = parse_urdf_motor_config(UR5E_SHAPE_URDF, ARM_JOINTS)

        self.assertEqual(tuple(config.name for config in configs), ARM_JOINTS)
        self.assertEqual(len(configs), 6)
        self.assertEqual(configs[0].max_torque_nm, 150.0)
        self.assertEqual(configs[3].max_torque_nm, 28.0)
        self.assertEqual(configs[0].max_velocity_rad_s, 3.141592653589793)
        self.assertEqual(configs[0].mechanical_reduction, 1.0)
        self.assertIsNone(configs[1].mechanical_reduction)

    def test_yaml_is_deterministic_and_keeps_unknown_reduction_explicit(self) -> None:
        configs = parse_urdf_motor_config(UR5E_SHAPE_URDF, ARM_JOINTS)
        first = dump_motor_config_yaml(configs)
        second = dump_motor_config_yaml(configs)

        self.assertEqual(first, second)
        self.assertIn('  - name: "shoulder_pan_joint"', first)
        self.assertIn("    mechanical_reduction: 1.0", first)
        self.assertIn("    mechanical_reduction: null", first)

    def test_loads_expanded_urdf_from_utf8_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            urdf_path = Path(temporary_directory) / "ur5e.urdf"
            urdf_path.write_text(UR5E_SHAPE_URDF, encoding="utf-8")
            configs = load_urdf_motor_config(urdf_path, ARM_JOINTS)

        self.assertEqual(len(configs), 6)

    def test_rejects_missing_or_untrusted_parameters(self) -> None:
        cases = {
            "invalid xml": "<robot>",
            "missing joint": UR5E_SHAPE_URDF,
            "missing effort": UR5E_SHAPE_URDF.replace('effort="150.0" ', "", 1),
            "non finite velocity": UR5E_SHAPE_URDF.replace('velocity="3.141592653589793"', 'velocity="nan"', 1),
            "reversed limits": UR5E_SHAPE_URDF.replace(
                'lower="-6.283185307179586" upper="6.283185307179586"',
                'lower="7" upper="6"',
                1,
            ),
        }
        for label, urdf_xml in cases.items():
            with self.subTest(label=label), self.assertRaises(UrdfMotorConfigError):
                requested = ("missing_joint",) if label == "missing joint" else ARM_JOINTS
                parse_urdf_motor_config(urdf_xml, requested)

    def test_rejects_duplicate_mechanical_reduction(self) -> None:
        duplicate = UR5E_SHAPE_URDF.replace(
            "</robot>",
            """
  <transmission name="shoulder_pan_trans_duplicate">
    <joint name="shoulder_pan_joint"/>
    <actuator name="second_motor"><mechanicalReduction>2</mechanicalReduction></actuator>
  </transmission>
</robot>
""",
        )

        with self.assertRaises(UrdfMotorConfigError):
            parse_urdf_motor_config(duplicate, ARM_JOINTS)


if __name__ == "__main__":
    unittest.main()
