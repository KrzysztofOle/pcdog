"""Nieuprzywilejowany klient zamkniętego API hardware-agenta."""

from __future__ import annotations

import json
from pathlib import Path
import socket

from .hardware_agent import DEFAULT_SOCKET_PATH, MAX_REQUEST_BYTES, PROTOCOL_VERSION, unavailable_reading
from .inputs import InputReading
from .models import HddActivity, PowerLedState


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
