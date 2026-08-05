# mobile_base

Mobile base integration. The verifier contract generalises to navigation goals,
so adding a mobile base doesn't require changing the verification layer.

Planned for v0.4. The verifier will check "robot reached goal pose within
tolerance, with confirmed localisation confidence."

Subdirectories (when implemented):
- `description/`   base URDF / TF
- `control/`       ros2_control hardware interface or Nav2 integration
- `bringup/`       launch files
