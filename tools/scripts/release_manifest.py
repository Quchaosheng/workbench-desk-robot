#!/usr/bin/env python3
"""Write release provenance tying the tested image and SBOM to a commit."""

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_metadata(image: str, registry_image: str | None) -> dict:
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)[0]
    repo_digests = payload.get("RepoDigests", [])
    return {
        "image": image,
        "image_id": payload.get("Id"),
        "repo_digests": repo_digests,
        "registry_digest": next(
            (
                value.rsplit("@", 1)[1]
                for value in repo_digests
                if ("@" in value and registry_image and value.split("@", 1)[0].lower() == registry_image.lower())
            ),
            None,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a release provenance manifest")
    parser.add_argument("--image", required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--registry-image")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.sbom.is_file():
        raise RuntimeError(f"SBOM does not exist: {args.sbom}")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    image = image_metadata(args.image, args.registry_image)
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "version": args.version,
        "source_commit": commit,
        "registry_image": args.registry_image,
        "image": image,
        "sbom": {"format": "spdx-json", "path": str(args.sbom), "sha256": sha256(args.sbom)},
        "environment": {"platform": platform.platform(), "python": platform.python_version()},
        "release_eligible": bool(image["registry_digest"] and args.version.startswith("v")),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
