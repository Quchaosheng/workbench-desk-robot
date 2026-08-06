import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .logging import StructuredLogger
from .read_model import DashboardReadModel

SOURCE_ROOT = Path(__file__).resolve().parents[3]
ROOT = Path.cwd() if (Path.cwd() / "apps" / "dashboard").is_dir() else SOURCE_ROOT
DEFAULT_STATIC_DIR = ROOT / "apps" / "dashboard"
DEFAULT_DATA_DIR = DEFAULT_STATIC_DIR / "data"


class DashboardHandler(BaseHTTPRequestHandler):
    read_model = DashboardReadModel(DEFAULT_DATA_DIR)
    static_dir = DEFAULT_STATIC_DIR
    logger = StructuredLogger("workbench-backend")
    server_version = "WorkbenchBackend/0.1"

    def log_message(self, format: str, *args) -> None:
        self.logger.emit("http_access", format % args, details={"client": self.client_address[0]})

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, relative_path: str) -> None:
        requested = (self.static_dir / relative_path).resolve()
        static_root = self.static_dir.resolve()
        if requested != static_root and static_root not in requested.parents:
            self._send_json({"error": "invalid_path"}, HTTPStatus.BAD_REQUEST)
            return
        if not requested.is_file():
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        stat = requested.stat()
        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
        cache_control = (
            "public, max-age=31536000, immutable"
            if "vendor" in requested.relative_to(static_root).parts
            else "no-cache"
        )
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache_control)
            self.end_headers()
            return
        body = requested.read_bytes()
        content_type, _ = mimetypes.guess_type(requested.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/healthz":
            self._send_json({"status": "ok", "service": "workbench-backend", "version": "0.1.0"})
            return
        if route == "/readyz":
            ready = self.read_model.ready()
            self._send_json(
                {"status": "ready" if ready else "not_ready", "data_source": "dashboard-fixtures"},
                HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if route == "/api/runs":
            self._send_json({"runs": self.read_model.list_runs(), "read_only": True})
            return
        if route == "/api/expression-states":
            self._send_json(self.read_model.expression_contract())
            return
        if route.startswith("/api/runs/"):
            suffix = unquote(route.removeprefix("/api/runs/"))
            include_events = suffix.endswith("/events")
            run_id = suffix.removesuffix("/events") if include_events else suffix
            try:
                events = self.read_model.list_events(run_id)
            except KeyError:
                self._send_json({"error": "run_not_found", "run_id": run_id}, HTTPStatus.NOT_FOUND)
                return
            payload = {"run": self.read_model.summarize(events)}
            if include_events:
                payload["events"] = events
            self._send_json(payload)
            return
        static_path = "index.html" if route in {"", "/"} else route.lstrip("/")
        self._send_file(static_path)

    def _reject_write(self) -> None:
        self._send_json(
            {"error": "read_only", "message": "This service exposes no robot or ROS control operations."},
            HTTPStatus.METHOD_NOT_ALLOWED,
        )

    do_POST = _reject_write
    do_PUT = _reject_write
    do_PATCH = _reject_write
    do_DELETE = _reject_write


def create_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    data_dir: str | Path = DEFAULT_DATA_DIR,
    static_dir: str | Path = DEFAULT_STATIC_DIR,
) -> ThreadingHTTPServer:
    configured_read_model = DashboardReadModel(data_dir)
    configured_static_dir = Path(static_dir)

    class ConfiguredHandler(DashboardHandler):
        read_model = configured_read_model
        static_dir = configured_static_dir

    return ThreadingHTTPServer((host, port), ConfiguredHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the read-only Workbench-1 dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args()
    server = create_server(args.host, args.port, data_dir=args.data_dir)
    DashboardHandler.logger.emit(
        "service_started",
        f"dashboard listening on http://{args.host}:{args.port}",
        details={"offline": True, "read_only": True},
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
