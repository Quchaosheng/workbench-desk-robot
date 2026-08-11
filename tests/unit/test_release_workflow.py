from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release-image.yml"


def _step_block(workflow: str, marker: str) -> str:
    start = workflow.index(marker)
    next_step = workflow.find("\n      - ", start + len(marker))
    return workflow[start:] if next_step == -1 else workflow[start:next_step]


def test_sbom_generation_keeps_release_workflow_least_privileged() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    permissions = workflow.split("jobs:", maxsplit=1)[0]
    assert "contents: read" in permissions
    assert "contents: write" not in permissions

    sbom_step = _step_block(workflow, "uses: anchore/sbom-action@")
    assert "upload-artifact: false" in sbom_step
    assert "upload-release-assets: false" in sbom_step

    artifact_step = _step_block(workflow, "uses: actions/upload-artifact@")
    assert "name: workbench-1-sbom" in artifact_step
    assert "path: workbench-1.spdx.json" in artifact_step
