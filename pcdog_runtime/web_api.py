"""Minimalne, read-only HTTP API PcDog oparte na standard library."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from .event_store import EventStore, EventStoreError, StoredEvent
from .models import PcDogState, StateSnapshot


class HealthProvider(Protocol):
    """Minimalny kontrakt health, rozszerzalny bez wiązania z systemd."""

    def status(self) -> PcDogState:
        """Zwraca bieżący stan zdrowia runtime."""


class StaticHealthProvider:
    """Bezpieczny provider v1, nieodczytujący systemu ani sprzętu."""

    def __init__(self, state: PcDogState = PcDogState.HEALTHY) -> None:
        self._state = state

    def status(self) -> PcDogState:
        return self._state


EventStoreFactory = Callable[[], EventStore]
WEB_PANEL_DIRECTORY = Path(__file__).with_name("web_panel")
_STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/pcdog-panel.css": ("pcdog-panel.css", "text/css; charset=utf-8"),
    "/static/pcdog-panel.js": ("pcdog-panel.js", "application/javascript; charset=utf-8"),
}


class ApiRequestError(ValueError):
    """Błąd wejścia klienta z bezpieczną, stabilną odpowiedzią HTTP."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ReadOnlyApi:
    """Warstwa serializacji i odczytu nad Event Store.

    Factory musi zwracać nowe, read-only połączenie Event Store dla każdego
    wywołania. Dzięki temu HTTP server nie współdzieli surowego połączenia
    SQLite między wątkami requestów.
    """

    def __init__(
        self,
        event_store_factory: EventStoreFactory,
        *,
        health_provider: HealthProvider | None = None,
        max_event_limit: int = 100,
    ) -> None:
        if max_event_limit < 1:
            raise ValueError("max_event_limit must be at least one")
        self._event_store_factory = event_store_factory
        self._health_provider = health_provider or StaticHealthProvider()
        self._max_event_limit = max_event_limit

    def handle_get(self, path: str, query: Mapping[str, list[str]]) -> dict[str, object]:
        """Obsługuje dozwolone endpointy bez znajomości HTTP transportu."""

        if path == "/api/v1/health":
            self._require_only_parameters(query, set())
            return {"status": self._health_provider.status().value}
        if path == "/api/v1/state":
            self._require_only_parameters(query, set())
            return self._state_payload()
        if path == "/api/v1/events":
            self._require_only_parameters(query, {"limit", "after_id"})
            return self._events_payload(query)
        raise ApiRequestError(404, "NOT_FOUND", "Endpoint nie istnieje")

    def _state_payload(self) -> dict[str, object]:
        with self._event_store_factory() as store:
            snapshot = store.read_current_state()
        if snapshot is None:
            raise ApiRequestError(
                404,
                "STATE_UNAVAILABLE",
                "Bieżący stan nie jest jeszcze dostępny",
            )
        return self._snapshot_payload(snapshot)

    def _events_payload(self, query: Mapping[str, list[str]]) -> dict[str, object]:
        limit = self._integer_parameter(
            query,
            "limit",
            default=self._max_event_limit,
            minimum=1,
            maximum=self._max_event_limit,
        )
        after_id = self._integer_parameter(
            query, "after_id", default=None, minimum=0, maximum=None
        )
        with self._event_store_factory() as store:
            events = (
                store.read_recent_events(limit=limit)
                if after_id is None
                else store.read_events(after_id=after_id, limit=limit)
            )
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
    def _require_only_parameters(
        query: Mapping[str, list[str]], allowed: set[str]
    ) -> None:
        unexpected = set(query) - allowed
        if unexpected:
            raise ApiRequestError(400, "INVALID_PARAMETER", "Nieprawidłowy parametr")

    def _integer_parameter(
        self,
        query: Mapping[str, list[str]],
        name: str,
        *,
        default: int | None,
        minimum: int,
        maximum: int | None,
    ) -> int | None:
        values = query.get(name)
        if values is None:
            return default
        if len(values) != 1:
            raise ApiRequestError(400, "INVALID_PARAMETER", "Nieprawidłowy parametr")
        try:
            value = int(values[0])
        except ValueError as error:
            raise ApiRequestError(
                400, "INVALID_PARAMETER", "Nieprawidłowy parametr"
            ) from error
        if value < minimum:
            raise ApiRequestError(400, "INVALID_PARAMETER", "Nieprawidłowy parametr")
        if maximum is not None and value > maximum:
            raise ApiRequestError(400, "LIMIT_TOO_LARGE", "Przekroczono limit eventów")
        return value


class _ReadOnlyRequestHandler(BaseHTTPRequestHandler):
    """Transport HTTP bez endpointów mutujących."""

    api: ReadOnlyApi

    def do_GET(self) -> None:  # noqa: N802 - nazwa wymagana przez BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        static_file = _STATIC_FILES.get(parsed.path)
        if static_file is not None and not parsed.query:
            self._write_static(*static_file)
            return
        try:
            payload = self.api.handle_get(parsed.path, parse_qs(parsed.query, True))
            self._write_json(200, payload)
        except ApiRequestError as error:
            self._write_error(error.status, error.code, error.message)
        except EventStoreError:
            self._write_error(503, "EVENT_STORE_UNAVAILABLE", "Dane są niedostępne")
        except Exception:
            self._write_error(500, "INTERNAL_ERROR", "Wewnętrzny błąd serwera")

    def do_POST(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_HEAD(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self._write_error(405, "METHOD_NOT_ALLOWED", "API obsługuje tylko metodę GET")

    def _write_error(self, status: int, code: str, message: str) -> None:
        self._write_json(status, {"error": {"code": code, "message": message}})

    def _write_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_static(self, filename: str, content_type: str) -> None:
        """Zwraca wyłącznie jawnie dozwolone, lokalne zasoby Web Panelu."""

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
        """Testowy/local server nie zapisuje requestów do stderr."""


class PcDogApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(
    host: str,
    port: int,
    event_store_factory: EventStoreFactory,
    *,
    health_provider: HealthProvider | None = None,
    max_event_limit: int = 100,
) -> PcDogApiServer:
    """Tworzy serwer z konfigurowalnym bindem, ale go nie uruchamia."""

    api = ReadOnlyApi(
        event_store_factory,
        health_provider=health_provider,
        max_event_limit=max_event_limit,
    )
    handler = type("PcDogReadOnlyRequestHandler", (_ReadOnlyRequestHandler,), {"api": api})
    return PcDogApiServer((host, port), handler)
