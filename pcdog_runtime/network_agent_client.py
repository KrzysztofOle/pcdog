"""Nieuprzywilejowany klient zamkniętego protokołu network-agenta."""
from __future__ import annotations

import json
from pathlib import Path
import socket

from .network_agent import DEFAULT_SOCKET_PATH, MAX_REQUEST_BYTES


def request_network_agent(request: dict[str, object], socket_path: Path = DEFAULT_SOCKET_PATH, *, timeout: float = 1.0) -> dict[str, object]:
    try:
        raw = json.dumps(request, separators=(",", ":")).encode("utf-8")
        if len(raw) + 1 > MAX_REQUEST_BYTES:
            return {"status": "INVALID_WIFI_REQUEST"}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(socket_path))
            connection.sendall(raw + b"\n")
            response = connection.makefile("rb").readline(MAX_REQUEST_BYTES + 1)
        payload = json.loads(response.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            raise ValueError
        return payload
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return {"status": "UNAVAILABLE"}


def list_wifi() -> dict[str, object]:
    return request_network_agent({"operation": "list_wifi"})


def connection_status() -> dict[str, object]:
    return request_network_agent({"operation": "connection_status"})



def connect_wifi(ssid: str, password: str, bssid: str | None = None) -> dict[str, object]:
    request: dict[str, object] = {"operation": "connect_wifi", "ssid": ssid, "password": password}
    if bssid is not None:
        request["bssid"] = bssid
    return request_network_agent(request)
