"""Minimalny, uprzywilejowany agent systemowy PcDog.

Etap 3 udostępnia wyłącznie status przez lokalny socket Unix. Operacje zasilania
są celowo wyłączone: moduł nie importuje ``subprocess`` i nie wykonuje systemctl.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socketserver
from typing import Sequence


DEFAULT_SOCKET_PATH = Path("/run/pcdog-system-agent/agent.sock")
MAX_REQUEST_BYTES = 256
PROTOCOL_VERSION = 1


class SystemAgentRequestHandler(socketserver.StreamRequestHandler):
    """Obsługuje dokładnie jedno, krótkie żądanie JSON zakończone nową linią."""

    def handle(self) -> None:
        raw_request = self.rfile.readline(MAX_REQUEST_BYTES + 1)
        self._write(handle_request(raw_request))

    def _write(self, response: dict[str, object]) -> None:
        self.wfile.write(json.dumps(response, separators=(",", ":")).encode("utf-8") + b"\n")


def handle_request(raw_request: bytes) -> dict[str, object]:
    """Waliduje jedyne dozwolone żądanie, niezależnie od transportu socketu."""

    if len(raw_request) > MAX_REQUEST_BYTES or not raw_request.endswith(b"\n"):
        return {"status": "INVALID_REQUEST"}
    try:
        request = json.loads(raw_request.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "INVALID_REQUEST"}
    if request != {"operation": "status"}:
        return {"status": "ACTION_NOT_ENABLED"}
    return {
        "status": "READY",
        "protocol_version": PROTOCOL_VERSION,
        "actions_enabled": False,
    }


class SystemAgentServer(socketserver.UnixStreamServer):
    allow_reuse_address = True


def create_server(socket_path: Path) -> SystemAgentServer:
    """Tworzy socket root:pcdog, który może tylko raportować status."""

    if socket_path.exists():
        raise RuntimeError(f"Socket już istnieje: {socket_path}")
    server = SystemAgentServer(str(socket_path), SystemAgentRequestHandler)
    socket_path.chmod(0o660)
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PcDog system-agent (operacje wyłączone)")
    parser.add_argument("--socket", type=Path, default=DEFAULT_SOCKET_PATH)
    return parser


def main(arguments: Sequence[str] | None = None) -> None:
    arguments = build_parser().parse_args(arguments)
    with create_server(arguments.socket) as server:
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
