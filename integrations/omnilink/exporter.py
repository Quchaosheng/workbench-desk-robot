"""One-way export of safe run summaries into OmniLink bookmarks."""

from __future__ import annotations

from typing import Any

from .client import OmniLinkClient


class RunSummaryExporter:
    def __init__(self, client: OmniLinkClient, backend_base_url: str) -> None:
        self.client = client
        self.backend_base_url = backend_base_url.rstrip("/")

    def export(self, summary: dict[str, Any]) -> dict[str, Any]:
        """Export only the public projection; raw events and payloads stay local."""
        run_id = summary.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("summary.run_id must be a non-empty string")
        status = summary.get("status", "unknown")
        title = f"Workbench run {run_id} ({status})"
        notes = (
            f"Run ID: {run_id}\nStatus: {status}\n"
            f"Goal: {str(summary.get('goal', ''))[:500]}\n"
            f"Event count: {summary.get('event_count', 0)}\n"
            f"Evidence refs: {', '.join(str(x) for x in summary.get('evidence_refs', [])[:20])}"
        )
        return self.client.save_bookmark(
            f"{self.backend_base_url}/api/v1/runs/{run_id}",
            title=title,
            notes=notes,
            tags=["workbench", "run-summary", str(status)],
        )
