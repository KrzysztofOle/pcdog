"""Testy entrypointu produkcyjnego read-only runtime PcDog."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch
from http.client import HTTPConnection

from pcdog_runtime import EventStore
from pcdog_runtime import read_only_runtime


class ReadOnlyRuntimeTests(unittest.TestCase):
    def test_defaults_bind_only_ipv4_wildcard_on_preferred_port(self) -> None:
        arguments = read_only_runtime.build_parser().parse_args([])
        self.assertEqual(arguments.host, "0.0.0.0")
        self.assertEqual(arguments.port, 8080)
        self.assertEqual(arguments.database, Path("/var/lib/pcdog-runtime/pcdog.sqlite3"))

    def test_initialization_creates_readable_event_store(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "runtime" / "pcdog.sqlite3"
            database.parent.mkdir()
            read_only_runtime.initialize_event_store(database)
            self.assertTrue(database.is_file())
            with EventStore(database, read_only=True) as store:
                self.assertIsNone(store.read_current_state())

    def test_runtime_server_exposes_health_panel_and_unavailable_state(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "pcdog.sqlite3"
            server = read_only_runtime.create_runtime_server(
                database=database, host="127.0.0.1", port=0
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                connection = HTTPConnection(host, port, timeout=2)
                for path, expected_status in (
                    ("/api/v1/health", 200),
                    ("/", 200),
                    ("/api/v1/state", 404),
                ):
                    connection.request("GET", path)
                    response = connection.getresponse()
                    response.read()
                    self.assertEqual(response.status, expected_status)
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_invalid_port_stops_before_runtime_starts(self) -> None:
        with patch.object(read_only_runtime, "run") as run:
            with self.assertRaisesRegex(SystemExit, "1..65535"):
                read_only_runtime.main(["--port", "0"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
