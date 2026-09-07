"""Lokalne testy loopback read-only HTTP API PcDog."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from pcdog_runtime import (
    DomainEvent,
    EventSource,
    EventStore,
    EventStoreError,
    EventType,
    HddActivity,
    PcDogState,
    PcState,
    PowerLedState,
    StateSnapshot,
    create_server,
)
from pcdog_runtime.web_auth import WebAuthenticator


BASE_TIME = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def snapshot(
    *,
    pc_state: PcState = PcState.ON,
    power_led: PowerLedState = PowerLedState.ON,
    timestamp: datetime = BASE_TIME,
) -> StateSnapshot:
    return StateSnapshot(
        pc_state=pc_state,
        power_led=power_led,
        power_led_reliable=True,
        hdd_activity=HddActivity.ACTIVE,
        hdd_activity_reliable=True,
        pcdog_state=PcDogState.HEALTHY,
        timestamp_utc=timestamp,
    )


def event(
    *, timestamp: datetime = BASE_TIME, details: dict[str, object] | None = None
) -> DomainEvent:
    return DomainEvent(
        timestamp_utc=timestamp,
        event_type=EventType.PC_STATE_CHANGED,
        source=EventSource.STATE_ENGINE,
        old_value=PcState.OFF,
        new_value=PcState.ON,
        details=details,
    )


class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = TemporaryDirectory()
        self.database = Path(self._directory.name) / "pcdog.db"
        EventStore(self.database).close()
        self.auth = WebAuthenticator.from_password("correct horse battery staple")
        self.session = self.auth.login("correct horse battery staple", "127.0.0.1")
        self.server, self.thread = self._start_server(
            lambda: EventStore(self.database, read_only=True), max_event_limit=2
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self._directory.cleanup()

    def _start_server(self, factory, *, max_event_limit: int, system_agent_status_provider=None):
        server = create_server(
            "127.0.0.1", 0, factory, max_event_limit=max_event_limit,
            authenticator=self.auth,
            system_agent_status_provider=system_agent_status_provider,
        )
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def request(self, method: str, path: str, *, headers=None, body=None) -> tuple[int, str, dict[str, object]]:
        host, port = self.server.server_address
        self.assertEqual(host, "127.0.0.1")
        connection = HTTPConnection(host, port, timeout=2)
        request_headers = {"Cookie": f"pcdog_session={self.session.token}", **(headers or {})}
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        content_type = response.getheader("Content-Type")
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        return response.status, content_type, payload

    def request_without_session(self, method: str, path: str, *, headers=None, body=None):
        host, port = self.server.server_address
        connection = HTTPConnection(host, port, timeout=2)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        result = response.status, response.getheader("Set-Cookie"), payload
        connection.close()
        return result

    def raw_request(self, path: str) -> tuple[int, str, str]:
        host, port = self.server.server_address
        connection = HTTPConnection(host, port, timeout=2)
        connection.request("GET", path)
        response = connection.getresponse()
        content_type = response.getheader("Content-Type")
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, content_type, body

    def write(self, events: list[DomainEvent], state: StateSnapshot) -> None:
        with EventStore(self.database) as store:
            store.persist(events=events, snapshot=state)

    def test_health_is_json_and_healthy(self) -> None:
        status, content_type, payload = self.request("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertEqual(payload, {"status": "HEALTHY"})

        status, _, payload = self.request_without_session("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "HEALTHY"})

    def test_panel_data_requires_authenticated_session(self) -> None:
        status, _, payload = self.request_without_session("GET", "/api/v1/state")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "AUTH_REQUIRED")

    def test_system_agent_status_requires_login_and_never_enables_actions(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server, self.thread = self._start_server(
            lambda: EventStore(self.database, read_only=True), max_event_limit=2,
            system_agent_status_provider=lambda: {"status": "READY", "protocol_version": 1, "actions_enabled": False},
        )
        status, _, payload = self.request_without_session("GET", "/api/v1/system")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "AUTH_REQUIRED")
        status, _, payload = self.request("GET", "/api/v1/system")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "READY", "protocol_version": 1, "actions_enabled": False})

    def test_root_serves_observational_web_panel_as_html(self) -> None:
        status, content_type, body = self.raw_request("/")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        self.assertIn("Komputer", body)
        for view in ("status", "history", "network", "settings"):
            self.assertIn(f'data-view="{view}"', body)
            self.assertIn(f'href="#{view}"', body)

    def test_web_panel_static_assets_are_available_with_explicit_types(self) -> None:
        for path, content_type in (
            ("/static/pcdog-panel.css", "text/css; charset=utf-8"),
            ("/static/pcdog-panel.js", "application/javascript; charset=utf-8"),
        ):
            with self.subTest(path=path):
                status, received_type, body = self.raw_request(path)
                self.assertEqual(status, 200)
                self.assertEqual(received_type, content_type)
                self.assertTrue(body)

    def test_state_serializes_enums_and_utc_timestamp(self) -> None:
        self.write([], snapshot())
        status, _, payload = self.request("GET", "/api/v1/state")
        self.assertEqual(status, 200)
        self.assertEqual(payload["pc_state"], "ON")
        self.assertEqual(payload["power_led"], "ON")
        self.assertEqual(payload["hdd_activity"], "ACTIVE")
        self.assertEqual(payload["pcdog_state"], "HEALTHY")
        self.assertEqual(payload["updated_at_utc"], "2026-09-05T12:00:00Z")

    def test_empty_state_is_explicitly_unavailable(self) -> None:
        status, _, payload = self.request("GET", "/api/v1/state")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "STATE_UNAVAILABLE")

    def test_events_obey_limit_and_keep_id_order(self) -> None:
        events = [event(timestamp=BASE_TIME + timedelta(seconds=index)) for index in range(3)]
        self.write(events, snapshot())
        status, _, payload = self.request("GET", "/api/v1/events?limit=2")
        self.assertEqual(status, 200)
        result = payload["events"]
        self.assertEqual([item["id"] for item in result], [2, 3])

    def test_events_support_after_id_and_details(self) -> None:
        self.write([event(), event(details={"reason": "debounce"})], snapshot())
        status, _, payload = self.request("GET", "/api/v1/events?after_id=1&limit=2")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in payload["events"]], [2])
        self.assertEqual(payload["events"][0]["details"], {"reason": "debounce"})

    def test_invalid_and_excessive_limits_are_rejected(self) -> None:
        for limit in ("0", "-1", "text", "3"):
            with self.subTest(limit=limit):
                status, _, payload = self.request("GET", f"/api/v1/events?limit={limit}")
                self.assertEqual(status, 400)
                self.assertIn(payload["error"]["code"], {"INVALID_PARAMETER", "LIMIT_TOO_LARGE"})

    def test_unknown_endpoint_and_non_get_method_return_json_errors(self) -> None:
        status, content_type, payload = self.request("GET", "/api/v1/missing")
        self.assertEqual(status, 404)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertEqual(payload["error"]["code"], "NOT_FOUND")

        status, _, payload = self.request("POST", "/api/v1/state")
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "METHOD_NOT_ALLOWED")

    def test_http_login_session_and_csrf_logout(self) -> None:
        status, cookie, payload = self.request_without_session(
            "POST", "/api/v1/session",
            headers={"Content-Type": "application/json"},
            body=json.dumps({"password": "correct horse battery staple"}),
        )
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertTrue(payload["csrf_token"])
        token = cookie.split(";", 1)[0]

        status, _, session = self.request_without_session("GET", "/api/v1/session", headers={"Cookie": token})
        self.assertEqual(status, 200)
        self.assertTrue(session["authenticated"])

        status, _, payload = self.request_without_session("GET", "/api/v1/session?password=secret", headers={"Cookie": token})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_PARAMETER")

        status, _, payload = self.request_without_session(
            "DELETE", "/api/v1/session",
            headers={"Cookie": token, "X-PcDog-CSRF": session["csrf_token"], "Origin": f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"},
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["authenticated"])

    def test_logout_rejects_missing_origin_or_csrf(self) -> None:
        status, _, payload = self.request_without_session(
            "DELETE", "/api/v1/session",
            headers={"Cookie": f"pcdog_session={self.session.token}", "X-PcDog-CSRF": self.session.csrf_token},
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["error"]["code"], "ORIGIN_INVALID")

    def test_login_rejects_secret_in_query_and_invalid_body(self) -> None:
        status, _, payload = self.request_without_session("POST", "/api/v1/session?password=secret")
        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "METHOD_NOT_ALLOWED")
        status, _, payload = self.request_without_session(
            "POST", "/api/v1/session", headers={"Content-Type": "application/json"},
            body=json.dumps({"password": "wrong"}),
        )
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "INVALID_CREDENTIALS")

    def test_event_store_error_is_safe(self) -> None:
        failing_server, thread = self._start_server(
            lambda: self._raise_event_store_error(), max_event_limit=2
        )
        try:
            host, port = failing_server.server_address
            connection = HTTPConnection(host, port, timeout=2)
            connection.request("GET", "/api/v1/events", headers={"Cookie": f"pcdog_session={self.session.token}"})
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, 503)
            self.assertEqual(payload["error"]["code"], "EVENT_STORE_UNAVAILABLE")
            self.assertNotIn("traceback", json.dumps(payload).lower())
            self.assertNotIn(str(self.database), json.dumps(payload))
        finally:
            failing_server.shutdown()
            failing_server.server_close()
            thread.join()

    def _raise_event_store_error(self) -> EventStore:
        raise EventStoreError(f"internal path: {self.database}")


class WebPanelSourceTests(unittest.TestCase):
    """Kontrakty UI możliwe do sprawdzenia bez przeglądarki lub Node.js."""

    panel_directory = Path(__file__).parents[1] / "pcdog_runtime" / "web_panel"

    @property
    def javascript(self) -> str:
        return (self.panel_directory / "pcdog-panel.js").read_text(encoding="utf-8")

    @property
    def stylesheet(self) -> str:
        return (self.panel_directory / "pcdog-panel.css").read_text(encoding="utf-8")

    def test_panel_uses_auth_and_read_only_api_endpoints(self) -> None:
        endpoints = set(re.findall(r'["`](/api/v1/[^?"`]+)', self.javascript))
        self.assertEqual(
            endpoints,
            {"/api/v1/health", "/api/v1/state", "/api/v1/events", "/api/v1/network", "/api/v1/system", "/api/v1/session"},
        )
        self.assertIn('method: "POST"', self.javascript)
        self.assertIn('method: "DELETE"', self.javascript)
        self.assertNotRegex(self.javascript.lower(), r"/api/v1/(power|reset|control)")

    def test_panel_has_only_auth_controls_and_no_external_assets(self) -> None:
        html = (self.panel_directory / "index.html").read_text(encoding="utf-8").lower()
        self.assertIn('<form id="login-form">', html)
        self.assertIn('id="logout-button"', html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("http://", self.stylesheet)
        self.assertNotIn("https://", self.stylesheet)
        self.assertNotIn("websocket", self.javascript.lower())
        self.assertNotIn("eventsource", self.javascript.lower())
        self.assertIn("csrfToken", self.javascript)
        self.assertIn('credentials: "same-origin"', self.javascript)

    def test_state_values_have_text_and_non_color_visual_distinction(self) -> None:
        self.assertIn("element.textContent = shown", self.javascript)
        self.assertIn("renderUnavailableState", self.javascript)
        self.assertIn('setBadge(id, "UNKNOWN")', self.javascript)
        for css_class in (".badge-on", ".badge-off", ".badge-unknown"):
            self.assertIn(css_class, self.stylesheet)

    def test_health_states_and_event_failures_are_presentable(self) -> None:
        for css_class in (".badge-healthy", ".badge-degraded", ".badge-error"):
            self.assertIn(css_class, self.stylesheet)
        self.assertIn("Promise.allSettled", self.javascript)
        self.assertIn("renderEventsUnavailable", self.javascript)
        self.assertIn("Brak zapisanych zdarzeń.", self.javascript)
        self.assertIn("STATE_UNAVAILABLE", self.javascript)

    def test_polling_is_configurable_and_does_not_overlap(self) -> None:
        self.assertIn("pollingIntervalMs: 5000", self.javascript)
        self.assertIn("eventsLimit: 25", self.javascript)
        self.assertIn("if (refreshInFlight || !csrfToken) return", self.javascript)
        self.assertIn("window.setInterval(refresh, CONFIG.pollingIntervalMs)", self.javascript)

    def test_mobile_navigation_and_history_contract(self) -> None:
        self.assertIn('window.addEventListener("hashchange"', self.javascript)
        self.assertIn('section.hidden = section.dataset.view !== view', self.javascript)
        self.assertIn('link.setAttribute("aria-current", "page")', self.javascript)
        self.assertIn('[...events].reverse()', self.javascript)
        self.assertIn('env(safe-area-inset-bottom)', self.stylesheet)
        self.assertIn('min-height: 48px', self.stylesheet)
        self.assertNotIn('min-width: 700px', self.stylesheet)
        self.assertNotIn('innerHTML', self.javascript)


if __name__ == "__main__":
    unittest.main()
