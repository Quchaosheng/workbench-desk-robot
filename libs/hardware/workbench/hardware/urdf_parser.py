import json
import math
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class UrdfMotorConfigError(ValueError):
    pass


@dataclass(frozen=True)
class MotorConfig:
    name: str
    joint_type: str
    max_torque_nm: float
    max_velocity_rad_s: float
    lower_limit_rad: float | None
    upper_limit_rad: float | None
    mechanical_reduction: float | None


def _required_float(value: str | None, field: str, joint_name: str, *, positive: bool) -> float:
    if value is None:
        raise UrdfMotorConfigError(f"joint {joint_name!r} is missing limit.{field}")
    try:
        parsed = float(value)
    except ValueError as exc:
        raise UrdfMotorConfigError(f"joint {joint_name!r} has invalid limit.{field}: {value!r}") from exc
    if not math.isfinite(parsed) or (positive and parsed <= 0):
        requirement = "finite positive" if positive else "finite"
        raise UrdfMotorConfigError(f"joint {joint_name!r} requires a {requirement} limit.{field}")
    return parsed


def _transmission_reductions(root: ElementTree.Element) -> dict[str, float]:
    reductions: dict[str, float] = {}
    transmission_joints: set[str] = set()
    for transmission in root.findall("./transmission"):
        joint_elements = transmission.findall("./joint")
        actuator_elements = transmission.findall("./actuator")
        transmission_name = transmission.get("name", "<unnamed>")
        if len(joint_elements) != 1 or len(actuator_elements) != 1:
            raise UrdfMotorConfigError(
                f"transmission {transmission_name!r} must declare exactly one joint and one actuator"
            )
        joint_name = joint_elements[0].get("name")
        if not joint_name or not joint_name.strip():
            raise UrdfMotorConfigError("a transmission joint is missing its name")
        if joint_name in transmission_joints:
            raise UrdfMotorConfigError(f"joint {joint_name!r} has multiple transmission declarations")
        transmission_joints.add(joint_name)

        actuator = actuator_elements[0]
        reduction_elements = actuator.findall("./mechanicalReduction")
        all_reduction_elements = transmission.findall(".//mechanicalReduction")
        if len(reduction_elements) != len(all_reduction_elements) or len(reduction_elements) > 1:
            raise UrdfMotorConfigError(
                f"transmission {transmission_name!r} must declare at most one actuator mechanicalReduction"
            )
        if not reduction_elements:
            continue

        reduction_text = reduction_elements[0].text
        try:
            reduction = float(reduction_text) if reduction_text is not None else float("nan")
        except ValueError as exc:
            raise UrdfMotorConfigError(
                f"transmission for joint {joint_name!r} has invalid mechanicalReduction"
            ) from exc
        if not math.isfinite(reduction) or reduction <= 0:
            raise UrdfMotorConfigError(
                f"transmission for joint {joint_name!r} requires a finite positive mechanicalReduction"
            )
        reductions[joint_name] = reduction
    return reductions


def parse_urdf_motor_config(
    urdf_xml: str,
    joint_names: Sequence[str] | None = None,
) -> tuple[MotorConfig, ...]:
    try:
        root = ElementTree.fromstring(urdf_xml)
    except ElementTree.ParseError as exc:
        raise UrdfMotorConfigError("input is not valid expanded URDF XML") from exc
    if root.tag != "robot":
        raise UrdfMotorConfigError("expanded URDF root element must be <robot>")

    joints: dict[str, ElementTree.Element] = {}
    declared_joint_names: set[str] = set()
    discovered_names: list[str] = []
    for joint in root.findall("./joint"):
        joint_name = joint.get("name")
        if not joint_name or not joint_name.strip():
            raise UrdfMotorConfigError("a joint declaration is missing its name")
        if joint_name in declared_joint_names:
            raise UrdfMotorConfigError(f"duplicate joint declaration {joint_name!r}")
        declared_joint_names.add(joint_name)

        joint_type = joint.get("type")
        if joint_type not in {"continuous", "revolute"}:
            continue
        joints[joint_name] = joint
        discovered_names.append(joint_name)

    if joint_names is None:
        selected_names = tuple(discovered_names)
    else:
        if isinstance(joint_names, str):
            raise UrdfMotorConfigError("joint_names must be a sequence, not a string")
        selected_names = tuple(joint_names)
        if not selected_names or any(
            not isinstance(name, str) or not name or not name.strip() for name in selected_names
        ):
            raise UrdfMotorConfigError("joint_names requires non-empty joint names")
        if len(selected_names) != len(set(selected_names)):
            raise UrdfMotorConfigError("joint_names must not contain duplicates")

    if not selected_names:
        raise UrdfMotorConfigError("expanded URDF contains no actuated joints")

    reductions = _transmission_reductions(root)
    configs: list[MotorConfig] = []
    for joint_name in selected_names:
        joint = joints.get(joint_name)
        if joint is None:
            raise UrdfMotorConfigError(f"requested actuated joint {joint_name!r} is not present")
        joint_type = joint.get("type")
        limit_elements = joint.findall("./limit")
        if len(limit_elements) != 1:
            raise UrdfMotorConfigError(f"joint {joint_name!r} must declare exactly one <limit> element")
        limit = limit_elements[0]
        lower_limit: float | None = None
        upper_limit: float | None = None
        if joint_type == "revolute":
            lower_limit = _required_float(limit.get("lower"), "lower", joint_name, positive=False)
            upper_limit = _required_float(limit.get("upper"), "upper", joint_name, positive=False)
            if lower_limit >= upper_limit:
                raise UrdfMotorConfigError(f"joint {joint_name!r} requires lower limit below upper limit")
        configs.append(
            MotorConfig(
                name=joint_name,
                joint_type=joint_type,
                max_torque_nm=_required_float(limit.get("effort"), "effort", joint_name, positive=True),
                max_velocity_rad_s=_required_float(limit.get("velocity"), "velocity", joint_name, positive=True),
                lower_limit_rad=lower_limit,
                upper_limit_rad=upper_limit,
                mechanical_reduction=reductions.get(joint_name),
            )
        )
    return tuple(configs)


def load_urdf_motor_config(
    urdf_path: Path,
    joint_names: Sequence[str] | None = None,
) -> tuple[MotorConfig, ...]:
    try:
        urdf_xml = urdf_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise UrdfMotorConfigError(f"could not read expanded URDF: {urdf_path}") from exc
    return parse_urdf_motor_config(urdf_xml, joint_names)


def dump_motor_config_yaml(configs: Sequence[MotorConfig]) -> str:
    if not configs:
        raise UrdfMotorConfigError("at least one motor config is required")
    lines = ["motors:"]
    for config in configs:
        lines.extend(
            [
                f"  - name: {json.dumps(config.name, ensure_ascii=False)}",
                f"    joint_type: {json.dumps(config.joint_type)}",
                f"    max_torque_nm: {config.max_torque_nm!r}",
                f"    max_velocity_rad_s: {config.max_velocity_rad_s!r}",
                f"    lower_limit_rad: {'null' if config.lower_limit_rad is None else repr(config.lower_limit_rad)}",
                f"    upper_limit_rad: {'null' if config.upper_limit_rad is None else repr(config.upper_limit_rad)}",
                "    mechanical_reduction: "
                + ("null" if config.mechanical_reduction is None else repr(config.mechanical_reduction)),
            ]
        )
    return "\n".join(lines) + "\n"
