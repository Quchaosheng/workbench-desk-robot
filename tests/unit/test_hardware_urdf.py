import tempfile
import unittest
from pathlib import Path

import workbench.kernel
from workbench.hardware import (
    MotorConfig,
    UrdfMotorConfigError,
    dump_motor_config_yaml,
    load_urdf_motor_config,
    parse_urdf_motor_config,
)

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
    def test_installed_package_exposes_hardware_api(self) -> None:
        self.assertEqual(MotorConfig.__module__, "workbench.hardware.urdf_parser")
        self.assertIsNotNone(workbench.kernel.__path__)

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

    def test_rejects_duplicate_limit_elements(self) -> None:
        duplicate = UR5E_SHAPE_URDF.replace(
            '<limit effort="150.0" lower="-6.283185307179586" upper="6.283185307179586" '
            'velocity="3.141592653589793"/>',
            """<limit effort="150.0" lower="-6.283185307179586" upper="6.283185307179586" velocity="3.141592653589793"/>
    <limit effort="1.0" lower="-1.0" upper="1.0" velocity="1.0"/>""",
            1,
        )

        with self.assertRaises(UrdfMotorConfigError):
            parse_urdf_motor_config(duplicate, ARM_JOINTS)

    def test_rejects_malformed_transmission_structures(self) -> None:
        cases = {
            "multiple actuators with reduction": UR5E_SHAPE_URDF.replace(
                '<actuator name="shoulder_pan_motor"><mechanicalReduction>1</mechanicalReduction></actuator>',
                """<actuator name="shoulder_pan_motor"><mechanicalReduction>1</mechanicalReduction></actuator>
    <actuator name="ambiguous_motor"/>""",
            ),
            "multiple joints without reduction": UR5E_SHAPE_URDF.replace(
                '<joint name="shoulder_pan_joint"/>\n    '
                '<actuator name="shoulder_pan_motor"><mechanicalReduction>1</mechanicalReduction></actuator>',
                '<joint name="shoulder_pan_joint"/>\n    <joint name="elbow_joint"/>\n    '
                '<actuator name="shoulder_pan_motor"/>',
            ),
            "misplaced reduction": UR5E_SHAPE_URDF.replace(
                '<actuator name="shoulder_pan_motor"><mechanicalReduction>1</mechanicalReduction></actuator>',
                '<actuator name="shoulder_pan_motor"/>\n    <mechanicalReduction>1</mechanicalReduction>',
            ),
        }

        for label, urdf_xml in cases.items():
            with self.subTest(label=label), self.assertRaises(UrdfMotorConfigError):
                parse_urdf_motor_config(urdf_xml, ARM_JOINTS)

    def test_rejects_duplicate_and_empty_joint_declarations(self) -> None:
        duplicate_joint = UR5E_SHAPE_URDF.replace(
            '<joint name="world_joint" type="fixed"/>',
            '<joint name="shoulder_pan_joint" type="fixed"/>',
        )
        empty_joint = UR5E_SHAPE_URDF.replace('name="world_joint"', 'name="   "')
        empty_transmission_joint = UR5E_SHAPE_URDF.replace(
            '<joint name="shoulder_pan_joint"/>\n    <actuator',
            '<joint name=""/>\n    <actuator',
        )

        for label, urdf_xml in {
            "duplicate joint": duplicate_joint,
            "empty joint": empty_joint,
            "empty transmission joint": empty_transmission_joint,
        }.items():
            with self.subTest(label=label), self.assertRaises(UrdfMotorConfigError):
                parse_urdf_motor_config(urdf_xml, ARM_JOINTS)


if __name__ == "__main__":
    unittest.main()
