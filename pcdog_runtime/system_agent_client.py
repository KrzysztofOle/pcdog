"""Nieuprzywilejowany klient statusu agenta systemowego PcDog."""

from __future__ import annotations

import json
from pathlib import Path
import socket

from .system_agent import DEFAULT_SOCKET_PATH, MAX_REQUEST_BYTES, PROTOCOL_VERSION


def read_system_agent_status(socket_path: Path = DEFAULT_SOCKET_PATH, *, timeout: float = 0.5) -> dict[str, object]:
    """Zwraca bezpieczny status albo ``UNAVAILABLE`` bez ujawniania błędów systemu."""

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(socket_path))
            connection.sendall(b'{"operation":"status"}\n')
            response = connection.makefile("rb").readline(MAX_REQUEST_BYTES + 1)
        payload = json.loads(response.decode("utf-8"))
        if payload != {
            "status": "READY",
            "protocol_version": PROTOCOL_VERSION,
            "actions_enabled": False,
        }:
            raise ValueError("Nieprawidłowa odpowiedź agenta")
        return payload
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {"status": "UNAVAILABLE"}
