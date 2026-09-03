# Third-party review register

| Dependency or asset | Version / digest | License checked | Owner | Exit path |
|---|---|---:|---|---|
| ROS 2 Jazzy | pending | pending | Linux | pinned container |
| Gazebo Harmonic | pending | pending | Linux + Simulation | single simulator baseline |
| MoveIt 2 | `ros-jazzy-moveit` 2.12.4 | Apache-2.0 (checked 2026-08-08) | Motion | fixed validated trajectory |
| UR description (arm URDF/xacro) | `ros-jazzy-ur-description` | **BSD-3-Clause (code) — OK** | Motion | primitive-only description |
| UR meshes (visual/collision STL/DAE) | shipped in `ur_description/meshes` | **PROPRIETARY: "Universal Robots A/S' Terms and Conditions for Use of Graphical Documentation" — NOT open-source; distribution unverified** | Motion + Legal | drop visual meshes / use primitive collision geometry, or swap to Panda (config-only, see ADR-0004) |
| Robotiq 2F-85 gripper (description) | `ros-jazzy-robotiq-description` | BSD (checked 2026-08-08) | Motion | primitive-only gripper description |
| TRAC-IK kinematics plugin | `ros-jazzy-trac-ik-kinematics-plugin` | BSD (upstream trac_ik) — reconfirm at pin | Motion | fall back to KDL (ships with MoveIt) |
| OpenCV / AprilTag | pending | pending | Perception Owner | known-object baseline |
| Ollama runtime image | `sha256:b88c73ace3e115f8ec53dc8761ae1c0aabfa675406e3681786b98757ce050f42` | Apache-2.0 (verify at release) | Runtime + Integration | localhost-only endpoint and internal network |
| Qwen2.5 0.5B weights | `qwen2.5:0.5b` (397 MB pulled locally) | pending model-card review | Runtime + Product | remove model profile and use template runner |
| Lucide icons | 0.468.0 | ISC (`apps/dashboard/vendor/LUCIDE-LICENSE.txt`) | Interaction | replace with text labels |
| MonoSim | invited access; version pending | use invitation recorded; license and redistribution terms pending | Simulation + Integration | keep behind an external adapter; remove from release if terms do not permit distribution |
| RLSOK | invited access; version pending | use invitation recorded; license and redistribution terms pending | Simulation + Integration | keep behind an external adapter; remove from release if terms do not permit distribution |

Model weights, CAD, mesh, images, audio and code are reviewed separately.

MonoSim and RLSOK are recorded as invited third-party integrations, not as
co-created project assets. Do not vendor their source, models or datasets, or
claim joint development, until the maintainers confirm the applicable license,
publication and redistribution terms in writing.
