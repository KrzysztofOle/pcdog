"""Nieuprzywilejowany klient zamkniętego API hardware-agenta."""

from __future__ import annotations

import json
from pathlib import Path
import socket

from .hardware_agent import DEFAULT_SOCKET_PATH, MAX_REQUEST_BYTES, PROTOCOL_VERSION, unavailable_reading
from .inputs import InputReading
from .models import HddActivity, PowerLedState


class HardwareAgentControlClient:
    """Klient dwóch semantycznych operacji impulsowych hardware-agenta."""

    def __init__(self, socket_path: Path = DEFAULT_SOCKET_PATH, *, timeout: float = 2.0) -> None:
        self._socket_path = socket_path
        self._timeout = timeout

    def pulse_power(self, duration_ms: int | None = None) -> int:
        return self._pulse("pulse_power", duration_ms)

    def pulse_reset(self, duration_ms: int | None = None) -> int:
        return self._pulse("pulse_reset", duration_ms)

    def _pulse(self, operation: str, duration_ms: int | None) -> int:
        request: dict[str, object] = {"operation": operation}
        if duration_ms is not None:
            request["duration_ms"] = duration_ms
        response = self._request(request)
        if response.get("status") != "PULSE_COMPLETED" or not isinstance(response.get("duration_ms"), int):
            raise RuntimeError(f"Hardware-agent odrzucił impuls: {response.get('status', 'INVALID_RESPONSE')}")
        return response["duration_ms"]

    def _request(self, request: dict[str, object]) -> dict[str, object]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self._timeout)
            connection.connect(str(self._socket_path))
            connection.sendall(json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n")
            raw_response = connection.makefile("rb").readline(MAX_REQUEST_BYTES + 1)
        response = json.loads(raw_response.decode("utf-8"))
        if not isinstance(response, dict):
            raise ValueError("Nieprawidłowa odpowiedź hardware-agenta")
        return response


class HardwareAgentInputSource:
    """Zwraca UNKNOWN/niewiarygodne dane przy utracie agenta lub protokołu."""

    def __init__(self, socket_path: Path = DEFAULT_SOCKET_PATH, *, timeout: float = 0.5) -> None:
        self._socket_path = socket_path
        self._timeout = timeout

    def read(self) -> InputReading:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self._timeout)
                connection.connect(str(self._socket_path))
                connection.sendall(b'{"operation":"read_inputs"}\n')
                raw_response = connection.makefile("rb").readline(MAX_REQUEST_BYTES + 1)
            response = json.loads(raw_response.decode("utf-8"))
            return self._parse_response(response)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            return unavailable_reading()

    @staticmethod
    def _parse_response(response: object) -> InputReading:
        if not isinstance(response, dict) or response.get("status") != "READY" or response.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("Nieprawidłowa odpowiedź hardware-agenta")
        if not isinstance(response.get("power_led_reliable"), bool) or not isinstance(response.get("hdd_activity_reliable"), bool):
            raise ValueError("Nieprawidłowa wiarygodność wejścia")
        return InputReading(
            power_led=PowerLedState(response["power_led"]), power_led_reliable=response["power_led_reliable"],
            hdd_activity=HddActivity(response["hdd_activity"]), hdd_activity_reliable=response["hdd_activity_reliable"],
        )
