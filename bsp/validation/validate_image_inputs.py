"""Validate fail-closed Jetson BSP image build inputs."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "bsp/image/build-inputs.yaml"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
UNRESOLVED_PREFIXES = ("TBD_", "NOT_BUILT")


def _unresolved(value: object) -> bool:
    return not isinstance(value, str) or not value or value.startswith(UNRESOLVED_PREFIXES)


def _repository_file(root: Path, value: object) -> Path | None:
    if _unresolved(value):
        return None
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def validate_image_inputs(manifest: object, root: Path = ROOT) -> list[str]:
    if not isinstance(manifest, dict):
        return ["image build manifest must be a mapping"]
    errors: list[str] = []
    inputs = manifest.get("inputs")
    outputs = manifest.get("outputs")
    rules = manifest.get("rules")
    if not isinstance(inputs, dict) or set(inputs) != {
        "jetpack",
        "l4t",
        "kernel",
        "device_tree",
        "rootfs",
        "recovery",
        "toolchain",
    }:
        return ["image build manifest requires the exact controlled input groups"]
    if not isinstance(outputs, dict) or set(outputs) != {
        "boot_image_sha256",
        "rootfs_image_sha256",
        "recovery_image_sha256",
    }:
        errors.append("image build manifest requires the exact controlled outputs")
    if not isinstance(rules, dict) or not all(value is True for value in rules.values()):
        errors.append("image build manifest safety rules must all be true")

    unresolved = False
    for group_name in ("jetpack", "l4t"):
        group = inputs.get(group_name, {})
        if not isinstance(group, dict):
            errors.append(f"{group_name} input must be a mapping")
            continue
        for field in ("version", "source", "sha256"):
            unresolved |= _unresolved(group.get(field))
        source = group.get("source")
        if not _unresolved(source) and not source.startswith("https://"):
            errors.append(f"{group_name} source must use HTTPS")
        digest = group.get("sha256")
        if not _unresolved(digest) and not SHA256.fullmatch(digest):
            errors.append(f"{group_name} sha256 must be lowercase hexadecimal")

    kernel = inputs.get("kernel", {})
    device_tree = inputs.get("device_tree", {})
    rootfs = inputs.get("rootfs", {})
    recovery = inputs.get("recovery", {})
    toolchain = inputs.get("toolchain", {})
    for group_name, group in (
        ("kernel", kernel),
        ("device_tree", device_tree),
        ("rootfs", rootfs),
        ("recovery", recovery),
        ("toolchain", toolchain),
    ):
        if not isinstance(group, dict):
            errors.append(f"{group_name} input must be a mapping")
            continue
        unresolved |= any(_unresolved(value) for value in group.values())

    for source_name, source in (
        ("kernel", kernel.get("source") if isinstance(kernel, dict) else None),
        ("rootfs", rootfs.get("base_source") if isinstance(rootfs, dict) else None),
    ):
        if not _unresolved(source) and not source.startswith("https://"):
            errors.append(f"{source_name} source must use HTTPS")

    digest_fields = (
        kernel.get("sha256"),
        kernel.get("config_sha256"),
        device_tree.get("source_sha256"),
        device_tree.get("dtb_sha256"),
        rootfs.get("base_sha256"),
        rootfs.get("package_lock_sha256"),
        rootfs.get("services_sha256"),
        recovery.get("image_sha256"),
    )
    for digest in digest_fields:
        if not _unresolved(digest) and not SHA256.fullmatch(digest):
            errors.append("image input sha256 values must be lowercase hexadecimal")
    container_digest = toolchain.get("container_digest") if isinstance(toolchain, dict) else None
    if not _unresolved(container_digest) and not OCI_DIGEST.fullmatch(container_digest):
        errors.append("toolchain container_digest must be an OCI sha256 digest")

    for field_name, value in (
        ("kernel config", kernel.get("config")),
        ("rootfs services", rootfs.get("services")),
        ("rootfs package lock", rootfs.get("package_lock")),
        ("device-tree source", device_tree.get("source")),
        ("rollback procedure", recovery.get("rollback_procedure")),
    ):
        if not _unresolved(value) and _repository_file(root, value) is None:
            errors.append(f"{field_name} must reference a repository file")

    built_outputs = isinstance(outputs, dict) and all(SHA256.fullmatch(value or "") for value in outputs.values())
    build_ready = manifest.get("build_ready") is True
    if build_ready and unresolved:
        errors.append("unresolved image inputs must block build_ready")
    if build_ready and errors:
        errors.append("invalid image inputs must block build_ready")
    if built_outputs and not build_ready:
        errors.append("built output hashes require build_ready inputs")
    expected_status = "inputs_locked" if build_ready else "inputs_unresolved"
    if manifest.get("status") != expected_status:
        errors.append(f"image build status must be {expected_status}")
    return errors


def validate() -> list[str]:
    return validate_image_inputs(yaml.safe_load(MANIFEST.read_text(encoding="utf-8")))


if __name__ == "__main__":
    failures = validate()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        raise SystemExit(1)
    print("BSP image input validation passed")
