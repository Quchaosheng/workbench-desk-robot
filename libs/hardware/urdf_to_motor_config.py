import argparse
import sys
from pathlib import Path

HARDWARE_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(HARDWARE_ROOT))

from workbench.hardware.urdf_parser import (
    UrdfMotorConfigError,
    dump_motor_config_yaml,
    load_urdf_motor_config,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract deterministic motor limits from an expanded URDF")
    parser.add_argument("urdf", type=Path, help="path to expanded URDF XML")
    parser.add_argument("--joint", action="append", dest="joints", help="joint to include, repeat in desired order")
    parser.add_argument("--output", type=Path, help="write YAML to this path instead of stdout")
    args = parser.parse_args()

    try:
        configs = load_urdf_motor_config(args.urdf, args.joints)
        serialized = dump_motor_config_yaml(configs)
        if args.output is None:
            sys.stdout.write(serialized)
        else:
            args.output.write_text(serialized, encoding="utf-8")
    except (OSError, UrdfMotorConfigError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
