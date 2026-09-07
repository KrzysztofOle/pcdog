"""HTTP API PcDog: odczyt panelu i lokalne uwierzytelnienie."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from .event_store import EventStore, EventStoreError, StoredEvent
from .models import PcDogState, StateSnapshot
from .network_status import read_network_status
from .network_agent import NetworkAgentError, validate_bssid, validate_password, validate_ssid
from .network_agent_client import connection_status, connect_wifi, list_wifi
from .system_agent_client import read_system_agent_status
from .web_auth import (
    AuthenticationError,
    SESSION_COOKIE_NAME,
    SESSION_TTL,
    WebAuthenticator,
)


class HealthProvider(Protocol):
    def status(self) -> PcDogState: ...


class StaticHealthProvider:
    def __init__(self, state: PcDogState = PcDogState.HEALTHY) -> None:
        self._state = state

    def status(self) -> PcDogState:
        return self._state


EventStoreFactory = Callable[[], EventStore]
SystemAgentStatusProvider = Callable[[], dict[str, object]]
NetworkAgentProvider = Callable[[], dict[str, object]]
NetworkAgentConnect = Callable[[str, str, str | None], dict[str, object]]
WEB_PANEL_DIRECTORY = Path(__file__).with_name("web_panel")
_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/pcdog-panel.css": ("pcdog-panel.css", "text/css; charset=utf-8"),
    "/static/pcdog-panel.js": ("pcdog-panel.js", "application/javascript; charset=utf-8"),
}


class ApiRequestError(ValueError):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ReadOnlyApi:
    """Serializacja odczytu Event Store; bez zależności od HTTP i sesji."""

    def __init__(
        self, event_store_factory: EventStoreFactory, *,
        health_provider: HealthProvider | None = None, max_event_limit: int = 100,
        system_agent_status_provider: SystemAgentStatusProvider | None = None,
        wifi_list_provider: NetworkAgentProvider | None = None,
        wifi_status_provider: NetworkAgentProvider | None = None,
        wifi_connect: NetworkAgentConnect | None = None,
    ) -> None:
        if max_event_limit < 1:
            raise ValueError("max_event_limit must be at least one")
        self._event_store_factory = event_store_factory
        self._health_provider = health_provider or StaticHealthProvider()
        self._max_event_limit = max_event_limit
        self._system_agent_status_provider = system_agent_status_provider or read_system_agent_status
        self._wifi_list_provider = wifi_list_provider or list_wifi
        self._wifi_status_provider = wifi_status_provider or connection_status
        self._wifi_connect = wifi_connect or connect_wifi

    def handle_get(self, path: str, query: Mapping[str, list[str]]) -> dict[str, object]:
        if path == "/api/v1/health":
            self._require_only_parameters(query, set())
            return {"status": self._health_provider.status().value}
        if path == "/api/v1/network":
            self._require_only_parameters(query, set())
            return read_network_status()
        if path == "/api/v1/system":
            self._require_only_parameters(query, set())
            return self._system_agent_status_provider()
        if path == "/api/v1/wifi":
            self._require_only_parameters(query, set())
            return self._wifi_list_provider()
        if path == "/api/v1/wifi/connection":
            self._require_only_parameters(query, set())
            return self._wifi_status_provider()
        if path == "/api/v1/state":
            self._require_only_parameters(query, set())
            return self._state_payload()
        if path == "/api/v1/events":
            self._require_only_parameters(query, {"limit", "after_id"})
            return self._events_payload(query)
        raise ApiRequestError(404, "NOT_FOUND", "Endpoint nie istnieje")

    def connect_wifi(self, payload: dict[str, object]) -> dict[str, object]:
        if set(payload) not in ({"ssid", "password"}, {"ssid", "bssid", "password"}):
            raise ApiRequestError(400, "INVALID_WIFI_REQUEST", "Nieprawidłowe dane Wi-Fi")
        try:
            ssid = validate_ssid(payload.get("ssid"))
            bssid = validate_bssid(payload.get("bssid"))
            password = validate_password(payload.get("password"))
        except NetworkAgentError as error:
            raise ApiRequestError(400, error.code, "Nieprawidłowe dane Wi-Fi") from error
        result = self._wifi_connect(ssid, password, bssid)
        status = result.get("status")
        if status == "BUSY":
            raise ApiRequestError(409, "WIFI_CHANGE_BUSY", "Zmiana Wi-Fi jest już w toku")
        if status in {"UNAVAILABLE", "NETWORK_MANAGER_UNAVAILABLE"}:
            raise ApiRequestError(503, "NETWORK_AGENT_UNAVAILABLE", "Agent sieciowy jest niedostępny")
        if status != "STARTED":
            raise ApiRequestError(400, "WIFI_CHANGE_REJECTED", "Nie można rozpocząć zmiany Wi-Fi")
        return result

    def _state_payload(self) -> dict[str, object]:
        with self._event_store_factory() as store:
            snapshot = store.read_current_state()
        if snapshot is None:
            raise ApiRequestError(404, "STATE_UNAVAILABLE", "Bieżący stan nie jest jeszcze dostępny")
        return self._snapshot_payload(snapshot)

    def _events_payload(self, query: Mapping[str, list[str]]) -> dict[str, object]:
        limit = self._integer_parameter(query, "limit", default=self._max_event_limit, minimum=1, maximum=self._max_event_limit)
        after_id = self._integer_parameter(query, "after_id", default=None, minimum=0, maximum=None)
        with self._event_store_factory() as store:
            events = store.read_recent_events(limit=limit) if after_id is None else store.read_events(after_id=after_id, limit=limit)
        return {"events": [self._event_payload(event) for event in events]}

    @staticmethod
    def _snapshot_payload(snapshot: StateSnapshot) -> dict[str, object]:
        return {
            "pc_state": snapshot.pc_state.value,
            "power_led": snapshot.power_led.value,
            "power_led_reliable": snapshot.power_led_reliable,
            "hdd_activity": snapshot.hdd_activity.value,
            "hdd_activity_reliable": snapshot.hdd_activity_reliable,
            "pcdog_state": snapshot.pcdog_state.value,
            "updated_at_utc": ReadOnlyApi._utc_text(snapshot.timestamp_utc),
        }

    @staticmethod
    def _event_payload(stored_event: StoredEvent) -> dict[str, object]:
        event = stored_event.event
        return {
            "id": stored_event.id,
            "timestamp_utc": ReadOnlyApi._utc_text(event.timestamp_utc),
            "event_type": event.event_type.value,
            "source": event.source.value,
            "old_value": event.old_value.value,
            "new_value": event.new_value.value,
            "details": event.details,
        }

    @staticmethod
    def _utc_text(timestamp) -> str:
        return timestamp.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _require_only_parameters(query: Mapping[str, list[str]], allowed: set[str]) -> None:
        if set(query) - allowed:
            raise ApiRequestError(400, "INVALID_PARAMETER", "Nieprawidłowy parametr")

    def _integer_parameter(self, query: Mapping[str, list[str]], name: str, *, default: int | None, minimum: int, maximum: int | None) -> int | None:
        values = query.get(name)
        if values is None:
            return default
        if len(values) != 1:
            raise ApiRequestError(400, "INVALID_PARAMETER", "Nieprawidłowy parametr")
        try:
            value = int(values[0])
        except ValueError as error:
            raise ApiRequestError(400, "INVALID_PARAMETER", "Nieprawidłowy parametr") from error
        if value < minimum:
            raise ApiRequestError(400, "INVALID_PARAMETER", "Nieprawidłowy parametr")
        if maximum is not None and value > maximum:
            raise ApiRequestError(400, "LIMIT_TOO_LARGE", "Przekroczono limit eventów")
        return value


class _RequestHandler(BaseHTTPRequestHandler):
    api: ReadOnlyApi
    auth: WebAuthenticator

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        static_file = _STATIC_FILES.get(parsed.path)
        if static_file is not None and not parsed.query:
            self._write_static(*static_file)
            return
        try:
            if parsed.path == "/api/v1/session":
                if parsed.query:
                    raise ApiRequestError(400, "INVALID_PARAMETER", "Nieprawidłowy parametr")
                session = self.auth.session(self._session_token())
                self._write_json(200, {"authenticated": True, "csrf_token": session.csrf_token})
                return
            if parsed.path != "/api/v1/health":
                self.auth.session(self._session_token())
            payload = self.api.handle_get(parsed.path, parse_qs(parsed.query, True))
            self._write_json(200, payload)
        except AuthenticationError as error:
            self._write_error(error.status, error.code, error.message)
        except ApiRequestError as error:
            self._write_error(error.status, error.code, error.message)
        except EventStoreError:
            self._write_error(503, "EVENT_STORE_UNAVAILABLE", "Dane są niedostępne")
        except Exception:
            self._write_error(500, "INTERNAL_ERROR", "Wewnętrzny błąd serwera")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.query or parsed.path not in {"/api/v1/session", "/api/v1/wifi/connection"}:
            self._method_not_allowed()
            return
        try:
            payload = self._json_body()
            if parsed.path == "/api/v1/session":
                if set(payload) != {"password"} or not isinstance(payload["password"], str):
                    raise ApiRequestError(400, "INVALID_REQUEST", "Nieprawidłowe dane logowania")
                session = self.auth.login(payload["password"], self.client_address[0])
                self._write_json(200, {"authenticated": True, "csrf_token": session.csrf_token}, cookie=self._session_cookie(session.token))
                return
            if parsed.path == "/api/v1/wifi/connection":
                self._require_same_origin()
                self.auth.require_write(self._session_token(), self.headers.get("X-PcDog-CSRF"))
                self._write_json(202, self.api.connect_wifi(payload))
                return
            self._method_not_allowed()
        except AuthenticationError as error:
            self._write_error(error.status, error.code, error.message)
        except ApiRequestError as error:
            self._write_error(error.status, error.code, error.message)
        except Exception:
            self._write_error(500, "INTERNAL_ERROR", "Wewnętrzny błąd serwera")
        except Exception:
            self._write_error(500, "INTERNAL_ERROR", "Wewnętrzny błąd serwera")

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/session" or parsed.query:
            self._method_not_allowed()
            return
        try:
            self._require_same_origin()
            token = self._session_token()
            self.auth.require_write(token, self.headers.get("X-PcDog-CSRF"))
            self.auth.logout(token)
            self._write_json(200, {"authenticated": False}, cookie=self._expired_session_cookie())
        except AuthenticationError as error:
            self._write_error(error.status, error.code, error.message)
        except ApiRequestError as error:
            self._write_error(error.status, error.code, error.message)

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_HEAD(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _json_body(self) -> dict[str, object]:
        if self.headers.get("Content-Type") != "application/json":
            raise ApiRequestError(415, "UNSUPPORTED_MEDIA_TYPE", "Wymagany jest JSON")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError as error:
            raise ApiRequestError(400, "INVALID_REQUEST", "Nieprawidłowe dane żądania") from error
        if not 1 <= length <= 4096:
            raise ApiRequestError(400, "INVALID_REQUEST", "Nieprawidłowe dane żądania")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ApiRequestError(400, "INVALID_REQUEST", "Nieprawidłowe dane żądania") from error
        if not isinstance(payload, dict):
            raise ApiRequestError(400, "INVALID_REQUEST", "Nieprawidłowe dane żądania")
        return payload

    def _session_token(self) -> str | None:
        try:
            cookie = SimpleCookie(self.headers.get("Cookie"))
            morsel = cookie.get(SESSION_COOKIE_NAME)
            return None if morsel is None else morsel.value
        except (AttributeError, TypeError):
            return None

    def _require_same_origin(self) -> None:
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        if not host or not origin or not hmac.compare_digest(origin, "http://" + host):
            raise ApiRequestError(403, "ORIGIN_INVALID", "Nieprawidłowe pochodzenie żądania")

    @staticmethod
    def _session_cookie(token: str) -> str:
        return f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={int(SESSION_TTL.total_seconds())}"

    @staticmethod
    def _expired_session_cookie() -> str:
        return f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"

    def _method_not_allowed(self) -> None:
        self._write_error(405, "METHOD_NOT_ALLOWED", "Endpoint nie obsługuje tej metody")

    def _write_error(self, status: int, code: str, message: str) -> None:
        self._write_json(status, {"error": {"code": code, "message": message}})

    def _write_json(self, status: int, payload: dict[str, object], *, cookie: str | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _write_static(self, filename: str, content_type: str) -> None:
        try:
            body = (WEB_PANEL_DIRECTORY / filename).read_bytes()
        except OSError:
            self._write_error(500, "STATIC_ASSET_UNAVAILABLE", "Panel jest niedostępny")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


class PcDogApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(
    host: str, port: int, event_store_factory: EventStoreFactory, *,
    health_provider: HealthProvider | None = None, max_event_limit: int = 100,
    authenticator: WebAuthenticator | None = None,
    system_agent_status_provider: SystemAgentStatusProvider | None = None,
    wifi_list_provider: NetworkAgentProvider | None = None,
    wifi_status_provider: NetworkAgentProvider | None = None,
    wifi_connect: NetworkAgentConnect | None = None,
) -> PcDogApiServer:
    api = ReadOnlyApi(
        event_store_factory, health_provider=health_provider, max_event_limit=max_event_limit,
        system_agent_status_provider=system_agent_status_provider,
        wifi_list_provider=wifi_list_provider,
        wifi_status_provider=wifi_status_provider,
        wifi_connect=wifi_connect,
    )
    handler = type("PcDogRequestHandler", (_RequestHandler,), {
        "api": api,
        "auth": authenticator or WebAuthenticator(None),
    })
    return PcDogApiServer((host, port), handler)
