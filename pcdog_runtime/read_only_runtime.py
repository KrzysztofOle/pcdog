"""Entry point read-only runtime PcDog dla usługi systemd."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import signal
from threading import Event, Thread
from typing import Sequence

from .event_store import EventStore
from .hardware_agent_client import HardwareAgentInputSource
from .input_monitor import InputMonitor, InputMonitorConfig
from .state_engine import StateEngine
from .web_api import create_server
from .web_auth import WebAuthenticator


# StateDirectory=pcdog-runtime zapewnia własność pcdog bez osłabiania dostępu
# do istniejącego /var/lib/pcdog z artefaktami USB/DHCP.
DEFAULT_DATABASE = Path("/var/lib/pcdog-runtime/pcdog.sqlite3")
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
DEFAULT_AUTH_CONFIG = Path("/etc/pcdog/web-auth.json")
DEFAULT_INPUT_POLL_INTERVAL = 0.25
DEFAULT_INPUT_MONITOR_CONFIG = InputMonitorConfig(
    power_debounce=timedelta(seconds=1),
    unreliable_power_timeout=timedelta(seconds=2),
    hdd_active_hold=timedelta(milliseconds=500),
)


class RuntimeInputMonitor:
    """Pętla zapisu wejść; awaria agenta daje UNKNOWN i nie zatrzymuje HTTP."""

    def __init__(self, database: Path, source: HardwareAgentInputSource, *, poll_interval: float = DEFAULT_INPUT_POLL_INTERVAL) -> None:
        self._database = database
        self._source = source
        self._poll_interval = poll_interval
        self._stop = Event()
        self._thread: Thread | None = None
        self._last_persisted_signature: tuple[object, ...] | None = None

    def poll_once(self, monitor: InputMonitor, store: EventStore) -> None:
        update = monitor.poll_once()
        snapshot = update.snapshot
        signature = (
            snapshot.pc_state, snapshot.power_led, snapshot.power_led_reliable,
            snapshot.hdd_activity, snapshot.hdd_activity_reliable, snapshot.pcdog_state,
        )
        if signature != self._last_persisted_signature:
            store.persist_update(update)
            self._last_persisted_signature = signature

    def start(self) -> None:
        self._thread = Thread(target=self._run, name="pcdog-input-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        monitor = InputMonitor(self._source, StateEngine(), DEFAULT_INPUT_MONITOR_CONFIG)
        try:
            with EventStore(self._database) as store:
                while not self._stop.is_set():
                    try:
                        self.poll_once(monitor, store)
                    except Exception:
                        # A transient SQLite or input failure must not terminate monitoring.
                        pass
                    self._stop.wait(self._poll_interval)
        except Exception:
            # The HTTP process remains available; an agent/service restart retries later.
            return


def build_parser() -> argparse.ArgumentParser:
    """Buduje jawny, minimalny interfejs uruchomieniowy bez GPIO i kontroli PC."""

    parser = argparse.ArgumentParser(description="PcDog read-only Web API i Web Panel")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--auth-config", type=Path, default=DEFAULT_AUTH_CONFIG)
    return parser


def initialize_event_store(database: Path) -> None:
    """Inicjalizuje lokalny, trwały schemat SQLite przed otwarciem HTTP."""

    with EventStore(database):
        pass


def create_runtime_server(
    *, database: Path, host: str, port: int, auth_config: Path = DEFAULT_AUTH_CONFIG
):
    """Tworzy serwer read-only po bezpiecznej inicjalizacji SQLite."""

    initialize_event_store(database)
    return create_server(
        host,
        port,
        lambda: EventStore(database, read_only=True),
        authenticator=WebAuthenticator.from_config(auth_config),
    )


def run(*, database: Path, host: str, port: int, auth_config: Path) -> None:
    """Uruchamia HTTP oraz obserwacyjny monitor GPIO przez local IPC."""

    server = create_runtime_server(database=database, host=host, port=port, auth_config=auth_config)
    monitor = RuntimeInputMonitor(database, HardwareAgentInputSource())
    monitor.start()

    def stop_server(_signal_number: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()
        server.server_close()


def main(arguments: Sequence[str] | None = None) -> None:
    arguments = build_parser().parse_args(arguments)
    if not 1 <= arguments.port <= 65535:
        raise SystemExit("Port musi należeć do zakresu 1..65535")
    run(database=arguments.database, host=arguments.host, port=arguments.port, auth_config=arguments.auth_config)


if __name__ == "__main__":
    main()
