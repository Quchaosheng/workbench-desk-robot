# HW1 official UR5e extraction evidence

Status: **EXECUTED** on 2026-08-12 in the repository development environment.

This evidence uses the ROS Jazzy `ur_description` package as the controlled,
non-generated source. The expanded URDF is a temporary generated artifact and
is not treated as the source of the limits.

## Controlled source references

- `ros-jazzy-ur-description 3.5.1-1noble.20260615.175716`
- `ros-jazzy-xacro 2.1.1-1noble.20260519.011123`
- `/opt/ros/jazzy/share/ur_description/urdf/ur.urdf.xacro`
  SHA-256: `d2eb6b60edf4c18b347c0612598f3c2b95fd0b189cf16fdb8c2f2ac119a0a82f`
- `/opt/ros/jazzy/share/ur_description/config/ur5e/joint_limits.yaml`
  SHA-256: `1e908454a0fb073761a0c675f708eb003ca7d5333a9e0863ef87fe40d9abb3c7`

The package's `joint_limits.yaml` cites the Universal Robots e-Series UR5e user
manual and Universal Robots' maximum-joint-torque article as its upstream
sources.

## Reproduction

```bash
/opt/ros/jazzy/bin/xacro \
  /opt/ros/jazzy/share/ur_description/urdf/ur.urdf.xacro \
  ur_type:=ur5e name:=ur5e \
  -o /tmp/workbench-hw1-official-ur5e.urdf

python3 libs/hardware/urdf_to_motor_config.py \
  /tmp/workbench-hw1-official-ur5e.urdf \
  --joint shoulder_pan_joint \
  --joint shoulder_lift_joint \
  --joint elbow_joint \
  --joint wrist_1_joint \
  --joint wrist_2_joint \
  --joint wrist_3_joint
```

The expanded URDF had SHA-256
`a21bf5fb70b3a1745bf2e4816e0f43654539737ba7f2585939ec773d159778d8`,
was 11,870 bytes, and contained exactly six revolute joints. Every selected
joint contained exactly one `<limit>` element. It contained no transmission,
so every reduction below remains explicitly unknown.

The extracted YAML below had SHA-256
`9a32af8b6504b4e242d2f3bf9458d5a87c96ae45fb55a14e459644fe6c5fd7d1`
and was 1,394 bytes.

## Extracted motor configuration

```yaml
motors:
  - name: "shoulder_pan_joint"
    joint_type: "revolute"
    max_torque_nm: 150.0
    max_velocity_rad_s: 3.141592653589793
    lower_limit_rad: -6.283185307179586
    upper_limit_rad: 6.283185307179586
    mechanical_reduction: null
  - name: "shoulder_lift_joint"
    joint_type: "revolute"
    max_torque_nm: 150.0
    max_velocity_rad_s: 3.141592653589793
    lower_limit_rad: -6.283185307179586
    upper_limit_rad: 6.283185307179586
    mechanical_reduction: null
  - name: "elbow_joint"
    joint_type: "revolute"
    max_torque_nm: 150.0
    max_velocity_rad_s: 3.141592653589793
    lower_limit_rad: -3.141592653589793
    upper_limit_rad: 3.141592653589793
    mechanical_reduction: null
  - name: "wrist_1_joint"
    joint_type: "revolute"
    max_torque_nm: 28.0
    max_velocity_rad_s: 3.141592653589793
    lower_limit_rad: -6.283185307179586
    upper_limit_rad: 6.283185307179586
    mechanical_reduction: null
  - name: "wrist_2_joint"
    joint_type: "revolute"
    max_torque_nm: 28.0
    max_velocity_rad_s: 3.141592653589793
    lower_limit_rad: -6.283185307179586
    upper_limit_rad: 6.283185307179586
    mechanical_reduction: null
  - name: "wrist_3_joint"
    joint_type: "revolute"
    max_torque_nm: 28.0
    max_velocity_rad_s: 3.141592653589793
    lower_limit_rad: -6.283185307179586
    upper_limit_rad: 6.283185307179586
    mechanical_reduction: null
```
