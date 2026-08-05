# arm_drivers

Vendor SDK wrappers → `ros2_control` hardware interface.

One subdirectory per arm model, e.g. `franka/`, `ur/`, `custom/`.

**What to implement**: a `hardware_interface::SystemInterface` subclass that
talks to the real arm SDK and emits the same `action_result` as the Gazebo
simulation. joint limits, safety limits and bring-up sequence go here too.

Cross-compilation notes (for ARM boards): `docs/hardware/cross_compile.md`
