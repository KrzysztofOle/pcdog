"""Entry point read-only runtime PcDog dla usługi systemd."""

from __future__ import annotations

import argparse
from pathlib import Path
import signal
from typing import Sequence

from .event_store import EventStore
from .web_api import create_server


# StateDirectory=pcdog-runtime zapewnia własność pcdog bez osłabiania dostępu
# do istniejącego /var/lib/pcdog z artefaktami USB/DHCP.
DEFAULT_DATABASE = Path("/var/lib/pcdog-runtime/pcdog.sqlite3")
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080


def build_parser() -> argparse.ArgumentParser:
    """Buduje jawny, minimalny interfejs uruchomieniowy bez GPIO i kontroli PC."""

    parser = argparse.ArgumentParser(description="PcDog read-only Web API i Web Panel")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def initialize_event_store(database: Path) -> None:
    """Inicjalizuje lokalny, trwały schemat SQLite przed otwarciem HTTP."""

    with EventStore(database):
        pass


def create_runtime_server(*, database: Path, host: str, port: int):
    """Tworzy serwer read-only po bezpiecznej inicjalizacji SQLite."""

    initialize_event_store(database)
    return create_server(
        host,
        port,
        lambda: EventStore(database, read_only=True),
    )


def run(*, database: Path, host: str, port: int) -> None:
    """Uruchamia jedynie read-only HTTP nad Event Store."""

    server = create_runtime_server(database=database, host=host, port=port)

    def stop_server(_signal_number: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(arguments: Sequence[str] | None = None) -> None:
    arguments = build_parser().parse_args(arguments)
    if not 1 <= arguments.port <= 65535:
        raise SystemExit("Port musi należeć do zakresu 1..65535")
    run(database=arguments.database, host=arguments.host, port=arguments.port)


if __name__ == "__main__":
    main()
