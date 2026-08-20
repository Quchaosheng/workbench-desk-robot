import argparse
import fnmatch
import json
import os
import re
import shlex
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from _paths import ROOT
from jsonschema import Draft202012Validator

SCHEMA_PATH = ROOT / "tools/schemas/task-packet-v1.schema.json"
PACKET_DIR = ROOT / "docs/task_packets"
PATH_FIELDS = ("allowed_paths", "read_only_paths", "forbidden")
COMMAND_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
COMMAND_PREFIX = re.compile(
    r"^(?:[A-Z_][A-Z0-9_]*=\S+\s+)*(?:sudo\s+)?(?:make|python3?|docker|git|insmod|source|uv|colcon|xacro|ros2|<[^>]+>/bin/python)(?:\s|$)"
)


class TaskPacketError(RuntimeError):
    """A Task Packet is malformed or exceeds a safe repository boundary."""


def _format_json_path(parts: list[Any]) -> str:
    return ".".join(str(part) for part in parts) or "<packet>"


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskPacketError(f"cannot read JSON: {exc}") from exc


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _validate_schema(payload: Any) -> None:
    schema = _load_json(SCHEMA_PATH)
    errors = sorted(Draft202012Validator(schema).iter_errors(payload), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(f"{_format_json_path(list(error.absolute_path))}: {error.message}" for error in errors)
        raise TaskPacketError(f"schema validation failed: {details}")


def _normalize_repo_path(value: str, *, field: str) -> str:
    if value != value.strip():
        raise TaskPacketError(f"{field}: path has leading or trailing whitespace: {value!r}")
    if "\\" in value:
        raise TaskPacketError(f"{field}: use repository-relative '/' separators: {value!r}")
    windows_path = PureWindowsPath(value)
    path = PurePosixPath(value)
    if windows_path.drive or windows_path.root or path.is_absolute():
        raise TaskPacketError(f"{field}: absolute paths and drive prefixes are forbidden: {value!r}")
    if not path.parts or path.as_posix() != value or any(part in {"", ".", ".."} for part in path.parts):
        raise TaskPacketError(f"{field}: path must be normalized and cannot contain '.' or '..': {value!r}")
    if any("**" in part and part != "**" for part in path.parts):
        raise TaskPacketError(f"{field}: recursive wildcard must be a complete path segment: {value!r}")

    current = ROOT
    has_wildcard = False
    for part in path.parts:
        if any(character in part for character in "*?["):
            has_wildcard = True
            break
        candidate = current / part
        if not candidate.exists() and not _is_link(candidate):
            break
        if _is_link(candidate):
            raise TaskPacketError(f"{field}: symbolic links are not authorization boundaries: {value!r}")
        current = candidate
    try:
        current.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise TaskPacketError(f"{field}: path escapes the repository: {value!r}") from exc
    if has_wildcard and current.is_dir():
        for directory, directories, files in os.walk(current, followlinks=False):
            for name in (*directories, *files):
                if _is_link(Path(directory) / name):
                    raise TaskPacketError(f"{field}: wildcard boundary contains a link: {value!r}")
    return path.as_posix()


def _patterns_overlap(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    for left_part, right_part in zip(left_parts, right_parts, strict=False):
        if left_part == "**" or right_part == "**":
            return True
        left_wild = any(character in left_part for character in "*?[")
        right_wild = any(character in right_part for character in "*?[")
        if not left_wild and not right_wild and left_part != right_part:
            return False
        if left_wild and not right_wild and not fnmatch.fnmatchcase(right_part, left_part):
            return False
        if right_wild and not left_wild and not fnmatch.fnmatchcase(left_part, right_part):
            return False
    common = min(len(left_parts), len(right_parts))
    return all(part == "**" for part in left_parts[common:]) or all(part == "**" for part in right_parts[common:])


def _validate_boundaries(payload: dict[str, Any]) -> None:
    normalized: dict[str, list[str]] = {}
    for field in PATH_FIELDS:
        normalized[field] = [_normalize_repo_path(value, field=field) for value in payload[field]]

    boundary_pairs = (
        ("allowed_paths", "read_only_paths"),
        ("allowed_paths", "forbidden"),
        ("read_only_paths", "forbidden"),
    )
    for left_field, right_field in boundary_pairs:
        for left in normalized[left_field]:
            for right in normalized[right_field]:
                if _patterns_overlap(left, right):
                    raise TaskPacketError(
                        f"boundary overlap: {left_field} entry {left!r} conflicts with {right_field} entry {right!r}"
                    )


def _validate_commands(commands: list[str]) -> None:
    for index, command in enumerate(commands):
        if command != command.strip():
            raise TaskPacketError(f"commands.{index}: command evidence instruction has surrounding whitespace")
        if "\n" in command or "\r" in command or COMMAND_CONTROL_CHARACTERS.search(command):
            raise TaskPacketError(
                f"commands.{index}: command evidence instruction must be one printable line; it is never executed"
            )
        try:
            shlex.split(command, posix=True)
        except ValueError as exc:
            raise TaskPacketError(f"commands.{index}: ambiguous command evidence instruction: {exc}") from exc
        if not COMMAND_PREFIX.match(command):
            raise TaskPacketError(
                f"commands.{index}: command evidence instruction must start with an approved repository tool"
            )


def validate_packet(packet_path: Path) -> None:
    try:
        packet_path.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise TaskPacketError(f"packet file is outside the repository: {packet_path}") from exc
    if packet_path.is_symlink():
        raise TaskPacketError(f"packet file cannot be a symbolic link: {packet_path}")
    payload = _load_json(packet_path)
    _validate_schema(payload)
    _validate_boundaries(payload)
    _validate_commands(payload["commands"])


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Task Packets without executing their commands.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("packet", nargs="?", type=Path, help="one Task Packet JSON file")
    selection.add_argument("--all", action="store_true", help="validate every committed packet in docs/task_packets")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.all:
        packet_paths = sorted(PACKET_DIR.glob("*.json"))
        if not packet_paths:
            raise TaskPacketError(f"no Task Packets found in {PACKET_DIR}")
    else:
        packet_paths = [args.packet or PACKET_DIR / "example-001-world-reducer.json"]

    failures: list[str] = []
    for packet_path in packet_paths:
        try:
            validate_packet(packet_path)
        except TaskPacketError as exc:
            failures.append(f"{packet_path}: {exc}")
        else:
            print(f"Task Packet validation passed: {packet_path}")
    if failures:
        raise TaskPacketError("Task Packet validation failed:\n" + "\n".join(failures))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TaskPacketError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None
