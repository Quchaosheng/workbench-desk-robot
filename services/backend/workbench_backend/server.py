import argparse
import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, urlparse

from .logging import StructuredLogger
from .read_model import (
    DashboardReadModel,
    ReadModelError,
    ReadModelResponseTooLarge,
    RemoteDashboardReadModel,
)

SOURCE_ROOT = Path(__file__).resolve().parents[3]
ROOT = Path.cwd() if (Path.cwd() / "apps" / "dashboard").is_dir() else SOURCE_ROOT
DEFAULT_STATIC_DIR = ROOT / "apps" / "dashboard"
DEFAULT_DATA_DIR = DEFAULT_STATIC_DIR / "data"
OPENAPI_RESOURCE = resources.files("workbench_backend").joinpath("api-openapi-v1.json")
API_VERSION = "1"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class DashboardHandler(BaseHTTPRequestHandler):
    read_model = DashboardReadModel(DEFAULT_DATA_DIR)
    static_dir = DEFAULT_STATIC_DIR
    logger = StructuredLogger("workbench-backend")
    data_source = "dashboard-fixtures"
    server_version = "WorkbenchBackend/0.1"

    def log_message(self, format: str, *args) -> None:
        self.logger.emit("http_access", format % args, details={"client": self.client_address[0]})

    def _send_json(
        self, payload: object, status: HTTPStatus = HTTPStatus.OK, *, api_version: str | None = None
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        if len(body) > MAX_RESPONSE_BYTES:
            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            body = json.dumps(
                {"error": "response_too_large", "message": "The requested read model exceeds the response limit."}
            ).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if api_version:
            self.send_header("X-API-Version", api_version)
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
        )

    def _send_file(self, relative_path: str) -> None:
        try:
            requested = (self.static_dir / relative_path).resolve()
            static_root = self.static_dir.resolve()
        except (OSError, RuntimeError):
            self._send_json({"error": "invalid_path"}, HTTPStatus.BAD_REQUEST)
            return
        if requested != static_root and static_root not in requested.parents:
            self._send_json({"error": "invalid_path"}, HTTPStatus.BAD_REQUEST)
            return
        if not requested.is_file():
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            stat = requested.stat()
        except OSError:
            self._send_json({"error": "asset_unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
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
            self._send_security_headers()
            self.end_headers()
            return
        try:
            body = requested.read_bytes()
        except OSError:
            self._send_json({"error": "asset_unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE)
            return
        content_type, _ = mimetypes.guess_type(requested.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", cache_control)
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            self._do_get()
        except ReadModelResponseTooLarge:
            self._send_json(
                {"error": "response_too_large", "message": "The requested read model exceeds the response limit."},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
        except ReadModelError as exc:
            self.logger.emit("read_model_error", str(exc), level="ERROR")
            self._send_json(
                {"error": "invalid_event_source", "message": "The event source is unavailable or malformed."},
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

    def _do_get(self) -> None:
        route = urlparse(self.path).path
        api_version = API_VERSION if route.startswith("/api/v1/") else None
        if route == "/healthz":
            self._send_json({"status": "ok", "service": "workbench-backend", "version": "0.1.0"})
            return
        if route == "/readyz":
            ready = self.read_model.ready()
            self._send_json(
                {"status": "ready" if ready else "not_ready", "data_source": self.data_source},
                HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        if route in {"/api/openapi.json", "/api/v1/openapi.json"}:
            try:
                contract = json.loads(OPENAPI_RESOURCE.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                self._send_json(
                    {"error": "contract_unavailable"}, HTTPStatus.SERVICE_UNAVAILABLE, api_version=api_version
                )
                return
            self._send_json(contract, api_version=api_version)
            return
        if route in {"/api/runs", "/api/v1/runs"}:
            self._send_json({"runs": self.read_model.list_runs(), "read_only": True}, api_version=api_version)
            return
        if route in {"/api/expression-states", "/api/v1/expression-states"}:
            self._send_json(self.read_model.expression_contract(), api_version=api_version)
            return
        run_prefix = "/api/v1/runs/" if route.startswith("/api/v1/runs/") else "/api/runs/"
        if route.startswith(run_prefix):
            suffix = unquote(route.removeprefix(run_prefix))
            include_events = suffix.endswith("/events")
            run_id = suffix.removesuffix("/events") if include_events else suffix
            if not RUN_ID_PATTERN.fullmatch(run_id):
                self._send_json({"error": "invalid_run_id"}, HTTPStatus.BAD_REQUEST, api_version=api_version)
                return
            try:
                events = self.read_model.list_events(run_id)
            except KeyError:
                self._send_json(
                    {"error": "run_not_found", "run_id": run_id}, HTTPStatus.NOT_FOUND, api_version=api_version
                )
                return
            payload = {"run": self.read_model.summarize(events)}
            if include_events:
                payload["events"] = events
            self._send_json(payload, api_version=api_version)
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
    event_source_url: str | None = None,
) -> ThreadingHTTPServer:
    configured_read_model = (
        RemoteDashboardReadModel(event_source_url) if event_source_url else DashboardReadModel(data_dir)
    )
    configured_static_dir = Path(static_dir)

    class ConfiguredHandler(DashboardHandler):
        read_model = configured_read_model
        static_dir = configured_static_dir
        data_source = configured_read_model.data_source if event_source_url else "dashboard-fixtures"

    return ThreadingHTTPServer((host, port), ConfiguredHandler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the read-only Workbench-1 dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--event-source-url", default=os.environ.get("WORKBENCH_EVENT_SOURCE_URL"))
    args = parser.parse_args()
    server = create_server(args.host, args.port, data_dir=args.data_dir, event_source_url=args.event_source_url)
    DashboardHandler.logger.emit(
        "service_started",
        f"dashboard listening on http://{args.host}:{args.port}",
        details={"offline": True, "read_only": True, "data_source": "remote" if args.event_source_url else "local"},
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
