import http.client
import ipaddress
import math
import socket
import time
import urllib.parse
from dataclasses import dataclass

MAX_REMOTE_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_REMOTE_TIMEOUT_SECONDS = 2.0
_READ_CHUNK_BYTES = 64 * 1024


class RemoteHttpError(RuntimeError):
    """Raised when a remote event-source request cannot be trusted."""


class RemoteHttpConfigurationError(RemoteHttpError, ValueError):
    """Raised when a remote event-source URL or policy is invalid."""


class RemoteHttpResponseTooLarge(RemoteHttpError):
    """Raised when a remote response exceeds the configured byte limit."""


@dataclass(frozen=True)
class RemoteHttpResponse:
    status: int
    body: bytes


@dataclass(frozen=True)
class ResolvedEndpoint:
    family: int
    sockaddr: tuple
    address: str
    effective_address: str


def _effective_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _parse_allowlist(
    value: str | None,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    if value is None:
        return ()
    if not isinstance(value, str):
        raise RemoteHttpConfigurationError("remote event source allow-list must be a string")
    if not value.strip():
        return ()
    tokens = value.split(",")
    if any(not token.strip() for token in tokens):
        raise RemoteHttpConfigurationError("remote event source allow-list contains an empty entry")
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for token in tokens:
        try:
            network = ipaddress.ip_network(token.strip(), strict=False)
        except ValueError as exc:
            raise RemoteHttpConfigurationError("remote event source allow-list is malformed") from exc
        if network not in networks:
            networks.append(network)
    return tuple(networks)


def _parse_origin(base_url: str) -> tuple[str, int, str, str]:
    if not isinstance(base_url, str) or not base_url or any(ord(character) < 32 for character in base_url):
        raise RemoteHttpConfigurationError("remote event source URL is invalid")
    try:
        parsed = urllib.parse.urlsplit(base_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise RemoteHttpConfigurationError("remote event source URL is invalid") from exc
    if parsed.scheme.lower() != "http":
        raise RemoteHttpConfigurationError("remote event source URL must use http")
    if not parsed.netloc or not hostname:
        raise RemoteHttpConfigurationError("remote event source URL must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise RemoteHttpConfigurationError("remote event source URL must not contain credentials")
    if "?" in base_url or "#" in base_url:
        raise RemoteHttpConfigurationError("remote event source URL must not contain query or fragment data")
    if parsed.path not in {"", "/"}:
        raise RemoteHttpConfigurationError("remote event source URL must be an origin without a path")
    if parsed.netloc.endswith(":"):
        raise RemoteHttpConfigurationError("remote event source URL contains an invalid port")
    if "%" in hostname:
        raise RemoteHttpConfigurationError("remote event source URL contains an unsupported scoped address")
    if not hostname.isascii():
        raise RemoteHttpConfigurationError("remote event source URL hostname must contain only ASCII characters")
    port = 80 if port is None else port
    if not 1 <= port <= 65535:
        raise RemoteHttpConfigurationError("remote event source URL contains an invalid port")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        normalized_host = hostname.lower()
        host_header = normalized_host
    else:
        normalized_host = literal.compressed
        host_header = f"[{normalized_host}]" if isinstance(literal, ipaddress.IPv6Address) else normalized_host
    if port != 80:
        host_header = f"{host_header}:{port}"
    return normalized_host, port, host_header, f"http://{host_header}"


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, endpoint: ResolvedEndpoint, timeout: float) -> None:
        super().__init__(host, port=port, timeout=timeout)
        self._endpoint = endpoint

    def connect(self) -> None:
        sock = socket.socket(self._endpoint.family, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self._endpoint.sockaddr)
        except BaseException:
            sock.close()
            raise
        self.sock = sock


class RemoteHttpClient:
    def __init__(self, base_url: str, *, allowlist: str | None = None, timeout_s: float = 1.0) -> None:
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(timeout_s)
            or not 0 < timeout_s <= MAX_REMOTE_TIMEOUT_SECONDS
        ):
            raise RemoteHttpConfigurationError(
                f"remote event source timeout must be finite and between 0 and {MAX_REMOTE_TIMEOUT_SECONDS} seconds"
            )
        self.host, self.port, self.host_header, self.base_url = _parse_origin(base_url)
        self.timeout_s = float(timeout_s)
        self.allowlist = _parse_allowlist(allowlist)
        try:
            literal = ipaddress.ip_address(self.host)
        except ValueError:
            self._literal_address = None
        else:
            self._literal_address = literal
            self._validate_address(literal)

    def _validate_address(self, address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        effective = _effective_address(address)
        if effective.is_loopback:
            return
        is_deprecated_site_local = isinstance(effective, ipaddress.IPv6Address) and effective.is_site_local
        if (
            effective.is_unspecified
            or effective.is_link_local
            or effective.is_multicast
            or effective.is_reserved
            or is_deprecated_site_local
        ):
            raise RemoteHttpError(f"remote event source address is prohibited: {effective.compressed}")
        if not any(effective.version == network.version and effective in network for network in self.allowlist):
            raise RemoteHttpError(
                f"remote event source address is not present in the allow-list: {effective.compressed}"
            )

    def _endpoint(
        self,
        family: int,
        sockaddr: tuple,
    ) -> ResolvedEndpoint:
        raw_address = sockaddr[0]
        if not isinstance(raw_address, str) or "%" in raw_address:
            raise RemoteHttpError("remote event source resolved to an unsupported scoped address")
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise RemoteHttpError("remote event source resolved to an invalid address") from exc
        self._validate_address(address)
        normalized_sockaddr: tuple
        if family == socket.AF_INET:
            normalized_sockaddr = (address.compressed, self.port)
        elif family == socket.AF_INET6:
            flowinfo = sockaddr[2] if len(sockaddr) > 2 else 0
            scope_id = sockaddr[3] if len(sockaddr) > 3 else 0
            normalized_sockaddr = (address.compressed, self.port, flowinfo, scope_id)
        else:
            raise RemoteHttpError("remote event source resolved to an unsupported address family")
        return ResolvedEndpoint(
            family=family,
            sockaddr=normalized_sockaddr,
            address=address.compressed,
            effective_address=_effective_address(address).compressed,
        )

    def _resolve_endpoints(self) -> tuple[ResolvedEndpoint, ...]:
        if self._literal_address is not None:
            family = socket.AF_INET6 if isinstance(self._literal_address, ipaddress.IPv6Address) else socket.AF_INET
            sockaddr = (
                (self._literal_address.compressed, self.port, 0, 0)
                if family == socket.AF_INET6
                else (self._literal_address.compressed, self.port)
            )
            return (self._endpoint(family, sockaddr),)
        try:
            results = socket.getaddrinfo(
                self.host,
                self.port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except OSError as exc:
            raise RemoteHttpError("remote event source DNS resolution failed") from exc
        endpoints: list[ResolvedEndpoint] = []
        for family, socktype, _protocol, _canonical_name, sockaddr in results:
            if family not in {socket.AF_INET, socket.AF_INET6} or socktype != socket.SOCK_STREAM:
                continue
            endpoint = self._endpoint(family, sockaddr)
            if endpoint not in endpoints:
                endpoints.append(endpoint)
        if not endpoints:
            raise RemoteHttpError("remote event source DNS resolution returned no usable addresses")
        return tuple(endpoints)

    def _resolve_endpoint(self) -> ResolvedEndpoint:
        return self._resolve_endpoints()[0]

    def get(self, path: str) -> RemoteHttpResponse:
        parsed_path = urllib.parse.urlsplit(path)
        if (
            not path.startswith("/")
            or path.startswith("//")
            or parsed_path.scheme
            or parsed_path.netloc
            or parsed_path.fragment
        ):
            raise RemoteHttpConfigurationError("remote event source request path is invalid")
        deadline = time.monotonic() + self.timeout_s
        endpoint = self._resolve_endpoint()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RemoteHttpError("remote event source request timed out")
        connection = _PinnedHTTPConnection(self.host, self.port, endpoint, remaining)
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "application/json",
                    "Connection": "close",
                    "Host": self.host_header,
                },
            )
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise RemoteHttpError("remote event source redirect is prohibited")
            if response.status == 413:
                raise RemoteHttpResponseTooLarge("remote event source response is too large")
            content_type = response.getheader("Content-Type", "")
            content_type_parts = [part.strip() for part in content_type.split(";")]
            media_type = content_type_parts[0].lower()
            if media_type != "application/json":
                raise RemoteHttpError("remote event source response Content-Type must be application/json")
            parameters = content_type_parts[1:]
            if parameters:
                parameter_name, separator, parameter_value = parameters[0].partition("=")
                if (
                    len(parameters) != 1
                    or not separator
                    or parameter_name.strip().lower() != "charset"
                    or not parameter_value.strip()
                ):
                    raise RemoteHttpError("remote event source response Content-Type permits only a charset parameter")
            content_length = response.getheader("Content-Length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except ValueError as exc:
                    raise RemoteHttpError("remote event source response Content-Length is invalid") from exc
                if declared_length < 0:
                    raise RemoteHttpError("remote event source response Content-Length is invalid")
                if declared_length > MAX_REMOTE_RESPONSE_BYTES:
                    raise RemoteHttpResponseTooLarge("remote event source response is too large")
            body = bytearray()
            while len(body) <= MAX_REMOTE_RESPONSE_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RemoteHttpError("remote event source request timed out")
                if response.fp is not None and getattr(response.fp, "raw", None) is not None:
                    response_socket = getattr(response.fp.raw, "_sock", None)
                    if response_socket is not None:
                        response_socket.settimeout(remaining)
                chunk = response.read(min(_READ_CHUNK_BYTES, MAX_REMOTE_RESPONSE_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
            if len(body) > MAX_REMOTE_RESPONSE_BYTES:
                raise RemoteHttpResponseTooLarge("remote event source response is too large")
            return RemoteHttpResponse(status=response.status, body=bytes(body))
        except RemoteHttpError:
            raise
        except TimeoutError as exc:
            raise RemoteHttpError("remote event source request timed out") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise RemoteHttpError("remote event source request failed") from exc
        finally:
            connection.close()
