import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from integrations.omnilink import OmniLinkClient, OmniLinkError, OmniLinkResponseTooLarge, RunSummaryExporter


class Handler(BaseHTTPRequestHandler):
    response: ClassVar[dict[str, Any]] = {"results": [{"link": {"title": "Guide"}}]}
    requests: ClassVar[list[tuple[str, dict[str, Any]]]] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.__class__.requests.append((self.path, json.loads(self.rfile.read(length))))
        body = json.dumps(self.response).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def server():
    Handler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_search_and_export_send_only_safe_projection(server):
    client = OmniLinkClient(server)
    assert client.search("robot safety")["results"]
    Handler.response = {"link": {"id": "x"}}
    RunSummaryExporter(client, server).export(
        {"run_id": "run-1", "status": "confirmed", "goal": "secret?", "event_count": 3, "evidence_refs": ["sha256:abc"]}
    )
    assert Handler.requests[0][0] == "/api/ai/search/hybrid"
    path, payload = Handler.requests[1]
    assert path == "/api/links"
    assert payload["autoAiExtract"] is False
    assert "secret?" in payload["notes"]
    assert "events" not in payload["notes"]


def test_invalid_response_and_size_fail_closed(server):
    Handler.response = {"unexpected": True}
    with pytest.raises(OmniLinkError):
        OmniLinkClient(server).search("x")
    Handler.response = {"results": ["x" * 1000]}
    with pytest.raises(OmniLinkResponseTooLarge):
        OmniLinkClient(server, max_response_bytes=50).search("x")
